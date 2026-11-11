#!/usr/bin/env python3
"""Read-only identity/UR smoke test. Never chooses files, uploads, or saves.

Usage: .venv/bin/python test_identity.py <NUMERIC_SERIAL> "<EXACT_APPLICANT_NAME>"
"""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, expect
from common import CITY_BASE, VERIFY_BASE, load_creds, run_dir
from city_status import check_mis_status
from city_navigation import find_bank_row


def norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def city_check(browser, creds, serial, applicant, directory):
    context = browser.new_context(viewport={"width": 1600, "height": 1000})
    page = context.new_page()
    page.goto(CITY_BASE, wait_until="domcontentloaded", timeout=60000)
    text = page.locator("body").inner_text().lower()
    if any(term in text for term in ("request rejected", "access denied", "support id", "unauthorized")):
        raise RuntimeError("City Bank rejected access; inspect the portal with the operator.")
    page.locator("input[type='text']").first.fill(creds["city_id"])
    page.locator("input[type='password']").fill(creds["city_pass"])
    page.locator("input[type='submit'], button[type='submit']").first.click()
    page.get_by_text("MY Q", exact=True).wait_for(timeout=30000)
    page.get_by_text("MY Q", exact=True).click()
    page.locator("div[role='gridcell'][columnindex='6']").first.wait_for(timeout=30000)
    page.wait_for_timeout(1500)

    # Exact suffix lookup; use the bank's serial filter if not on the first page.
    target = find_bank_row(page, serial)
    full_serial = target.locator("[columnindex='6']").inner_text().strip()
    bank_applicant = target.locator("[columnindex='5']").inner_text().strip()
    if norm(bank_applicant) != norm(applicant):
        raise RuntimeError("City Bank applicant does not match the operator's requested person.")
    print(f"CITY MATCH: {full_serial} | {bank_applicant}", flush=True)
    mis_status = check_mis_status(target)
    target.screenshot(path=str(directory / "shots" / "city_target_row.png"))
    if mis_status['skip']:
        print(f"SKIPPED {full_serial}: MIS Received (Full) in green. No UR or Verify work.", flush=True)
        context.close()
        return {'serial': full_serial, 'applicant': bank_applicant,
                'mis_status': mis_status, 'skipped': True,
                'save_clicked': False, 'files_selected': False}
    target.locator("[columnindex='2'] [onclick^='ur(']").click()
    page.locator("iframe[name='pmbwidget']").wait_for(timeout=30000)
    frame = page.frame(name="pmbwidget")
    frame.locator("input[type='file']").first.wait_for(timeout=30000)
    if full_serial not in frame.locator("body").inner_text():
        raise RuntimeError("UR serial does not match the selected bank row.")
    fields = frame.locator("input[type='file']").evaluate_all("""els => els.map(el => {
        const row = el.closest('tr');
        return {
            input_id: el.id,
            label: row.cells[0].innerText.trim(),
            change_handler: el.getAttribute('onchange'),
            existing_links: [...row.querySelectorAll('a[href]')].map(a => ({text:a.innerText, href:a.getAttribute('href')}))
        };
    })""")
    # Inspect the already-loaded handler; do not invoke it or dispatch change.
    handler = frame.evaluate("typeof uploadFile === 'function' ? uploadFile.toString() : ''")
    (directory / "city_upload_handler.txt").write_text(handler)
    page.screenshot(path=str(directory / "shots" / "city_ur.png"), full_page=True)
    for field in fields:
        print(f"  UR: {field['label']}", flush=True)
    print("CITY: no files chosen, no upload, no Save.", flush=True)
    result = {"serial": full_serial, "applicant": bank_applicant, "fields": fields,
              "mis_status": mis_status, "skipped": False,
              "save_clicked": False, "files_selected": False}
    context.close()
    return result


def verify_search(page, query):
    search = page.locator("input[placeholder*='Search files' i]")
    search.fill(query)
    page.get_by_role("button", name="Search", exact=True).click()
    # Existing results must settle after each different search.
    page.wait_for_timeout(4000)
    # Read an atomic DOM snapshot: React can replace the result rows while a
    # sequence of nth() locator reads is in progress.
    return page.locator('table tr').evaluate_all(r'''rows => rows.flatMap(row => {
        const cells=[...row.querySelectorAll(':scope > td')];
        const text=i=>cells[i]?.innerText.trim() || '';
        if(cells.length<7 || !text(2))return [];
        return [{applicant:text(1),file:text(2),status:text(3),organization:text(5),
                 trip_ids:text(6).match(/\d+/g)||[],
                 start_date:cells.length>7?text(7):null,end_date:cells.length>9?text(9):null}];
    })''')


