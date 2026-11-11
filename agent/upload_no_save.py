#!/usr/bin/env python3
"""Live upload test: upload reviewed PDFs through UR inputs, NEVER Save.
Requires an explicit --live-upload flag. Does not replace existing reports/retry.
"""
import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, expect
from common import CITY_BASE, load_creds
from test_identity import norm
from city_status import check_mis_status
from city_navigation import find_bank_row


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--live-upload',action='store_true',required=True)
    parser.add_argument('--hold-seconds',type=int,default=30)
    args=parser.parse_args()
    path=args.manifest.resolve()
    manifest=json.loads(path.read_text())
    directory=path.parent
    if manifest.get('uploads'):
        raise RuntimeError('Manifest already contains upload attempts. Inspect the bank; do not blindly retry.')
    if not manifest.get('serial') or not manifest.get('applicant') or not manifest.get('items'):
        raise RuntimeError('Manifest has no confirmed target/items.')
    seen=set()
    for item in manifest['items']:
        doc=Path(item['path']).resolve()
        if not doc.is_relative_to(directory/'final'):
            raise RuntimeError('Upload file is outside this run\'s final directory.')
        if not item.get('visual_reviewed'):
            raise RuntimeError('A document has not been visually reviewed.')
        if doc.stat().st_size>=1_000_000 or hashlib.sha256(doc.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('PDF size/hash validation failed.')
        if item['bank_label'] in seen:
            raise RuntimeError('Duplicate destination field in manifest.')
        seen.add(item['bank_label'])
    creds=load_creds()
    blocked=[]
    allowed_input={'id':None,'used':False}
    def record():
        path.write_text(json.dumps(manifest,indent=2))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=False)
        context=browser.new_context(viewport={'width':1600,'height':1000},accept_downloads=True)
        page=context.new_page()
        try:
            page.goto(CITY_BASE,wait_until='domcontentloaded',timeout=60000)
            if any(s in page.locator('body').inner_text().lower() for s in ('access denied','request rejected','support id')):
                raise RuntimeError('Bank rejected access. Stopping.')
            page.locator("input[type='text']").first.fill(creds['city_id'])
            page.locator("input[type='password']").fill(creds['city_pass'])
            page.locator("input[type='submit'],button[type='submit']").first.click()
            page.locator('text=MY Q').first.wait_for(timeout=90000)
            print('City Bank login complete',flush=True)
            # Hard UI guard applies to the upcoming UR iframe, not the login.
            context.add_init_script('''(() => {
                document.addEventListener('click',e=>{
                    let el=e.target.closest('#btnSave');
                    if(el){e.preventDefault();e.stopImmediatePropagation();}
                },true);
                document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation();},true);
            })();''')
            page.locator('text=MY Q').first.click()
            page.locator("[role='gridcell'][columnindex='6']").first.wait_for(timeout=90000)
            row=find_bank_row(page,manifest['serial'])
            print('Authorized target located in MY Q',flush=True)
            bank_name=row.locator("[columnindex='5']").inner_text().strip()
            bank_serial=row.locator("[columnindex='6']").inner_text().strip()
            if norm(bank_name)!=norm(manifest['applicant']):
                raise RuntimeError('Bank applicant identity mismatch.')
            # Recheck the live bank status even if an earlier discovery/preparer
            # run found it pending: it may have completed in the meantime.
            manifest['bank_serial']=bank_serial
            manifest['mis_status']=check_mis_status(row)
            if manifest['mis_status']['skip']:
                manifest['status']='skipped_received_full'
                manifest['save_clicked']=False
                record()
                row.screenshot(path=str(directory/'shots'/'city_skipped_received_full.png'))
                print(f'SKIPPED {bank_serial}: green MIS Received (Full). No UR or upload.',flush=True)
                return
            row.locator("[columnindex='2'] [onclick^='ur(']").click()
            page.locator("iframe[name='pmbwidget']").wait_for()
            frame=page.frame(name='pmbwidget')
            frame.locator("input[type='file']").first.wait_for(timeout=30000)
            body=frame.locator('body').inner_text()
            if bank_serial not in body or manifest['applicant'] not in body:
                raise RuntimeError('UR identity does not match bank/manifest.')
            manifest['bank_serial']=bank_serial
            # From here, only the exact intended file's single upload POST may
            # leave the browser. Save/delete/update and unexpected writes abort.
            def guard(route):
                request=route.request
                if request.method in ('GET','HEAD','OPTIONS'):
                    return route.continue_()
                parsed=urlparse(request.url)
                expected=allowed_input['id']
                payload=request.post_data_buffer or b''
                marker=(f'name="agent_report"\r\n\r\n{expected}\r\n').encode() if expected else b''
                valid=(request.method=='POST' and parsed.hostname==urlparse(CITY_BASE).hostname
                       and parsed.path=='/cpv-agency/report_upload' and expected
                       and not allowed_input['used'] and marker in payload)
                if valid:
                    allowed_input['used']=True
                    return route.continue_()
                blocked.append({'method':request.method,'path':parsed.path})
                route.abort('blockedbyclient')
            context.route('**/*',guard)
            save=frame.locator('#btnSave')
            save.evaluate("el=>{el.style.pointerEvents='none';el.style.opacity='0.45';el.setAttribute('aria-disabled','true');el.title='Disabled: upload test; do not Save';}")
            destinations=[]
            for item in manifest['items']:
                inputs=[]
                for inp in frame.locator("input[type='file']").all():
                    label=inp.evaluate("el=>el.closest('tr').cells[0].innerText.trim()")
                    if label==item['bank_label']:
                        inputs.append(inp)
                if len(inputs)!=1:
                    raise RuntimeError(f"Destination label is not unique: {item['bank_label']}")
                inp=inputs[0]
                state=inp.evaluate('''el=>{
                    let td=el.closest('td'),row=el.closest('tr');
                    return {id:el.id,
                        existingValues:[...row.querySelectorAll('input[id^="agent_file_url_"]')].map(e=>e.value).filter(Boolean),
                        visibleReportLinks:[...td.querySelectorAll('a[href]')].filter(a=>a.getClientRects().length).length};
                }''')
                # DOC column links are the bank's source/request documents, not
                # uploaded reports. Inspect only the Report cell and report URL.
                if state['existingValues'] or state['visibleReportLinks']:
                    raise RuntimeError(f"Existing report in '{item['bank_label']}' — replacement not authorized.")
                destinations.append((item,inp,state['id']))
            page.screenshot(path=str(directory/'shots'/'city_before_upload.png'),full_page=True)
            manifest['status']='uploading_no_save'
            manifest.pop('error',None)
            record()
            for item,inp,input_id in destinations:
                entry={'category':item['category'],'label':item['bank_label'],
                       'filename':Path(item['path']).name,'bytes':item['bytes'],
                       'status':'attempt_started_no_retry'}
                manifest['uploads'].append(entry)
                record()
                allowed_input.update(id=input_id,used=False)
                with page.expect_response(lambda r: urlparse(r.url).path=='/cpv-agency/report_upload'
                                          and r.request.method=='POST',timeout=60000) as event:
                    inp.set_input_files(item['path'])
                response=event.value
                allowed_input['id']=None
                if response.status!=200:
                    raise RuntimeError(f'Upload returned HTTP {response.status}; inspect bank before retry.')
                data=response.json()
                entry['http_status']=response.status
                entry['server_status']=data.get('status')
                if str(data.get('status'))!='1':
                    entry['status']='server_rejected'
                    record()
                    raise RuntimeError('Bank rejected upload. No retry.')
                link=frame.locator(f'[id="file_spn_{input_id}"]')
                link.wait_for(state='visible',timeout=15000)
                # The green/file icon must link to the server-returned file.
                server_url=data.get('file_data',{}).get('CPV_REPORT_FILE_URL')
                href=link.get_attribute('href')
                if not server_url or href!=server_url:
                    raise RuntimeError('Upload response and visible report link disagree.')
                entry['status']='upload_accepted_visible_no_save'
                entry['server_file_path']=urlparse(server_url).path
                record()
                # Independently retrieve the uploaded PDF, compare bytes, retain
                # it in its own new directory. This is GET only, never Save.
                check=context.request.get(urljoin(CITY_BASE,href),timeout=60000)
                if check.ok and hashlib.sha256(check.body()).hexdigest()==item['sha256']:
                    slot=Path(tempfile.mkdtemp(prefix=f"server_check_{item['category']}_",dir=directory/'downloads'))
                    (slot/Path(item['path']).name).write_bytes(check.body())
                    entry['status']='upload_accepted_visible_hash_verified_no_save'
                    entry['server_content_hash_matches']=True
                else:
                    entry['server_content_hash_matches']=False
                    entry['server_get_status']=check.status
                record()
                print(f"UPLOADED: {item['bank_label']} | {item['bytes']} bytes | {entry['status']}",flush=True)
            manifest['status']='uploads_complete_save_not_clicked'
            manifest['save_clicked']=False
            manifest['blocked_requests']=blocked
            record()
            page.screenshot(path=str(directory/'shots'/'city_uploaded_NO_SAVE.png'),full_page=True)
            print('COMPLETE: all file uploads accepted. SAVE NOT CLICKED; no final submission.',flush=True)
            print(f'Evidence: {directory}',flush=True)
            page.wait_for_timeout(args.hold_seconds*1000)
        except Exception as error:
            manifest['status']='blocked_inspect_before_retry'
            manifest['error']=str(error)
            manifest['blocked_requests']=blocked
            record()
            try:
                page.screenshot(path=str(directory/'shots'/'city_stopped_NO_SAVE.png'),full_page=True,
                                mask=page.locator("input[type='password']").all())
            except Exception:
                pass
            raise
        finally:
            browser.close()


if __name__=='__main__':
    main()
