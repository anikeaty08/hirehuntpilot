import sys
import os
import shutil
import subprocess
import sqlite3
from pathlib import Path

def run_command(cmd, env=None):
    if env is None:
        env = os.environ.copy()
    # Force UTF-8 for console output on Windows
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    
    try:
        res = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env
        )
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)

def main():
    print("=" * 60)
    print(" HIREHUNTPILOT AUTOMATED VERIFICATION REPORT")
    print("=" * 60)
    
    # 1. Environment and python verification
    print("\n[1] Environment & Executable Check:")
    venv_python = Path(__file__).parent / ".venvtest" / "Scripts" / "python.exe"
    if not venv_python.exists():
        # fallback to standard venv name
        venv_python = Path(__file__).parent / ".venv" / "Scripts" / "python.exe"
        
    if venv_python.exists():
        print(f"  - Virtual environment found: {venv_python}")
    else:
        print("  - ERROR: Virtual environment not found in .venvtest or .venv")
        sys.exit(1)
        
    code, out, err = run_command(f'"{venv_python}" --version')
    print(f"  - Python version: {out.strip() or err.strip()}")
    
    # 2. Package installation check
    print("\n[2] Package Installation Check:")
    code, out, err = run_command(f'"{venv_python}" -m pip list')
    installed_packages = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            installed_packages[parts[0].lower()] = parts[1]
            
    for pkg in ["hirehuntpilot", "hirehunt", "playwright", "rich", "typer"]:
        if pkg in installed_packages:
            print(f"  - {pkg}: Installed ({installed_packages[pkg]})")
        else:
            print(f"  - {pkg}: MISSING")
            
    # 3. Running Doctor Command
    print("\n[3] Running 'hirehuntpilot doctor':")
    doctor_cmd = f'"{venv_python}" -m hirehuntpilot.cli doctor'
    env = os.environ.copy()
    env["HIREHUNTPILOT_DIR"] = str(Path(__file__).parent / ".runtime")
    
    code, out, err = run_command(doctor_cmd, env=env)
    if code == 0:
        print("  - Doctor command succeeded!")
        clean_lines = [line for line in out.splitlines() if line.strip() and "decrypt" not in line and "Skipping" not in line]
        for line in clean_lines[:15]:
            print(f"    {line}")
    else:
        print(f"  - Doctor command failed with code {code}!")
        print(f"    Err: {err[:200]}")
        
    # 4. Database Check
    print("\n[4] Database Schema & Stats Check:")
    db_path = Path(__file__).parent / ".runtime" / "runtime.db"
    if db_path.exists():
        print(f"  - Database exists at {db_path} (Size: {db_path.stat().st_size} bytes)")
        try:
            conn = sqlite3.connect(db_path)
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            print(f"  - Found tables: {', '.join(tables)}")
            
            # Check row counts
            for table in tables:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"    * {table} row count: {cnt}")
                
            # Check site distribution
            if "jobs" in tables:
                sites = conn.execute("SELECT site, COUNT(*) FROM jobs GROUP BY site").fetchall()
                print("    * Jobs by site:")
                for site, cnt in sites:
                    print(f"      - {site or 'Unknown'}: {cnt}")
            conn.close()
        except Exception as e:
            print(f"  - Database error: {e}")
    else:
        print("  - Database file does not exist yet.")

    # 5. Pipeline Stages Verification (Dry Run)
    print("\n[5] Pipeline Verification (Dry Run):")
    # Discover stage
    discover_cmd = f'"{venv_python}" -m hirehuntpilot.cli run discover --dry-run'
    code, out, err = run_command(discover_cmd, env=env)
    print(f"  - Run discover (dry-run): {'SUCCESS' if code == 0 else 'FAILED'}")
    
    # Enrich stage
    enrich_cmd = f'"{venv_python}" -m hirehuntpilot.cli run enrich --dry-run'
    code, out, err = run_command(enrich_cmd, env=env)
    print(f"  - Run enrich (dry-run): {'SUCCESS' if code == 0 else 'FAILED'}")

    # LLM stages (Dry Run - using local provider override to test tier check bypass)
    local_env = env.copy()
    local_env["LLM_PROVIDER"] = "local"
    local_env["LLM_URL"] = "http://localhost:11434/v1"
    ai_cmd = f'"{venv_python}" -m hirehuntpilot.cli run score tailor cover pdf --dry-run'
    code, out, err = run_command(ai_cmd, env=local_env)
    print(f"  - Run AI stages (dry-run with local config): {'SUCCESS' if code == 0 else 'FAILED'}")
    
    # Apply stage (Dry Run)
    apply_cmd = f'"{venv_python}" -m hirehuntpilot.cli apply --dry-run'
    code, out, err = run_command(apply_cmd, env=local_env)
    print(f"  - Run Apply stage (dry-run with local config): {'SUCCESS' if code == 0 else 'FAILED'}")
    
    print("\n" + "=" * 60)
    print(" VERIFICATION COMPLETE")
    print("=" * 60)

if __name__ == '__main__':
    main()
