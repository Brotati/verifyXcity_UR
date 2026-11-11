#!/usr/bin/env python3
"""Live Verify inspection/downloads + an entirely intercepted local bank simulation.
Never calls City Bank login, discovery, or upload workflows. No Save on Verify.
"""
import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect
from common import VERIFY_BASE, CITY_BASE, run_dir
from test_identity import norm, verify_search


def bank_host(host):
    host = (host or '').lower().rstrip('.')
    configured = (urlparse(CITY_BASE).hostname or '').lower()
    return host == configured or host == 'citybankplc.com' or host.endswith('.citybankplc.com')


def install_verify_guards(context, audit):
    def route(request_route):
        request = request_route.request
        host = urlparse(request.url).hostname or ''
        if bank_host(host):
            audit['blocked_bank_requests'] += 1
            request_route.abort('blockedbyclient')
            return
        audit['source_request_hosts'][host] += 1
        request_route.continue_()
    context.route('**/*', route)
    context.add_init_script('''document.addEventListener('click',e=>{
        const el=e.target.closest('button,#btnSave');
        if(el && (el.id==='btnSave' || el.textContent.trim()==='Save')){
            e.preventDefault();e.stopImmediatePropagation();
        }
    },true);''')


def login_verify(page):
    email, password = os.environ.get('VERIFY_EMAIL'), os.environ.get('VERIFY_PASS')
    if not email or not password:
        raise RuntimeError('Set VERIFY_EMAIL and VERIFY_PASS privately in root .env/process variables.')
    page.goto(VERIFY_BASE+'/login', wait_until='domcontentloaded', timeout=60000)
    page.get_by_role('button', name='Login', exact=True).wait_for()
    page.wait_for_timeout(2000)
    page.locator("input[type='text']").first.press_sequentially(email, delay=30)
    page.locator("input[type='password']").fill(password)
    page.locator("button[type='submit']").click()
    page.wait_for_url('**/dashboard', wait_until='domcontentloaded', timeout=60000)
    page.goto(VERIFY_BASE+'/reports', wait_until='domcontentloaded', timeout=60000)
    page.locator("input[placeholder*='Search files' i]").wait_for()
    page.wait_for_timeout(2000)


def settled_search(page, query, file_no, applicant):
    verify_search(page, query)
    # Observe the existing request/table refresh without resubmitting searches.
    for _ in range(60):
        rows = []
        for row in page.locator('table tr').all():
            cells = row.locator(':scope > td')
            if cells.count() < 10:
                continue
            if cells.nth(2).inner_text().strip() == file_no and norm(cells.nth(1).inner_text()) == norm(applicant):
                rows.append({'file': file_no, 'applicant': cells.nth(1).inner_text().strip(),
                             'organization': cells.nth(5).inner_text().strip(),
                             'status': cells.nth(3).inner_text().strip(),
                             'trip_ids': re.findall(r'\d+', cells.nth(6).inner_text()),
                             'start_date': cells.nth(7).inner_text().strip(),
                             'end_date': cells.nth(9).inner_text().strip()})
        if rows and page.locator('.ant-spin-spinning').count() == 0:
            return rows
        page.wait_for_timeout(500)
    return []


