"""
FastAPI — Ana REST + WebSocket API sunucusu
Run: python api.py   (eğitim + canlı trader ayrı thread'lerde başlar)
"""
import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from database import Database, get_database_path

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
MODEL_PATH = Path(__file__).resolve().parent / "model.bin"
EVENTS_LOG = Path(__file__).resolve().parent / "events.log"

# ── Event Bus (train_engine ile paylaşılır) ───────────────────────────────────
_clients: List[asyncio.Queue] = []
_clients_lock = threading.Lock()

# Bot durumu
_bot_state: Dict[str, Any] = {
    "is_running": False,
    "is_training": False,
    "ready_for_live": False,
    "last_summary": None,
    "trader_thread": None,
}


def _push_event(ev: Dict[str, Any]) -> None:
    ev = {"ts": time.time(), **ev}
    if ev.get("phase") == "health":
        _bot_state["last_health"] = ev   # /health endpoint'i için önbellek
    with _clients_lock:
        for q in list(_clients):
            try:
                q.put_nowait(ev)
            except Exception:
                pass


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Futures Scalping Bot API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    with _clients_lock:
        _clients.append(q)
    # Replay son olayı (backtest summary varsa)
    if _bot_state["last_summary"]:
        try:
            await ws.send_text(json.dumps({"phase": "backtest", "summary": _bot_state["last_summary"]}, default=str))
        except Exception:
            pass
    try:
        while True:
            ev = await q.get()
            await ws.send_text(json.dumps(ev, default=str, ensure_ascii=False))
    except Exception:
        pass
    finally:
        with _clients_lock:
            try:
                _clients.remove(q)
            except ValueError:
                pass


