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

    ready = summary.get("win_rate", 0) >= 0.60 and summary.get("rr", 0) >= 2.0
    _bot_state["ready_for_live"] = ready

    return {
        "is_running": _bot_state["is_running"],
        "is_training": _bot_state["is_training"],
        "ready_for_live": ready,
        "model_exists": MODEL_PATH.exists(),
        "open_positions": len(open_trades),
        "last_win_rate": summary.get("win_rate"),
        "last_rr": summary.get("rr"),
        "last_trained": model_run.get("trained_at") if model_run else None,
        "symbols": summary.get("symbols", ["BTC/USDT", "ETH/USDT"]),
    }


# ── Train ─────────────────────────────────────────────────────────────────────
@app.post("/train")
async def trigger_train(background_tasks: BackgroundTasks):
    if _bot_state["is_training"]:
        raise HTTPException(400, "Eğitim zaten devam ediyor")

    def run_training():
        _bot_state["is_training"] = True
        _push_event({"phase": "server", "msg": "Eğitim başlatıldı"})
        try:
            import train_engine
            # broadcast fonksiyonunu bizim _push_event ile bağla
            train_engine.broadcast = _push_event
            train_engine.main(run_server=False)
            # Backtest sonuçlarını oku
            p = REPORTS_DIR / "backtest_summary.json"
            if p.exists():
                _bot_state["last_summary"] = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            _push_event({"phase": "error", "msg": str(e)})
        finally:
            _bot_state["is_training"] = False

    background_tasks.add_task(run_training)
    return {"status": "started"}


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
async def get_trades(limit: int = 100, offset: int = 0):
    db = Database()
    await db.connect()
    try:
        return await db.fetch_trades(limit=limit, offset=offset)
    finally:
        await db.close()


# ── Bot Start/Stop ────────────────────────────────────────────────────────────
@app.post("/bot/start")
async def bot_start(background_tasks: BackgroundTasks, testnet: bool = True):
    if _bot_state["is_running"]:
        raise HTTPException(400, "Bot zaten çalışıyor")
    if not _bot_state["ready_for_live"] and not testnet:
        raise HTTPException(403, "Backtest kriterleri karşılanmadan mainnet trade başlatılamaz (WR>60% + R:R>2.0 gerekli)")
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


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
