"""Background daemon for HireHuntPilot.

Runs the full pipeline (discover -> enrich -> score -> tailor -> cover -> pdf -> apply) on a schedule.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from hirehuntpilot.config import APP_DIR, LOG_DIR, load_env, ensure_dirs
from hirehuntpilot.database import get_stats

PID_FILE = APP_DIR / "daemon.pid"
LOG_FILE = LOG_DIR / "daemon.log"

logger = logging.getLogger("hirehuntpilot.daemon")

def setup_daemon_logging():
    ensure_dirs()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

def send_telegram_notification(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        import httpx
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        httpx.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as exc:
        logger.warning("Failed to send Telegram notification: %s", exc)

def is_running() -> int | None:
    """Return the PID if the daemon is running, else None."""
    if not PID_FILE.exists():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
        
    # Check if process is still active
    if sys.platform == "win32":
        try:
            import ctypes
            PROCESS_QUERY_INFORMATION = 0x0400
            SYNCHRONIZE = 0x00100000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | SYNCHRONIZE, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return pid
            return None
        except Exception:
            return pid # fallback
    else:
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            return None

def start_daemon():
    """Spawn the background daemon process."""
    load_env()
    pid = is_running()
    if pid:
        print(f"Daemon is already running with PID {pid}.")
        return

    ensure_dirs()
    
    # Detach process
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x00000008  # DETACHED_PROCESS
        
    # Spawn background daemon
    log_f = open(LOG_FILE, "a", encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, "-m", "hirehuntpilot.daemon", "run"],
        stdout=log_f,
        stderr=log_f,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True
    )
    
    PID_FILE.write_text(str(p.pid))
    print(f"Started HireHuntPilot daemon (PID {p.pid}).")
    print(f"Logs: {LOG_FILE}")

def stop_daemon():
    """Stop the background daemon process."""
    pid = is_running()
    if not pid:
        print("Daemon is not running.")
        # Clean up stale pidfile if any
        if PID_FILE.exists():
            PID_FILE.unlink()
        return

    print(f"Stopping daemon (PID {pid})...")
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 15) # SIGTERM
        except OSError:
            pass
            
    # Clean up pidfile
    if PID_FILE.exists():
        PID_FILE.unlink()
    print("Daemon stopped.")

def run_loop():
    """Blocking daemon loop."""
    setup_daemon_logging()
    logger.info("HireHuntPilot background daemon started (PID %d)", os.getpid())
    
    # Save own PID to double-check
    PID_FILE.write_text(str(os.getpid()))
    
    # Wait for other components to boot/stabilize
    load_env()
    
    interval = int(os.environ.get("DAEMON_INTERVAL", "1800")) # default 30 min
    
    while True:
        try:
            logger.info("Starting pipeline run...")
            
            # Record stats before run
            stats_before = get_stats()
            
            # Run all pipeline stages
            from hirehuntpilot.pipeline import run_pipeline
            # discover -> enrich -> score -> tailor -> cover -> pdf
            run_pipeline(stages=["all"], min_score=7, dry_run=False)
            
            # Run auto-apply
            from hirehuntpilot.apply.launcher import main as apply_main
            
            # Get count of ready to apply before applying
            stats_mid = get_stats()
            ready_count = stats_mid.get("ready_to_apply", 0)
            
            if ready_count > 0:
                logger.info("Found %d jobs ready to apply. Launching auto-apply...", ready_count)
                # apply to ready jobs (limit to 5 per loop iteration to be safe)
                apply_main(limit=5, min_score=7, headless=True)
                
            # Compare stats for notification
            stats_after = get_stats()
            new_discovered = stats_after["total"] - stats_before["total"]
            new_applied = stats_after["applied"] - stats_before["applied"]
            
            msg_parts = []
            if new_discovered > 0:
                msg_parts.append(f"🔍 Discovered {new_discovered} new job(s).")
            if new_applied > 0:
                msg_parts.append(f"✅ Applied to {new_applied} job(s) successfully.")
                
            if msg_parts:
                send_telegram_notification(
                    "📊 *HireHuntPilot Daemon Update*\n" + "\n".join(msg_parts)
                )
                
            logger.info("Pipeline run complete. Sleeping for %d seconds...", interval)
        except Exception as exc:
            logger.error("Error in daemon loop: %s", exc, exc_info=True)
            send_telegram_notification(f"⚠️ *HireHuntPilot Daemon Error*\n{exc}")
            
        time.sleep(interval)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        run_loop()
