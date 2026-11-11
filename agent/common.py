#!/usr/bin/env python3
"""Shared config and helpers for the Verify -> City Bank upload agent."""
import os
import sys
import getpass
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Resolve independently of the shell's working directory. Keep explicitly set
# process variables, and treat password '$' characters literally.
load_dotenv(PROJECT_ROOT / ".env", override=False, interpolate=False)
RUNS_DIR = PROJECT_ROOT / "runs"              # downloads, screenshots, logs per run
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"    # final compressed PDFs for upload
RUNS_DIR.mkdir(exist_ok=True)
ARTIFACTS_DIR.mkdir(exist_ok=True)

VERIFY_BASE = os.environ.get("VERIFY_BASE", "https://verify.bmapsbd.com").rstrip("/")
CITY_BASE = os.environ.get("CITY_BASE", "https://cityfastagent.citybankplc.com").rstrip("/")

# ---------------------------------------------------------------- credentials
def load_creds(path: Path | None = None) -> dict:
    """Load credentials from process variables, root .env, then creds.md.

    Process variables take precedence over .env; creds.md fills missing values.
    Keys: VERIFY_EMAIL, VERIFY_PASS, CITY_ID, CITY_PASS.
    Never print or log the returned values.
    """
    creds = {
        "verify_email": os.environ.get("VERIFY_EMAIL"),
        "verify_pass": os.environ.get("VERIFY_PASS"),
        "city_id": os.environ.get("CITY_ID"),
        "city_pass": os.environ.get("CITY_PASS"),
        "verify_base": VERIFY_BASE,
        "city_base": CITY_BASE,
    }
    path = path or PROJECT_ROOT / "creds.md"
    if path.exists():
        text = path.read_text()
        import re
        m = re.search(r"verify dashboard url\s*:\s*(\S+)", text)
        if m: creds.setdefault("verify_base", m.group(1))
        m = re.search(r"email\s*:\s*(\S+)", text)
        if m and not creds["verify_email"]: creds["verify_email"] = m.group(1)
        m = re.search(r"pass\s*:\s*(\S+)", text)  # first pass = verify
        if m and not creds["verify_pass"]: creds["verify_pass"] = m.group(1)
        m = re.search(r"city bank url\s*:\s*(\S+)", text)
        if m: creds.setdefault("city_base", m.group(1))
        m = re.search(r"id\s*:\s*(\d+)", text)
        if m and not creds["city_id"]: creds["city_id"] = m.group(1)
        passes = re.findall(r"pass\s*:\s*(\S+)", text)
        if len(passes) > 1 and not creds["city_pass"]:
            creds["city_pass"] = passes[1]
        m = re.search(r"to choose file no\s*:\s*(\S+)", text)
        if m: creds["file_no"] = m.group(1)
    missing = [k for k in ("verify_email", "verify_pass", "city_id", "city_pass") if not creds.get(k)]
    if missing:
        print(f"Missing credentials: {missing}. Set process variables, root .env, or creds.md.", file=sys.stderr)
        sys.exit(2)
    return creds


def ask_file_no(default: str | None = None) -> str:
    """Operator supplies the file number; preserved as typed (leading zeros kept)."""
    raw = input(f"File serial number to process {f'[{default}] ' if default else ''}: ").strip()
    value = raw or (default or "")
    if not value:
        sys.exit("No file number supplied.")
    return value


def run_dir(serial: str) -> Path:
    d = RUNS_DIR / serial
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "compressed").mkdir(parents=True, exist_ok=True)
    (d / "shots").mkdir(parents=True, exist_ok=True)
    return d
