#!/usr/bin/env python3
"""Inspect all exact-matching Verify report rows. No downloads, selections or Save."""
import argparse
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright, expect
from common import load_creds, VERIFY_BASE, run_dir
from test_identity import city_check, norm, verify_search


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial')
    parser.add_argument('applicant')
    args = parser.parse_args()
    directory = run_dir(args.serial) / datetime.now().strftime('inventory_%Y%m%d_%H%M%S')
    (directory / 'shots').mkdir(parents=True, mode=0o700)
    creds = load_creds()
    inventory = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1700, 'height': 1100})
        page = context.new_page()
        try:
            bank = city_check(browser, creds, args.serial, args.applicant, directory)
            if bank['skipped']:
                inventory.append({'status': 'skipped_received_full',
                                  'serial': bank['serial'], 'mis_status': bank['mis_status']})
                print('Inventory skipped: green MIS Received (Full). No Verify work.', flush=True)
                return
            page.goto(VERIFY_BASE + '/login', wait_until='domcontentloaded')
            page.get_by_role('button', name='Login', exact=True).wait_for()
            page.wait_for_timeout(2000)
            page.locator("input[type='text']").first.press_sequentially(creds['verify_email'], delay=35)
            page.locator("input[type='password']").fill(creds['verify_pass'])
            page.locator("button[type='submit']").click()
            page.wait_for_url('**/dashboard', wait_until='domcontentloaded', timeout=30000)
            page.goto(VERIFY_BASE + '/reports', wait_until='domcontentloaded')
            page.locator("input[placeholder*='Search files' i]").wait_for()
            page.wait_for_timeout(2000)
            matches = [r for r in verify_search(page, args.applicant)
                       if norm(r['applicant']) == norm(args.applicant)
                       and r['file'].split('-')[-1] == args.serial
                       and 'city bank' in r['organization'].lower()]
            print(f'Exact-matching report rows: {len(matches)}', flush=True)
            for record in matches:
                # A trip ID distinguishes repeated report rows for the same file.
                rows = page.locator('table tr').filter(has=page.get_by_text(record['file'], exact=True))
                rows = rows.filter(has=page.get_by_text(record['trip_ids'][0], exact=True))
                expect(rows).to_have_count(1)
                rows.locator("button:has(svg[data-icon='file-text'])").click()
                modal = page.get_by_role('dialog')
                modal.wait_for()
                expect(modal).to_contain_text(record['file'])
                page.wait_for_timeout(1200)
                visible_ids = [re.search(r'\d+', text).group() for text in
                               modal.get_by_text(re.compile(r'^Trip \d+$')).all_text_contents()]
                report = {'file': record['file'], 'start_date': record['start_date'], 'trips': [],
                          'listed_trip_ids': record['trip_ids'], 'modal_trip_ids': visible_ids,
                          'not_in_modal': sorted(set(record['trip_ids']) - set(visible_ids))}
                inventory.append(report)
                for trip_id in visible_ids:
                    trip_label = modal.get_by_text(f'Trip {trip_id}', exact=True)
                    expect(trip_label).to_have_count(1)
                    # Capture only sidebar label, not contact/report answers.
                    ancestors = trip_label.evaluate('''el => {
                        let result=[]; for(let i=0;el && i<4;i++,el=el.parentElement)
                            result.push({tag:el.tagName, cls:el.className, text:el.innerText.slice(0,600)});
                        return result;
                    }''')
                    trip_label.click()
                    page.wait_for_timeout(1600)
                    expect(modal).to_contain_text(f'Trip #{trip_id}')
                    images = modal.locator('img').evaluate_all('''els => els.map(el=>({
                        alt:el.alt,
                        parents:[el.parentElement,el.parentElement?.parentElement,el.parentElement?.parentElement?.parentElement]
                            .map(p=>p? {cls:p.className,text:p.innerText.slice(0,700),checkboxes:p.querySelectorAll("input[type=checkbox]").length}:null)
                    }))''')
                    # Attachment sections are lower down within a scrollable panel.
                    attachment_heading = modal.get_by_text(re.compile(r'^Attachments\s*\(\d+\)$'))
                    for heading in attachment_heading.all():
                        heading.scroll_into_view_if_needed()
                    modal.screenshot(path=str(directory/'shots'/f'trip_{trip_id}.png'))
                    sections = attachment_heading.evaluate_all('''els => els.map(el=>{
                        let result=[]; for(let i=0;el && i<3;i++,el=el.parentElement)
                            result.push({cls:el.className,text:el.innerText.slice(0,2000)});
                        return result;
                    })''')
                    item = {'id': trip_id, 'sidebar_ancestors': ancestors,
                            'attachment_headings': attachment_heading.all_text_contents(),
                            'attachment_sections': sections,
                            'images': images,
                            'download_controls': modal.get_by_role('button').all_text_contents()}
                    report['trips'].append(item)
                    print(f"Trip {trip_id}: {ancestors[2]['text'] if len(ancestors)>2 else ancestors[0]['text']}; sections={sections}; images={len(images)}", flush=True)
                modal.locator('.ant-modal-close').click()
                modal.wait_for(state='hidden')
        finally:
            (directory/'inventory.json').write_text(json.dumps(inventory, indent=2))
            print(f'Evidence: {directory}', flush=True)
            browser.close()


if __name__ == '__main__':
    main()
