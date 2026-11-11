#!/usr/bin/env python3
"""Offline integration checks of the actual upload_no_save.main workflow.

All browser requests are intercepted. APIRequestContext.get is replaced by an
in-memory reader. Real .env URLs/credentials are not edited or sent anywhere.
Uses labelled synthetic PDFs only, never failed/partial customer downloads.
"""
import hashlib
import base64
import html
import json
import sys
from contextlib import contextmanager
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import pymupdf as pdf
from playwright.sync_api import sync_playwright
from common import RUNS_DIR
import upload_no_save as uploader

ORIGIN='http://mock-bank.test'
SERIAL='0000001'
APPLICANT='Offline Test Applicant'
BANK_SERIAL='MOCK-2026-11-'+SERIAL
LABELS=['Business Address with Photo','Residence Address',
        'Office Address/Passport Size Lab Print Photo/Signature','Self Income Declaration (if any)']


def fixture_root():
    return '''<!doctype html><meta charset="utf-8"><title>LOCAL MOCK ONLY</title>
    <h1>LOCAL MOCK — NOT CITY BANK</h1><form action="/cpv-agency">
    <input type="text" name="mock_user"><input type="password" name="mock_password">
    <button type="submit">Login</button></form>'''


def fixture_queue(completed):
    status='<span style="color:rgb(0,128,0)">Received (Full)</span>' if completed else ''
    titles=['UL','DLD','UR','UCR','Correction Required','Applicant Name','File Serial No',
            'DRR','RRN','Zone','Request Type','MIS Report Receive Status']
    headers=''.join(f'<div role="columnheader" columnindex="{i}">{name}</div>' for i,name in enumerate(titles))
    values=['','','<div onclick="ur()">UR</div>','','No',APPLICANT,BANK_SERIAL,'','','','','']
    values[-1]=status
    cells=''.join(f'<div role="gridcell" columnindex="{i}">{value}</div>' for i,value in enumerate(values))
    return f'''<!doctype html><meta charset="utf-8"><h1>LOCAL MOCK — NOT CITY BANK</h1>
    <button>MY Q</button><div class="jqx-grid">{headers}<div role="row">{cells}</div></div>
    <script>function ur(){{let f=document.createElement('iframe');f.name='pmbwidget';
    f.src='/cpv-agency/ur/';f.style='width:100%;height:700px';document.body.append(f);}}</script>'''


def fixture_ur(existing):
    rows=[]
    for index,label in enumerate(LABELS,1):
        input_id=f'report_upload_0_{index}'
        old='<a href="/files/existing.pdf">Existing report</a>' if existing and index==1 else ''
        rows.append(f'''<tr><td>{html.escape(label)}</td><td>{old}
        <input type="file" id="{input_id}" onchange="uploadFile(this)">
        <input type="hidden" id="agent_file_url_0_{index}" value=""></td></tr>''')
    return f'''<!doctype html><meta charset="utf-8"><h1>LOCAL MOCK — NOT CITY BANK</h1>
    <h2>{BANK_SERIAL}</h2><p>{APPLICANT}</p><table>{''.join(rows)}</table>
    <div id="btnSave" onclick="fetch('/save',{{method:'POST'}})">Save</div>
    <script>async function uploadFile(input){{
        const data=new FormData();data.append('file',input.files[0]);data.append('agent_report',input.id);
        // Fixture-only copy: Chromium interception may omit binary file bytes.
        // This is derived from the same selected File and never used in production.
        const bytes=new Uint8Array(await input.files[0].arrayBuffer());let binary='';
        for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        data.append('mock_file_base64',btoa(binary));
        const response=await fetch('/cpv-agency/report_upload',{{method:'POST',body:data}});
        const result=await response.json();if(result.status!==1)return;
        const link=document.createElement('a');link.id='file_spn_'+input.id;
        link.href=result.file_data.CPV_REPORT_FILE_URL;link.textContent='Uploaded report';
        input.after(link);input.style.display='none';
    }}</script>'''