def inventory(page, file_no, applicant, directory):
    searches = {}
    for query in (file_no, applicant):
        records = settled_search(page, query, file_no, applicant)
        searches[query] = records
        print(f'SOURCE SEARCH {query!r}: {len(records)} exact name/file match(es)', flush=True)
    records = searches[applicant]
    if not records:
        raise RuntimeError('No exact Verify file/applicant match; no downloads attempted.')
    reports = []
    for record in records:
        if 'city bank' not in record['organization'].casefold():
            raise RuntimeError('Matching source file is not in the expected City Bank organization.')
        if not record['trip_ids']:
            raise RuntimeError('Matching report has no listed trips.')
        row = page.locator('table tr').filter(has=page.get_by_text(file_no, exact=True)).filter(
            has=page.get_by_text(record['trip_ids'][0], exact=True))
        expect(row).to_have_count(1)
        row.screenshot(path=str(directory/'shots'/f"source_row_{record['trip_ids'][0]}.png"))
        row.locator("button:has(svg[data-icon='file-text'])").click()
        modal = page.get_by_role('dialog')
        modal.wait_for()
        expect(modal).to_contain_text(file_no)
        page.wait_for_timeout(1500)
        labels = modal.get_by_text(re.compile(r'^Trip \d+$')).all_text_contents()
        visible_ids = [re.search(r'\d+', text).group() for text in labels]
        record['trips'] = []
        record['not_in_modal'] = sorted(set(record['trip_ids']) - set(visible_ids))
        reports.append(record)
        for trip_id in visible_ids:
            trip = modal.get_by_text(f'Trip {trip_id}', exact=True)
            sidebar = trip.locator('xpath=../..').inner_text().strip()
            trip.click()
            expect(modal).to_contain_text(f'Trip #{trip_id}')
            page.wait_for_timeout(1500)
            cards = []
            for image in modal.locator('img').all():
                card = image.locator('xpath=../..')
                if card.locator("input[type='checkbox']").count() == 1:
                    cards.append(card.inner_text().strip())
            attachment_headings = modal.get_by_text(re.compile(r'^Attachments\s*\(\d+\)$'))
            if attachment_headings.count():
                attachment_headings.first.scroll_into_view_if_needed()
            modal.screenshot(path=str(directory/'shots'/f'trip_{trip_id}.png'))
            item = {'id': trip_id, 'concern_type': sidebar,
                    'attachments': dict(Counter(cards)),
                    'attachment_headings': attachment_headings.all_text_contents()}
            record['trips'].append(item)
            print(f"TRIP {trip_id}: {sidebar.replace(chr(10),' | ')}; attachments={item['attachments']}", flush=True)
        modal.locator('.ant-modal-close').click()
        modal.wait_for(state='hidden')
    return {'searches': searches, 'reports': reports}


