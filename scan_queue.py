#!/usr/bin/env python3
"""Quick read-only scan of all 25 queue applicants in Barikoi Verify to check attachment counts."""
import sys
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent / "agent"))
from common import load_creds, VERIFY_BASE

discovery_path = Path("runs/daily/2026-11-12/discovery.json")
if not discovery_path.exists():
    print("ERROR: discovery.json not found!")
    sys.exit(1)

discovery_data = json.loads(discovery_path.read_text(encoding="utf-8"))
jobs = discovery_data.get("jobs", [])
print(f"Loaded {len(jobs)} jobs for {discovery_data.get('date')}")

creds = load_creds()
results = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1700, "height": 1100})
    page = context.new_page()

    latest_report_data = {}

    def on_response(response):
        if "json" in response.headers.get("content-type", ""):
            try:
                data = response.json()
                if isinstance(data, dict) and "trips" in str(data):
                    latest_report_data["current"] = data
            except Exception:
                pass

    page.on("response", on_response)

    print("Logging into Verify...")
    page.goto(VERIFY_BASE + "/login", wait_until="domcontentloaded", timeout=60000)
    page.get_by_role("button", name="Login", exact=True).wait_for(timeout=60000)
    page.wait_for_timeout(2000)
    email = page.locator("input[type=text]").first
    email.press_sequentially(creds["verify_email"], delay=25)
    page.locator("input[type=password]").fill(creds["verify_pass"])
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/dashboard", wait_until="domcontentloaded", timeout=60000)

    page.goto(VERIFY_BASE + "/reports", wait_until="domcontentloaded", timeout=60000)
    search_input = page.locator("input[placeholder*='Search files' i]")
    search_input.wait_for(timeout=60000)
    page.wait_for_timeout(2000)

    print("\nScanning queue applicants in Verify...\n" + "="*70)

    for idx, job in enumerate(jobs, 1):
        serial = job["serial"]
        suffix = serial.split("-")[-1]
        applicant = job["applicant"]
        latest_report_data.clear()

        # Search by suffix
        search_input.fill(suffix)
        page.get_by_role("button", name="Search", exact=True).click()
        page.wait_for_timeout(2500)

        rows = page.locator("table tr").filter(has_text=suffix)
        count = rows.count()
        if count == 0:
            # Fallback search by applicant
            search_input.fill(applicant)
            page.get_by_role("button", name="Search", exact=True).click()
            page.wait_for_timeout(2500)
            rows = page.locator("table tr").filter(has_text=applicant)
            count = rows.count()

        if count == 0:
            print(f"[{idx:02d}/25] {serial} | {applicant}: NOT FOUND in Verify reports")
            results.append({"serial": serial, "applicant": applicant, "status": "NOT_FOUND", "trips": []})
            continue

        target_row = rows.first
        topsheet_btn = target_row.locator("button:has(svg[data-icon='file-text'])")
        if topsheet_btn.count() == 0:
            print(f"[{idx:02d}/25] {serial} | {applicant}: No Topsheet button")
            results.append({"serial": serial, "applicant": applicant, "status": "NO_TOPSHEET", "trips": []})
            continue

        topsheet_btn.click()
        modal = page.get_by_role("dialog")
        try:
            modal.wait_for(timeout=15000)
            page.wait_for_timeout(1500)
        except Exception:
            print(f"[{idx:02d}/25] {serial} | {applicant}: Modal timeout")
            continue

        # Extract trips from intercepted API or modal
        trips_summary = []
        raw_report = latest_report_data.get("current", {})
        data_outcome = raw_report.get("data", {}).get("outcome", {}) if isinstance(raw_report, dict) else {}
        server_trips = data_outcome.get("trips", [])

        if server_trips:
            for st in server_trips:
                t_type = st.get("type", "UNKNOWN")
                t_id = st.get("id")
                atts = st.get("attachments", [])
                att_labels = [a.get("title") or a.get("label") or f"id:{a.get('id')}" for a in atts]
                trips_summary.append({
                    "id": t_id,
                    "type": t_type,
                    "count": len(atts),
                    "attachments": att_labels
                })
        else:
            # Fallback reading DOM sidebar
            trip_elements = modal.get_by_text(re.compile(r"^Trip \d+$")).all()
            for te in trip_elements:
                m = re.search(r"\d+", te.inner_text())
                if m:
                    trips_summary.append({"id": m.group(), "type": "DOM", "count": "?", "attachments": []})

        # Close modal
        close_btn = modal.locator(".ant-modal-close")
        if close_btn.count():
            close_btn.first.click()
            modal.wait_for(state="hidden", timeout=10000)
        else:
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)

        # Summarize
        summary_str = ", ".join(f"{t['type']}={t['count']}" for t in trips_summary)
        all_ready = any(t['count'] > 0 for t in trips_summary if isinstance(t['count'], int))
        status_label = "HAS ATTACHMENTS" if all_ready else "EMPTY TRIPS"
        print(f"[{idx:02d}/25] {serial} | {applicant}: {summary_str} [{status_label}]")

        results.append({
            "serial": serial,
            "applicant": applicant,
            "status": status_label,
            "trips": trips_summary
        })

    out_file = Path("runs/daily/2026-11-12/verify_scan_results.json")
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("="*70 + f"\nScan finished! Saved to {out_file}")
    browser.close()
