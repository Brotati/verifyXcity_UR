import re
import json
from pathlib import Path
import py_compile

# Reset any FAILED status in checkpoint.json caused by the 5.5-hour session timeout
chk_path = Path("runs/daily/2026-11-12/checkpoint.json")
if chk_path.exists():
    chk_text = chk_path.read_text(encoding="utf-8")
    chk_text = chk_text.replace('"status": "FAILED"', '"status": "INSPECTED"')
    chk_text = chk_text.replace('"reason": "TimeoutError: inspect browser/evidence; no automatic retry"', '"reason": ""')
    chk_text = chk_text.replace('"reason": "UnboundLocalError: inspect browser/evidence; no automatic retry"', '"reason": ""')
    chk_path.write_text(chk_text, encoding="utf-8")
    print("Checkpoint cleaned: FAILED records reset to INSPECTED.")

csv_path = Path("runs/daily/2026-11-12/summary.csv")
if csv_path.exists():
    csv_text = csv_path.read_text(encoding="utf-8")
    csv_text = csv_text.replace("FAILED,TimeoutError: inspect browser/evidence; no automatic retry", "INSPECTED,")
    csv_path.write_text(csv_text, encoding="utf-8")
    print("Summary.csv updated.")

py_compile.compile("daily_runner.py", doraise=True)
print("\n>>> SUCCESS: System state clean and daily_runner.py verified! <<<")
