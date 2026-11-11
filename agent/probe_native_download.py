"""Source-only native-download diagnostics; no bank requests or Save."""
import json
import tempfile
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright
import pymupdf as pdf
from common import run_dir
from hybrid_verify_test import install_verify_guards,login_verify,settled_search
from collections import Counter
from prepare_transfer_test import native_attachment_download

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('file_no')
parser.add_argument('applicant')
parser.add_argument('--office-trip',required=True)
args=parser.parse_args()
FILE=args.file_no
NAME=args.applicant
TRIP=args.office_trip
directory=run_dir(FILE.split('-')[-1])/datetime.now().strftime('native_diagnostic_%Y%m%d_%H%M%S')
for child in ('downloads','shots'):
    (directory/child).mkdir(parents=True,mode=0o700)
audit={'blocked_bank_requests':0,'source_request_hosts':Counter()}
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--host-resolver-rules=MAP *.citybankplc.com ~NOTFOUND, MAP citybankplc.com ~NOTFOUND'])
    context=browser.new_context(accept_downloads=True,service_workers='block',viewport={'width':1700,'height':1100})
    install_verify_guards(context,audit)
    page=context.new_page()
    downloads=[]
    page.on('download',lambda d:downloads.append(d))
    login_verify(page)
    records=settled_search(page,FILE,FILE,NAME)
    if len(records)!=1:
        raise RuntimeError('Source is not unique')
    row=page.locator('table tr').filter(has=page.get_by_text(FILE,exact=True)).filter(has=page.get_by_text(TRIP,exact=True))
    row.locator("button:has(svg[data-icon='file-text'])").click()
    modal=page.get_by_role('dialog')
    modal.wait_for()
    button=modal.get_by_role('button',name=__import__('re').compile(r'^Download Selected'))
    callback=button.evaluate('''el=>{const key=Object.keys(el).find(k=>k.startsWith('__reactProps')); const p=key?el[key]:null;return p?.onClick?.toString()||'not found';}''')
    print('Download button callback:',callback,flush=True)
    # Read only script text through the guarded browser fetch, not APIRequestContext.
    scripts=page.locator('script[src]').evaluate_all('els=>els.map(e=>e.src)')
    for src in scripts:
        if not src.startswith('https://verify.bmapsbd.com/'):
            continue
        code=page.evaluate('async url=>(await fetch(url)).text()',src)
        slot=Path(tempfile.mkdtemp(prefix='bundle_',dir=directory/'downloads'))
        (slot/'source.js').write_text(code)
        print('Saved source bundle for static diagnosis:',slot.name,flush=True)
    try:
        native_attachment_download(page,modal,TRIP,'APPLICANT SIGN','signature.pdf',directory,
                                   records[0]['trip_ids'],NAME,FILE)
    except Exception as error:
        print('Native result:',str(error),flush=True)
    page.wait_for_timeout(15000)
    print('Total download events:',len(downloads),flush=True)
    for index,download in enumerate(downloads,1):
        slot=Path(tempfile.mkdtemp(prefix=f'event_{index}_',dir=directory/'downloads'))
        path=slot/'download.pdf'
        download.save_as(path)
        try:
            with pdf.open(path) as doc:
                print(f'Download {index}: {len(doc)} page(s), {path.stat().st_size} bytes',flush=True)
        except Exception:
            print(f'Download {index}: not readable as PDF',flush=True)
    print('UI notices:',page.locator('.ant-message-notice-content').all_text_contents(),flush=True)
    (directory/'audit.json').write_text(json.dumps(audit,indent=2))
    print('Evidence:',directory,flush=True)
    browser.close()