def verify_check(browser, creds, serial, applicant, directory):
    context = browser.new_context(viewport={"width": 1700, "height": 1100})
    page = context.new_page()
    page.goto(VERIFY_BASE + "/login", wait_until="domcontentloaded", timeout=60000)
    page.get_by_role("button", name="Login", exact=True).wait_for()
    # The visible server-rendered form precedes React's event hydration.
    page.wait_for_timeout(2000)
    email = page.locator("input[type='text']").first
    email.fill("")
    email.press_sequentially(creds["verify_email"], delay=35)
    email.press("Tab")
    page.locator("input[type='password']").fill(creds["verify_pass"])
    page.locator("button[type='submit']").click()
    try:
        page.wait_for_url("**/dashboard", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        print(f"VERIFY login URL: {page.url}", flush=True)
        # Capture an error without exposing filled login inputs or tokens.
        errors = page.locator("[role='alert'], .ant-message-notice-content, .ant-form-item-explain-error").all_text_contents()
        print(f"VERIFY login messages: {errors}", flush=True)
        page.screenshot(path=str(directory / "shots" / "verify_login_check.png"),
                        mask=page.locator("input").all())
        if '/login' in page.url:
            raise RuntimeError("Verify remained at login; no repeated login attempt.") from None
    page.goto(VERIFY_BASE + "/reports", wait_until="domcontentloaded", timeout=60000)
    page.locator("input[placeholder*='Search files' i]").wait_for(timeout=30000)
    page.wait_for_timeout(2000)
    results = {}
    for query in (serial, applicant):
        rows = verify_search(page, query)
        # Retain only target-person/file evidence, not unrelated customer data.
        relevant = [r for r in rows if norm(r['applicant']) == norm(applicant)
                    or r['file'].split('-')[-1] == serial]
        results[query] = {"result_count": len(rows), "relevant": relevant}
        print(f"VERIFY SEARCH {query!r}: {len(rows)} result(s), {len(relevant)} relevant", flush=True)
        for row in relevant:
            print(f"  {row['file']} | {row['applicant']} | {row['organization']} | {row['status']} | trips {', '.join(row['trip_ids'])}", flush=True)
    matches = [r for r in results[applicant]['relevant']
               if norm(r['applicant']) == norm(applicant)
               and r['file'].split('-')[-1] == serial
               and 'city bank' in r['organization'].casefold()]
    if len(matches) != 1:
        for index, record in enumerate(matches, 1):
            print(f"  CANDIDATE {index}: start={record['start_date']}; end={record['end_date']}; trips={record['trip_ids']}", flush=True)
        target_rows = page.locator("table tr").filter(
            has=page.get_by_text(applicant, exact=True))
        for index, candidate in enumerate(target_rows.all(), 1):
            candidate.screenshot(path=str(directory / "shots" / f"verify_candidate_{index}.png"))
        context.close()
        return {"searches": results, "identity_confirmed": False,
                "blocker": "No unique match on name, file identifier, and City Bank organization."}
    match = matches[0]
    row = page.locator("table tr").filter(
        has=page.get_by_text(match['file'], exact=True)).filter(
        has=page.get_by_text(match['applicant'], exact=True))
    expect(row).to_have_count(1)
    row.screenshot(path=str(directory / "shots" / "verify_target_row.png"))
    row.locator("button:has(svg[data-icon='file-text'])").click()
    modal = page.get_by_role("dialog")
    modal.wait_for(timeout=30000)
    expect(modal).to_contain_text("Update Topsheet for Trips")
    expect(modal).to_contain_text(match['file'])
    page.wait_for_timeout(1500)
    trips = modal.get_by_text(re.compile(r"^Trip \d+$")).all_text_contents()
    links = modal.get_by_role("link").evaluate_all(
        "els => els.map(e=>({text:e.innerText, href:e.getAttribute('href')}))")
    modal.screenshot(path=str(directory / "shots" / "verify_topsheet.png"))
    print(f"VERIFY IDENTITY CONFIRMED: {match['file']}; {len(trips)} trips", flush=True)
    print("VERIFY: no report answers changed, no Save.", flush=True)
    context.close()
    return {"searches": results, "identity_confirmed": True, "match": match,
            "trips": trips, "application_links": links, "save_clicked": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", nargs='?')
    parser.add_argument("applicant", nargs='?')
    parser.add_argument('--queue', type=Path,
                        help='Operator-approved JSON list of {serial, applicant}; no uploads.')
    args = parser.parse_args()
    if args.queue:
        if args.serial or args.applicant:
            parser.error('Use either --queue or a single serial/applicant pair.')
        tasks = json.loads(args.queue.read_text())
        if not isinstance(tasks, list) or not tasks:
            parser.error('Queue must be a nonempty list of operator-approved files.')
    else:
        if not args.serial or not args.applicant:
            parser.error('Supply a serial/applicant pair, or --queue.')
        tasks = [{'serial': args.serial, 'applicant': args.applicant}]
    seen = set()
    for task in tasks:
        if (not isinstance(task, dict) or not isinstance(task.get('serial'), str)
                or not re.fullmatch(r'\d+', task['serial'])
                or not isinstance(task.get('applicant'), str) or not task['applicant'].strip()):
            parser.error('Each queue entry needs a numeric STRING serial (preserving zeros) and applicant name.')
        if task['serial'] in seen:
            parser.error('Queue contains a duplicate serial.')
        seen.add(task['serial'])
    creds = load_creds()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for task in tasks:
                serial, applicant = task['serial'], task['applicant']
                directory = run_dir(serial) / datetime.now().strftime('test_%Y%m%d_%H%M%S')
                (directory / 'shots').mkdir(parents=True, mode=0o700)
                result = {'requested_serial': serial, 'requested_applicant': applicant}
                try:
                    result['city'] = city_check(browser, creds, serial, applicant, directory)
                    if result['city']['skipped']:
                        result['status'] = 'skipped_received_full'
                        continue  # Next explicitly authorized entry, never an arbitrary MY Q row.
                    result['status'] = 'pending_file_selected'
                    result['verify'] = verify_check(browser, creds, serial, applicant, directory)
                    print(f'Pending file selected: {serial}; queue stops for review. No uploads.', flush=True)
                    break
                except Exception as error:
                    result.update(status='blocked', error=str(error))
                    raise
                finally:
                    (directory / 'result.json').write_text(json.dumps(result, indent=2))
                    print(f'Evidence: {directory}', flush=True)
            else:
                print('All operator-listed files were already Received (Full); no further work.', flush=True)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
