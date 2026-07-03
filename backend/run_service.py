"""
Servis sarmalayıcısı — Task Scheduler görevleri bu dosya üzerinden çalışır.

Kullanım:
  pythonw.exe run_service.py api.py      → backend/api.py'yi python ile çalıştırır
  pythonw.exe run_service.py frontend    → Vite dev sunucusunu (npm run dev) çalıştırır

- Alt süreci penceresiz (CREATE_NO_WINDOW) başlatır
- stdout/stderr'i backend/logs/<ad>.log dosyasına yazar (5 MB'da döndürür)
- Alt süreç kill-on-close Job Object'e atanır → sarmalayıcı ölünce çocuklar da ölür
- Alt sürecin çıkış kodunu aynen iletir → süreç çökerse (kod != 0)
  Task Scheduler "hata durumunda yeniden başlat" ayarı devreye girer
"""
import ctypes
import shutil
import subprocess
import sys
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
MAX_LOG_BYTES = 5 * 1024 * 1024

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"


def _assign_kill_on_close_job(proc: subprocess.Popen) -> None:
    """
    Alt süreci KILL_ON_JOB_CLOSE bayraklı bir Job Object'e atar.
    Bu sarmalayıcı HANGİ yolla ölürse ölsün (schtasks /end, taskkill,
    çökme) job handle kapanır ve alt süreç de otomatik ölür — öksüz
    python süreçleri birikmez.
    """
    if sys.platform != "win32":
        return
    try:
        k32 = ctypes.windll.kernel32

        class _BASIC(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class _IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _EXTENDED(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC),
                ("IoInfo", _IO),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        h_job = k32.CreateJobObjectW(None, None)
        info = _EXTENDED()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        k32.SetInformationJobObject(
            h_job, JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info))
        k32.AssignProcessToJobObject(h_job, int(proc._handle))
        # h_job kasıtlı olarak açık bırakılır: bu süreç ölünce handle kapanır
    except Exception:
        pass


def _build_command() -> tuple:
    """(komut_listesi, çalışma_dizini, log_adı) döner."""
    target = sys.argv[1]

    # Özel mod: frontend (Vite dev sunucusu)
    if target == "frontend":
        frontend_dir = HERE.parent / "frontend"
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
        if not (frontend_dir / "node_modules").exists():
            subprocess.run([npm, "install"], cwd=str(frontend_dir), timeout=300,
                           creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return [npm, "run", "dev", "--", "--host"], frontend_dir, "frontend"

    # Varsayılan mod: backend dizinindeki python scripti
    script = HERE / target
    if not script.is_file():
        raise FileNotFoundError(f"script bulunamadı: {script}")
    python = sys.executable.replace("pythonw.exe", "python.exe")
    return [python, "-u", str(script), *sys.argv[2:]], HERE, script.stem


def main() -> int:
    if len(sys.argv) < 2:
        print("kullanım: run_service.py <script.py|frontend> [argümanlar...]")
        return 2

    try:
        cmd, cwd, name = _build_command()
    except FileNotFoundError as e:
        print(e)
        return 2

    LOGS.mkdir(exist_ok=True)
    log_path = LOGS / f"{name}.log"

    # Basit log rotasyonu: 5 MB'ı aşınca .old'a taşı (tek yedek tut)
    try:
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            old = log_path.with_suffix(".log.old")
            if old.exists():
                old.unlink()
            log_path.rename(old)
    except Exception:
        pass

    with log_path.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n=== {name} başlatılıyor ===\n")
        f.flush()
        flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=f,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        _assign_kill_on_close_job(proc)
        try:
            return proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