def prepare_documents(page, result, directory):
    from prepare_transfer_test import native_attachment_download, finalize, render_previews
    reports=result['reports']
    if len(reports)!=1:
        raise RuntimeError('Multiple source reports: explicit report selection is required before downloads.')
    report=reports[0]
    file_no=result['file']
    row=page.locator('table tr').filter(has=page.get_by_text(file_no,exact=True)).filter(
        has=page.get_by_text(report['trip_ids'][0],exact=True))
    expect(row).to_have_count(1)
    row.locator("button:has(svg[data-icon='file-text'])").click()
    modal=page.get_by_role('dialog')
    modal.wait_for()
    expect(modal).to_contain_text(file_no)
    all_ids=[trip['id'] for trip in report['trips']]
    manifest={'mode':'live_verify_local_mock_bank','serial':file_no.split('-')[-1],
              'applicant':result['applicant'],'verify_file':file_no,'items':[],
              'uploads':[],'save_clicked':False,'status':'preparing',
              'bank_labels_are_simulated':True,'blockers':[]}
    source_plan=[('office','APPLICANT OFFICE','Image of Office',False),
                 ('residence','APPLICANT RESIDENCE','Residence Address',False),
                 ('signature','APPLICANT SIGN','Office Address/Passport Size Lab Print Photo/Signature',False),
                 ('bank_statement','BANK STATEMENT','Bank Statement',False),
                 ('loi','LOI','Letter of Introduction',True)]
    namepart=re.sub(r'[^A-Za-z0-9]+','_',result['applicant']).strip('_')
    for category,label,bank_label,attachment_only in source_plan:
        candidates=[trip for trip in report['trips'] if label in trip['attachments']
                    and norm(trip['concern_type']).startswith('applicant s ')]
        if not candidates:
            continue
        if len(candidates)!=1 or (label in ('LOI','APPLICANT SIGN') and candidates[0]['attachments'][label]!=1):
            manifest['blockers'].append({'category':category,'reason':'Multiple candidate trips or attachments; operator selection needed.',
                                         'candidates':[{ 'trip':t['id'],'count':t['attachments'][label]} for t in candidates]})
            print(f'SKIPPED ambiguous {category}: operator selection needed',flush=True)
            continue
        trip=candidates[0]
        filename=f"{file_no}_{namepart}_{category}_trip{trip['id']}.pdf"
        try:
            raw,count=native_attachment_download(page,modal,trip['id'],label,filename,directory,all_ids,
                                                result['applicant'],file_no,attachment_only=attachment_only)
            item=finalize(raw,directory/'final'/filename,result['applicant'] if not attachment_only else None,file_no)
            item.update(category=category,trip_id=trip['id'],attachment_label=label,attachment_count=count,
                        bank_label=bank_label,bank_label_is_simulated=True,raw=str(raw),
                        download_method='verify_download_selected')
            manifest['items'].append(item)
            render_previews(Path(item['path']),directory/'previews')
            print(f"PREPARED {category}: {item['pages']} pages, {item['bytes']} bytes",flush=True)
        except Exception as error:
            manifest['blockers'].append({'category':category,'trip':trip['id'],'reason':str(error)})
            print(f'BLOCKED {category}: {error}',flush=True)
            modal.screenshot(path=str(directory/'shots'/f'{category}_blocked.png'))
        finally:
            (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    manifest['status']='partial_preparation_awaiting_review' if manifest['blockers'] else 'prepared_awaiting_visual_review'
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file_no')
    parser.add_argument('applicant')
    parser.add_argument('--prepare',action='store_true',help='Download unambiguous native PDF groups; never contact bank.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z]+-\d+', args.file_no):
        parser.error('Provide the exact Verify file number, preserving zeros.')
    if bank_host(urlparse(VERIFY_BASE).hostname):
        parser.error('VERIFY_BASE must not point at the real bank.')
    directory = run_dir(args.file_no.split('-')[-1])/datetime.now().strftime('hybrid_%Y%m%d_%H%M%S')
    for child in ('shots','downloads','final','previews'):
        (directory/child).mkdir(parents=True, mode=0o700)
    audit = {'blocked_bank_requests': 0, 'source_request_hosts': Counter()}
    result = {'mode': 'live_verify_local_mock_bank', 'file': args.file_no,
              'applicant': args.applicant, 'save_clicked': False,
              'real_bank_access_allowed': False, 'status': 'inspecting'}
    print(f'Hybrid test directory: {directory}', flush=True)
    with sync_playwright() as p:
        blocked_host = urlparse(CITY_BASE).hostname
        rules = 'MAP *.citybankplc.com ~NOTFOUND, MAP citybankplc.com ~NOTFOUND'
        if blocked_host:
            rules += f', MAP {blocked_host} ~NOTFOUND'
        browser = p.chromium.launch(headless=True,args=['--host-resolver-rules='+rules])
        context = browser.new_context(accept_downloads=True, service_workers='block',
                                      viewport={'width':1700,'height':1100})
        install_verify_guards(context,audit)
        page = context.new_page()
        try:
            login_verify(page)
            result.update(inventory(page,args.file_no,args.applicant,directory))
            result['status']='inventory_complete_awaiting_download_plan'
            if args.prepare:
                manifest=prepare_documents(page,result,directory)
                result['preparation_manifest']=str(directory/'manifest.json')
                result['status']=manifest['status']
        except Exception as error:
            result.update(status='blocked',error=str(error))
            raise
        finally:
            result['network_audit'] = audit
            (directory/'result.json').write_text(json.dumps(result,indent=2))
            browser.close()
            print(f'Result: {directory/"result.json"}',flush=True)


if __name__ == '__main__':
    main()