# ── SSE ───────────────────────────────────────────────────────────────────────
@app.get("/sse")
async def sse(request: Request):
    async def gen(q: asyncio.Queue):
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(ev, default=str, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            with _clients_lock:
                try:
                    _clients.remove(q)
                except ValueError:
                    pass

    q: asyncio.Queue = asyncio.Queue()
    with _clients_lock:
        _clients.append(q)
    return StreamingResponse(gen(q), media_type="text/event-stream")


# ── Status ────────────────────────────────────────────────────────────────────
@app.get("/status")
async def get_status():
    db = Database()
    await db.connect()
    try:
        model_run = await db.fetch_latest_model_run()
        open_trades = await db.fetch_open_trades()
    finally:
        await db.close()

    summary = _bot_state["last_summary"] or {}
    if not summary and (REPORTS_DIR / "backtest_summary.json").exists():
        try:
            summary = json.loads((REPORTS_DIR / "backtest_summary.json").read_text(encoding="utf-8"))
            _bot_state["last_summary"] = summary
        except Exception:
            pass

    # Tek doğruluk kaynağı: train_engine ready_for_live bayrağını summary'ye yazar.
    # Eski raporlarda bayrak yoksa aynı dinamik kriterle yeniden hesapla.
    if "ready_for_live" in summary:
        ready = bool(summary["ready_for_live"])
    else:
        _rr  = summary.get("rr", 0)
        _wr  = summary.get("win_rate", 0)
        _sl  = summary.get("sl_pct", 0.005)
        _tp  = summary.get("tp_pct", 0.01)
        _fee = 0.0004 * 2  # giriş + çıkış komisyonu
        _net_tp = _tp - _fee
        _net_sl = _sl + _fee
        _breakeven  = _net_sl / (_net_tp + _net_sl) if (_net_tp + _net_sl) > 0 else 1.0
        _wr_target  = min(_breakeven + 0.05, 0.60)
        _ev_positive = _wr * _net_tp > (1 - _wr) * _net_sl
        ready = (
            _wr  >= _wr_target
            and _rr  >= 1.0
            and _ev_positive
            and summary.get("sharpe", 0) >= 0.5
            and summary.get("max_drawdown", 1) <= 0.25
        )
    _bot_state["ready_for_live"] = ready

    import risk_gate
    return {
        "is_running": _bot_state["is_running"],
        "is_training": _bot_state["is_training"],
        "ready_for_live": ready,
        "panic": risk_gate.panic_active(),
        "model_exists": MODEL_PATH.exists(),
        "open_positions": len(open_trades),
        "last_win_rate": summary.get("win_rate"),
        "last_rr": summary.get("rr"),
        "last_trained": model_run.get("trained_at") if model_run else None,
        "symbols": summary.get("symbols", ["BTC/USDT", "ETH/USDT"]),
    }


# ── Train ─────────────────────────────────────────────────────────────────────
@app.post("/train")
async def trigger_train(background_tasks: BackgroundTasks, days: int = 45, force: bool = False):
    """days: eğitimde kullanılacak son gün sayısı (0 = tüm veri).
    Varsayılan 45 — tam veride sinyal rejim-bağımlı olduğu için uzun pencereler
    her iki yönü de precision kapısına takıp sinyalsiz model üretiyor.
    force=true (K-22): C-v-C kıyası atlanır, yeni model her durumda yüklenir."""
    if _bot_state["is_training"]:
        raise HTTPException(400, "Eğitim zaten devam ediyor")

    def run_training():
        import telegram_notifier as tg
        _bot_state["is_training"] = True
        _push_event({"phase": "server", "msg": f"Eğitim başlatıldı (son {days} gün)" if days else "Eğitim başlatıldı (tüm veri)"})
        tg.send_async(f"🧠 <b>Model eğitimi başladı...</b> (son {days} gün)" if days else "🧠 <b>Model eğitimi başladı...</b>")
        try:
            import train_engine
            train_engine.broadcast = _push_event
            outcome = train_engine.main(run_server=False, days=days, force_deploy=force) or {}
            if not outcome.get("deployed", True):
                # K-22: şampiyon savundu — canlı model ve dashboard raporu değişmedi
                tg.send_async(
                    f"🛡 <b>Şampiyon Savundu</b>\n"
                    f"Yeni model doğrulamada mevcut modeli yenemedi — model DEĞİŞMEDİ.\n"
                    f"Challenger EV: {outcome.get('challenger_val_ev', 0):+.2f} | "
                    f"Şampiyon EV: {outcome.get('champion_val_ev', 0):+.2f}\n"
                    f"Detay: reports/challenger_last.json"
                )
            else:
                p = REPORTS_DIR / "backtest_summary.json"
                if p.exists():
                    s = json.loads(p.read_text(encoding="utf-8"))
                    _bot_state["last_summary"] = s
                    tg.send_async(
                        f"✅ <b>Eğitim tamamlandı — yeni model görevde!</b>\n"
                        f"Win Rate: {s.get('win_rate',0)*100:.1f}% | R:R: {s.get('rr',0):.2f}\n"
                        f"Sharpe: {s.get('sharpe',0):.2f} | Max DD: {s.get('max_drawdown',0)*100:.1f}%\n"
                        f"Yön: {s.get('direction','?')} | /paper ile botu başlat"
                    )
        except Exception as e:
            _push_event({"phase": "error", "msg": str(e)})
            tg.send_async(f"❌ Eğitim hatası: {e}")
        finally:
            _bot_state["is_training"] = False

    background_tasks.add_task(run_training)
    return {"status": "started", "force": force}


# ── Candles ───────────────────────────────────────────────────────────────────
@app.get("/candles/{symbol}")
async def get_candles(symbol: str, limit: int = 200, since: int = 0):
    """DB'den mumları döner. since: Unix saniye (0 = tümü, >0 = o andan itibaren)"""
    sym = symbol.upper()
    if "/" not in sym:
        sym = sym.replace("USDT", "") + "/USDT" if sym.endswith("USDT") else sym + "/USDT"

    import sqlite3
    db_path = get_database_path()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    since_ms = since * 1000
    if since_ms > 0:
        cur.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM historical_market_data "
            "WHERE symbol = ? AND timestamp >= ? "
            "ORDER BY timestamp ASC LIMIT ?",
            (sym, since_ms, limit),
        )
        rows = cur.fetchall()
    else:
        cur.execute(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM historical_market_data "
            "WHERE symbol = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (sym, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
    conn.close()
    return [
        {"time": r[0] // 1000, "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
        for r in rows
    ]


# ── Health (K-18 / FAZ 2) ─────────────────────────────────────────────────────
@app.get("/health")
async def get_health():
    """Botun son sağlık skoru (bot çalışırken 15 sn'de bir güncellenir)."""
    h = _bot_state.get("last_health")
    if not h:
        return {"score": None, "status": "VERİ YOK",
                "msg": "Bot çalışmıyor veya henüz ilk skor üretilmedi"}
    return h


# ── Panik / Kill Switch (K-19 / FAZ 3) ────────────────────────────────────────
@app.post("/panic")
async def panic():
    """Acil durdurma: kilit dosyası yazılır, açık pozisyonlar kapatılır, bot
    durur. Kilit kalkana kadar (/panic/clear) bot yeniden BAŞLATILAMAZ."""
    import risk_gate
    import telegram_notifier as tg
    already = risk_gate.panic_active()
    risk_gate.panic_engage("manual")
    if _bot_state["is_running"]:
        import live_trader
        live_trader.panic_close_all()
    _push_event({"phase": "server",
                 "msg": "🚨 PANİK KİLİDİ DEVREDE — pozisyonlar kapatılıyor, bot durduruluyor. "
                        "Kaldırmak için: /panik_kaldir (Telegram) veya POST /panic/clear"})
    if not already:
        tg.send_async(
            "🚨 <b>PANİK KİLİDİ DEVREDE</b>\n"
            "Tüm pozisyonlar kapatılıyor, bot durduruluyor.\n"
            "Kilit kalkana kadar bot başlatılamaz.\n"
            "Kaldırmak için: /panik_kaldir"
        )
    return {"status": "panic_engaged", "was_running": _bot_state["is_running"]}


@app.post("/panic/clear")
async def panic_clear():
    """Panik kilidini elle kaldır (bot otomatik başlamaz; /paper gerekir)."""
    import risk_gate
    if not risk_gate.panic_active():
        return {"status": "not_active"}
    risk_gate.panic_clear()
    _push_event({"phase": "server", "msg": "✅ Panik kilidi kaldırıldı — bot elle başlatılabilir"})
    return {"status": "cleared"}


# ── Karar Geçmişi (K-20 / FAZ 4) ─────────────────────────────────────────────
@app.get("/decisions")
async def get_decisions(limit: int = 50, symbol: str = ""):
    """Son sinyal kararları (gerekçe kodlarıyla). NO_SIGNAL kayıtları tutulmaz."""
    db = Database()
    await db.connect()
    try:
        rows = await db.fetch_decisions(limit=limit, symbol=symbol or None)
    finally:
        await db.close()
    for r in rows:
        if r.get("detail"):
            try:
                r["detail"] = json.loads(r["detail"])
            except Exception:
                pass
    return rows


# ── Backtest Results ──────────────────────────────────────────────────────────
@app.get("/backtest")
async def get_backtest():
    p = REPORTS_DIR / "backtest_summary.json"
    if not p.exists():
        raise HTTPException(404, "Henüz backtest sonucu yok")
    return json.loads(p.read_text(encoding="utf-8"))


# ── Positions ─────────────────────────────────────────────────────────────────
@app.get("/positions")
async def get_positions():
    db = Database()
    await db.connect()
    try:
        return await db.fetch_open_trades()
    finally:
        await db.close()


# ── Trade History ─────────────────────────────────────────────────────────────
@app.get("/trades")
async def get_trades(
    limit: int = 100,
    offset: int = 0,
    since: int = 0,       # Unix saniye
    until: int = 0,       # Unix saniye
    mode: str = "all",    # "all" | "paper" | "live"
    status: str = "",     # "open" | "closed" | "cancelled" | ""
):
    paper_filter = None
    if mode == "paper":
        paper_filter = True
    elif mode == "live":
        paper_filter = False

    db = Database()
    await db.connect()
    try:
        return await db.fetch_trades(
            limit=limit,
            offset=offset,
            since_ms=since * 1000,
            until_ms=until * 1000,
            paper=paper_filter,
            status=status or None,
        )
    finally:
        await db.close()


# ── Trade Sil ────────────────────────────────────────────────────────────────
@app.delete("/trades")
async def delete_trades(ids: List[int]):
    """Seçili trade ID'lerini sil (açık olanlar korunur)."""
    if not ids:
        raise HTTPException(400, "Silinecek ID listesi boş")
    db = Database()
    await db.connect()
    try:
        placeholders = ",".join("?" * len(ids))
        await db.conn.execute(
            f"DELETE FROM trades WHERE id IN ({placeholders}) AND status != 'open'",
            ids,
        )
        await db.conn.commit()
    finally:
        await db.close()
    return {"deleted": len(ids)}


# ── Manuel Pozisyon Kapat ─────────────────────────────────────────────────────
@app.post("/positions/{symbol}/close")
async def close_position(symbol: str):
    """Açık bir pozisyonu manuel olarak market fiyatından kapat."""
    if not _bot_state["is_running"]:
        raise HTTPException(400, "Bot çalışmıyor")
    import live_trader
    live_trader.request_close(symbol)
    return {"status": "requested", "symbol": symbol}


# ── Bot Start/Stop ────────────────────────────────────────────────────────────
@app.post("/bot/start")
async def bot_start(background_tasks: BackgroundTasks, testnet: bool = True):
    import risk_gate
    if risk_gate.panic_active():
        raise HTTPException(
            423,
            "Panik kilidi aktif — bot başlatılamaz. Önce kilidi kaldırın: "
            "/panik_kaldir (Telegram) veya POST /panic/clear",
        )
    if _bot_state["is_running"]:
        raise HTTPException(400, "Bot zaten çalışıyor")
    if not _bot_state["ready_for_live"] and not testnet:
        raise HTTPException(
            403,
            "Backtest kriterleri karşılanmadan mainnet trade başlatılamaz "
            "(dinamik WR hedefi + R:R≥2.0 + pozitif EV + Sharpe≥0.5 + MaxDD≤%25 gerekli)",
        )
    if not MODEL_PATH.exists():
        raise HTTPException(404, "Model bulunamadı. Önce /train çalıştırın.")

    def run_trader():
        _bot_state["is_running"] = True
        try:
            import live_trader
            live_trader.broadcast = _push_event
            live_trader.run(testnet=testnet)
        except Exception as e:
            _push_event({"phase": "error", "msg": f"Trader hatası: {e}"})
        finally:
            _bot_state["is_running"] = False

    t = threading.Thread(target=run_trader, daemon=True)
    t.start()
    _bot_state["trader_thread"] = t
    _push_event({"phase": "server", "msg": f"Bot başlatıldı ({'testnet' if testnet else 'mainnet'})"})
    return {"status": "started", "testnet": testnet}


@app.post("/bot/stop")
async def bot_stop():
    if not _bot_state["is_running"]:
        raise HTTPException(400, "Bot zaten durmuş")
    import live_trader
    live_trader.stop()
    _push_event({"phase": "server", "msg": "Bot durduruldu"})
    return {"status": "stopped"}


@app.post("/shutdown")
async def shutdown():
    """Backend'i tamamen kapat (Telegram /durdur komutu için)."""
    import os
    _push_event({"phase": "server", "msg": "Backend kapatılıyor..."})
    threading.Thread(target=lambda: (time.sleep(0.5), os._exit(0)), daemon=True).start()
    return {"status": "shutting_down"}


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
