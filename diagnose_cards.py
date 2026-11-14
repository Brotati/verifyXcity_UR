#!/usr/bin/env python3
"""Diagnostic script to inspect Verify modal DOM, checkboxes, images, and server JSON."""
import sys
import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

# Add agent directory to sys.path
sys.path.insert(0, str(Path(__file__).parent / "agent"))
from common import load_creds, VERIFY_BASE

applicant_query = sys.argv[1] if len(sys.argv) > 1 else "Farjana Mouree"
print(f"=== Diagnosing Verify modal for: {applicant_query} ===")

creds = load_creds()
server_data = {}

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(viewport={"width": 1700, "height": 1100})
    page = context.new_page()

    def on_response(response):
        if "json" in response.headers.get("content-type", ""):
            try:
                data = response.json()
                if isinstance(data, dict) and "trips" in str(data):
                    server_data["report"] = data
            except Exception:
                pass

    page.on("response", on_response)

    # 1. Login
    print("Logging into Verify...")
    page.goto(VERIFY_BASE + "/login", wait_until="domcontentloaded", timeout=60000)
    page.get_by_role("button", name="Login", exact=True).wait_for(timeout=60000)
    page.wait_for_timeout(2000)
    email = page.locator("input[type=text]").first
    email.press_sequentially(creds["verify_email"], delay=25)
    page.locator("input[type=password]").fill(creds["verify_pass"])
    page.locator("button[type=submit]").click()
    page.wait_for_url("**/dashboard", wait_until="domcontentloaded", timeout=60000)

    # 2. Go to reports and search
    print(f"Searching reports for '{applicant_query}'...")
    page.goto(VERIFY_BASE + "/reports", wait_until="domcontentloaded", timeout=60000)
    search_input = page.locator("input[placeholder*='Search files' i]")
    search_input.wait_for(timeout=60000)
    page.wait_for_timeout(2000)
    search_input.fill(applicant_query)
    page.get_by_role("button", name="Search", exact=True).click()
    page.wait_for_timeout(4000)

    # 3. Find row and click Update Topsheet
    rows = page.locator("table tr").filter(has_text=applicant_query)
    count = rows.count()
    if count == 0:
        # Fallback search with suffix
        print("Applicant query returned 0 rows in table, falling back to 0066853...")
        search_input.fill("0066853")
        page.get_by_role("button", name="Search", exact=True).click()
        page.wait_for_timeout(4000)
        rows = page.locator("table tr").filter(has_text="0066853")
        count = rows.count()

    print(f"Found {count} matching row(s) in reports table.")
    if count == 0:
        print("ERROR: No matching rows found!")
        browser.close()
        sys.exit(1)

    target_row = rows.first
    topsheet_btn = target_row.locator("button:has(svg[data-icon='file-text'])")
    if topsheet_btn.count() == 0:
        print("ERROR: No Update Topsheet button found in row!")
        browser.close()
        sys.exit(1)

    print("Opening Update Topsheet modal...")
    topsheet_btn.click()
    modal = page.get_by_role("dialog")
    modal.wait_for(timeout=60000)
    page.wait_for_timeout(2000)

    # 4. Discover trips in modal sidebar
    trip_elements = modal.get_by_text(re.compile(r"^Trip \d+$")).all()
    trip_ids = [re.search(r"\d+", el.inner_text()).group() for el in trip_elements]
    print(f"Modal opened! Sidebar Trip IDs: {trip_ids}")

    results = {"applicant": applicant_query, "trips": {}}

    out_dir = Path("runs/diagnose")
    out_dir.mkdir(parents=True, exist_ok=True)

    for trip_id in trip_ids:
        print(f"\n--- Inspecting Trip #{trip_id} ---")
        trip_label = modal.get_by_text(f"Trip {trip_id}", exact=True)
        sidebar_text = trip_label.locator("xpath=../..").inner_text().strip()
        print(f"Sidebar Concern: {sidebar_text}")
        trip_label.click()
        page.wait_for_timeout(2000)

        # Screenshot
        shot_path = out_dir / f"trip_{trip_id}.png"
        modal.screenshot(path=str(shot_path))
        print(f"Screenshot saved: {shot_path}")

        # Check total checkboxes in modal
        all_checkboxes = modal.locator("input[type=checkbox]").all()
        print(f"Total checkboxes in modal: {len(all_checkboxes)}")

        # Check images
        all_images = modal.locator("img").all()
        print(f"Total images in modal: {len(all_images)}")

        checkbox_info = []
        for idx, cb in enumerate(all_checkboxes, 1):
            val = cb.get_attribute("value") or ""
            cb_id = cb.get_attribute("id") or ""
            name = cb.get_attribute("name") or ""
            checked = cb.is_checked()
            
            # Ancestor hierarchy info
            ancestor_info = cb.evaluate("""el => {
                let p = el.parentElement;
                let levels = [];
                for (let i = 0; i < 4 && p; i++) {
                    levels.push({
                        tag: p.tagName,
                        cls: p.className,
                        text: (p.innerText || '').slice(0, 100).replace(/\\n/g, ' ')
                    });
                    p = p.parentElement;
                }
                return levels;
            }""")
            
            # Near image info
            near_img = cb.evaluate("""el => {
                let card = el.closest('.ant-card, .ant-col, div');
                let img = card ? card.querySelector('img') : null;
                return img ? {src: img.src, alt: img.alt} : null;
            }""")

            info = {
                "index": idx,
                "value": val,
                "id": cb_id,
                "name": name,
                "checked": checked,
                "ancestors": ancestor_info,
                "near_img": near_img
            }
            checkbox_info.append(info)
            label_text = ancestor_info[1]['text'] if len(ancestor_info) > 1 else ancestor_info[0]['text']
            print(f"  Checkbox #{idx}: value={val!r}, id={cb_id!r}, near_img={bool(near_img)}, label={label_text!r}")

        results["trips"][trip_id] = {
            "concern": sidebar_text,
            "checkboxes": checkbox_info,
            "images_count": len(all_images)
        }

    # Save full dump
    (out_dir / "diagnose_report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if server_data:
        (out_dir / "diagnose_server.json").write_text(json.dumps(server_data, indent=2), encoding="utf-8")
        print("\nCaptured Verify API JSON saved to runs/diagnose/diagnose_server.json")

    print("\n=== Diagnosis Complete ===")
    print("Inspect screenshots in runs/diagnose/ and runs/diagnose/diagnose_report.json")
    browser.close()