class FallbackRoute:
    """Let the production guard pass approved traffic to the offline fixture.

    Production route.continue_ otherwise bypasses lower-priority routes and
    would try the network. All remaining requests hit the fixture, never I/O.
    """
    def __init__(self,route):self.route=route
    @property
    def request(self):return self.route.request
    def continue_(self,**kwargs):return self.route.fallback(**kwargs)
    def abort(self,*args,**kwargs):return self.route.abort(*args,**kwargs)


class FakeGetResponse:
    def __init__(self,body,status):self._body=body;self.status=status;self.ok=status==200
    def body(self):return self._body


def isolated_playwright(state,completed=False,existing=False,reject=False):
    @contextmanager
    def manager():
        with sync_playwright() as p:
            launch=p.chromium.launch
            def isolated_launch(**kwargs):
                # No DNS/network fallback is permitted, even if a fixture fails.
                browser=launch(headless=True,args=['--host-resolver-rules=MAP * ~NOTFOUND','--disable-background-networking'])
                original_new_context=browser.new_context
                def new_context(**options):
                    options['service_workers']='block'
                    context=original_new_context(**options)
                    original_route=context.route
                    def fixture(route):
                        request=route.request
                        parsed=urlparse(request.url)
                        if parsed.scheme+'://'+parsed.netloc!=ORIGIN:
                            state['external_attempts'].append(parsed.hostname)
                            return route.abort('blockedbyclient')
                        state['requests'].append({'method':request.method,'path':parsed.path})
                        if request.method=='GET':
                            pages={'/':fixture_root(),'/cpv-agency':fixture_queue(completed),
                                   '/cpv-agency/ur/':fixture_ur(existing)}
                            if parsed.path in pages:
                                if parsed.path=='/cpv-agency/ur/':state['ur_opened']+=1
                                return route.fulfill(status=200,content_type='text/html',body=pages[parsed.path])
                            if parsed.path in state['files']:
                                return route.fulfill(status=200,content_type='application/pdf',body=state['files'][parsed.path])
                            return route.fulfill(status=404,body='Not found in local fixture')
                        if request.method=='POST' and parsed.path=='/cpv-agency/report_upload':
                            raw=request.post_data_buffer or b''
                            message=BytesParser(policy=policy.default).parsebytes(
                                ('Content-Type: '+request.headers['content-type']+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
                            parts={part.get_param('name',header='content-disposition'):part.get_payload(decode=True)
                                   for part in message.iter_parts()}
                            input_id=parts['agent_report'].decode()
                            selected_file=base64.b64decode(parts['mock_file_base64'],validate=True)
                            state['uploads'].append({'input_id':input_id,'sha256':hashlib.sha256(selected_file).hexdigest()})
                            if reject:
                                return route.fulfill(status=200,json={'status':0})
                            file_path='/files/'+input_id+'.pdf'
                            state['files'][file_path]=selected_file
                            return route.fulfill(status=200,json={'status':1,'file_data':{'CPV_REPORT_FILE_URL':ORIGIN+file_path}})
                        return route.fulfill(status=400,body='Unsupported local fixture action')
                    original_route('**/*',fixture)
                    def register(pattern,handler,**kwargs):
                        original_route(pattern,lambda route:handler(FallbackRoute(route)),**kwargs)
                    context.route=register
                    def offline_get(url,**kwargs):
                        parsed=urlparse(url)
                        if parsed.scheme+'://'+parsed.netloc!=ORIGIN:
                            state['external_attempts'].append(parsed.hostname)
                            raise RuntimeError('External APIRequestContext request blocked in offline fixture')
                        body=state['files'].get(parsed.path)
                        return FakeGetResponse(body or b'',200 if body is not None else 404)
                    context.request.get=offline_get
                    return context
                browser.new_context=new_context
                return browser
            p.chromium.launch=isolated_launch
            yield p
    return manager


def make_manifest(directory):
    (directory/'final').mkdir(parents=True,mode=0o700)
    (directory/'shots').mkdir()
    (directory/'downloads').mkdir()
    manifest={'mode':'LOCAL_SYNTHETIC_OFFLINE_TEST','serial':SERIAL,'applicant':APPLICANT,
              'items':[],'uploads':[],'save_clicked':False,'status':'synthetic_fixture_ready'}
    for index,label in enumerate(LABELS,1):
        path=directory/'final'/f'synthetic_{index}.pdf'
        with pdf.open() as doc:
            page=doc.new_page();page.insert_text((40,60),'SYNTHETIC TEST ONLY - NOT A CUSTOMER DOCUMENT')
            page.insert_text((40,90),label);doc.save(path)
        manifest['items'].append({'path':str(path),'bank_label':label,'category':f'fixture_{index}',
                                  'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'visual_reviewed':True})
    path=directory/'manifest.json';path.write_text(json.dumps(manifest,indent=2))
    return path


def main():
    directory=RUNS_DIR/'offline_mock_tests'/datetime.now().strftime('%Y%m%d_%H%M%S')
    results=[]
    cases=[('success',{},'uploads_complete_save_not_clicked',4),
           ('received_full',{'completed':True},'skipped_received_full',0),
           ('existing_document',{'existing':True},'blocked_inspect_before_retry',0),
           ('server_rejected',{'reject':True},'blocked_inspect_before_retry',1),
           ('oversized',{'oversized':True},'synthetic_fixture_ready',0),
           ('hash_changed',{'hash_changed':True},'synthetic_fixture_ready',0),
           ('not_reviewed',{'not_reviewed':True},'synthetic_fixture_ready',0)]
    for name,options,expected_status,expected_uploads in cases:
        options=dict(options)
        path=make_manifest(directory/name)
        inputs=json.loads(path.read_text())
        first=inputs['items'][0]
        if options.pop('oversized',False):
            selected=Path(first['path'])
            selected.write_bytes(selected.read_bytes().ljust(1_000_000,b' '))
            first.update(bytes=selected.stat().st_size,sha256=hashlib.sha256(selected.read_bytes()).hexdigest())
        if options.pop('hash_changed',False):
            with Path(first['path']).open('ab') as output:output.write(b'\n')
        if options.pop('not_reviewed',False):
            first['visual_reviewed']=False
        path.write_text(json.dumps(inputs,indent=2))
        state={'requests':[],'external_attempts':[],'files':{},'uploads':[],'ur_opened':0}
        error=None
        fake_creds={'city_id':'mock-only','city_pass':'mock-only'}
        with patch.object(uploader,'CITY_BASE',ORIGIN),patch.object(uploader,'load_creds',return_value=fake_creds),\
             patch.object(uploader,'sync_playwright',isolated_playwright(state,**options)),\
             patch.object(sys,'argv',['upload_no_save.py',str(path),'--live-upload','--hold-seconds','0']):
            try:
                uploader.main()
            except Exception as exc:
                error=str(exc)
        result=json.loads(path.read_text())
        assert result['status']==expected_status,(name,result['status'],error)
        assert len(state['uploads'])==expected_uploads,(name,'unexpected upload count')
        assert not state['external_attempts'],(name,'external network attempted')
        assert not any('/save' in item['path'] for item in state['requests']),(name,'Save was attempted')
        assert result['save_clicked'] is False
        if name=='received_full':assert state['ur_opened']==0
        if name=='success':assert all(item['server_content_hash_matches'] for item in result['uploads'])
        errors={'existing_document':'Existing report','server_rejected':'Bank rejected upload',
                'oversized':'size/hash validation failed','hash_changed':'size/hash validation failed',
                'not_reviewed':'not been visually reviewed'}
        if name in errors:assert error and errors[name] in error,(name,'unexpected failure reason',error)
        results.append({'case':name,'passed':True,'status':result['status'],'mock_uploads':len(state['uploads']),
                        'real_bank_requests':0,'save_requests':0,'expected_error':error})
        print(f'PASS {name}: mock uploads={len(state["uploads"])}; external requests=0; Save requests=0',flush=True)
    (directory/'test_results.json').write_text(json.dumps(results,indent=2))
    print(f'Offline mock results: {directory/"test_results.json"}',flush=True)


if __name__=='__main__':
    main()
