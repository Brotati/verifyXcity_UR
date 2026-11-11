#!/usr/bin/env python3
"""Prepare a single explicitly selected applicant/trip set. No bank upload or Save.
Downloads are isolated from scripts. A manifest records sources and final hashes.
"""
import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import pymupdf as pdf
from playwright.sync_api import sync_playwright, expect
from common import VERIFY_BASE, load_creds, run_dir
from test_identity import city_check, norm, verify_search
from pdf_package import compress_images

LIMIT = 1_000_000  # Strictly below decimal 1 MB as well as the portal's 1 MiB.


def save_manifest(directory, manifest):
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2))


def render_previews(path, directory):
    with pdf.open(path) as doc:
        tiles = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=pdf.Matrix(1, 1), alpha=False)
            out = directory / f'{path.stem}_page_{i+1}.png'
            pix.save(out)
            tiles.append((out, page.rect))
        sheet = pdf.open()
        rows = (len(tiles) + 2) // 3
        canvas = sheet.new_page(width=900, height=rows * 430)
        for i, (image, rect) in enumerate(tiles):
            x, y = (i % 3)*300, (i // 3)*430
            canvas.insert_text((x+8, y+15), f'Page {i+1}', fontsize=11)
            canvas.insert_image(pdf.Rect(x+5,y+20,x+295,y+425), filename=str(image), keep_proportion=True)
        canvas.get_pixmap().save(directory / f'{path.stem}_contact.png')
        sheet.close()


def finalize(raw, output, expected_name=None, expected_file=None):
    with pdf.open(raw) as original:
        if original.needs_pass or original.page_count == 0:
            raise RuntimeError('Downloaded document is empty/encrypted.')
        count = original.page_count
        text = ' '.join(p.get_text() for p in original)
        if expected_name and norm(expected_name) not in norm(text):
            raise RuntimeError('Downloaded trip report does not contain the expected applicant name.')
        if expected_file and expected_file not in text:
            raise RuntimeError('Downloaded trip report does not contain the expected file number.')
        original.ez_save(output)
    method = 'lossless'
    if output.stat().st_size >= LIMIT:
        for dpi, quality in ((160,80),(140,75),(120,70),(110,65),(100,60)):
            candidate = output.with_suffix(f'.{dpi}.pdf')
            compress_images(raw,candidate,dpi,quality)
            if candidate.stat().st_size < LIMIT:
                candidate.replace(output)
                method = f'embedded images {dpi} DPI, JPEG quality {quality}; native text retained'
                break
            candidate.unlink()
    if output.stat().st_size >= LIMIT:
        raise RuntimeError(f'{output.name}: cannot meet size limit at permitted quality settings.')
    with pdf.open(output) as result:
        if result.page_count != count:
            raise RuntimeError('Page count changed during compression.')
        if expected_name and norm(expected_name) not in norm(' '.join(p.get_text() for p in result)):
            raise RuntimeError('Report text lost during compression.')
        # Decode every page; human inspection of previews is still required.
        for page in result:
            page.get_pixmap(matrix=pdf.Matrix(0.5,0.5))
    return {'path': str(output), 'bytes': output.stat().st_size, 'pages': count,
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'compression': method,
            'visual_reviewed': False}


def sidebar_box(modal, trip_id):
    label = modal.get_by_text(f'Trip {trip_id}', exact=True)
    return label.locator("xpath=ancestor::*[.//input[@type='checkbox']][1]").locator("input[type='checkbox']").first


def open_trip(modal, trip_id):
    modal.get_by_text(f'Trip {trip_id}', exact=True).click()
    expect(modal).to_contain_text(f'Trip #{trip_id}')
    modal.page.wait_for_timeout(1500)


def attachment_cards(modal):
    return [img.locator('xpath=../..') for img in modal.locator('img').all()
            if img.locator('xpath=../..').locator("input[type='checkbox']").count() == 1]


def native_attachment_download(page, modal, trip_id, attachment_label, file_name,
                               directory, all_ids, expected_name, expected_file,
                               attachment_only=False):
    """Use the operator's native Verify sequence for every attachment category.

    Select attachments, then the left trip checkbox, then Download Selected (1).
    Never fetch raw image URLs or reconstruct Verify's generated page content.
    For standalone LOI, retain the original download and extract its generated
    attachment pages without changing their contents or layout.
    """
    open_trip(modal, trip_id)
    for current in all_ids:
        sidebar_box(modal, current).set_checked(False)

    cards = attachment_cards(modal)
    selected = sum(card.inner_text().strip() == attachment_label for card in cards)
    if selected == 0:
        raise RuntimeError(f'Trip {trip_id}: no {attachment_label} attachments.')
    if attachment_label in ('APPLICANT SIGN', 'LOI') and selected != 1:
        raise RuntimeError(f'Expected one {attachment_label} attachment; found {selected}.')
    for card in cards:
        card.locator("input[type='checkbox']").set_checked(
            card.inner_text().strip() == attachment_label)

    # The same order applies to business images, residence, signature and LOI.
    sidebar_box(modal, trip_id).set_checked(True)
    for current in all_ids:
        expect(sidebar_box(modal, current)).to_be_checked(checked=current == trip_id)
    current_cards = attachment_cards(modal)
    if sum(card.inner_text().strip() == attachment_label for card in current_cards) != selected:
        raise RuntimeError('Attachment list changed after selecting the trip; stopping.')
    for card in current_cards:
        expect(card.locator("input[type='checkbox']")).to_be_checked(
            checked=card.inner_text().strip() == attachment_label)
    button = modal.get_by_role('button', name=re.compile(r'^Download Selected'))
    expect(button).to_contain_text('(1)')
    expect(button).to_be_enabled()
    category = re.sub(r'[^a-z0-9]+', '_', attachment_label.lower()).strip('_')
    modal.screenshot(path=str(directory/'shots'/f'{category}_selection_trip{trip_id}.png'))

    slot = Path(tempfile.mkdtemp(prefix=f'{category}_trip_{trip_id}_', dir=directory/'downloads'))
    generated_path = slot/('verify_generated.pdf' if attachment_only else file_name)
    with page.expect_download(timeout=120000) as event:
        button.click()
    download = event.value
    if download.failure():
        raise RuntimeError(f'Verify-generated {attachment_label} download failed; no automatic retry.')
    download.save_as(generated_path)
    with pdf.open(generated_path) as generated:
        if not generated.is_pdf or generated.needs_pass or generated.page_count < 2:
            raise RuntimeError('Expected Verify report plus attachment pages; refusing raw/report-only output.')
        page_texts = [page.get_text() for page in generated]
        report_text = ' '.join(page_texts)
        if norm(expected_name) not in norm(report_text) or expected_file not in report_text:
            raise RuntimeError('Verify-generated PDF does not match the requested applicant/file.')
        matching_pages = [i for i, text in enumerate(page_texts) if i > 0
                          and norm(attachment_label) in norm(text) and trip_id in text]
        if not matching_pages:
            raise RuntimeError(f'Generated PDF lacks the expected {attachment_label} trip attachment header.')
        raw = generated_path
        if attachment_only:
            # Only this category/trip was selected. Preserve its generated pages
            # (including any overlays), excluding the preceding report sheet(s).
            raw = slot/file_name
            with pdf.open() as standalone_pdf:
                standalone_pdf.insert_pdf(generated, from_page=min(matching_pages))
                standalone_pdf.ez_save(raw)
    print(f'Downloaded Verify-generated {attachment_label}: {selected} selected attachment(s); visual review required', flush=True)
    return raw, selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial')
    parser.add_argument('applicant')
    parser.add_argument('--house-trip', required=True)
    parser.add_argument('--office-trip', required=True)
    args = parser.parse_args()
    if not all(re.fullmatch(r'\d+', n) for n in (args.serial,args.house_trip,args.office_trip)):
        parser.error('Identifiers must be digits, preserving leading zeros.')
    directory = run_dir(args.serial)/datetime.now().strftime('transfer_%Y%m%d_%H%M%S')
    for child in ('downloads','final','previews','shots'):
        (directory/child).mkdir(parents=True, mode=0o700)
    manifest = {'serial':args.serial,'applicant':args.applicant,'verify_file':None,
                'items':[],'uploads':[],'save_clicked':False,'status':'preparing'}
    creds = load_creds()
    print(f'Run directory: {directory}', flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(accept_downloads=True, viewport={'width':1700,'height':1100}).new_page()
        try:
            # Even when preparation is invoked directly, do not search/download
            # Verify documents for an already-completed bank file.
            bank = city_check(browser,creds,args.serial,args.applicant,directory)
            manifest['bank_serial'] = bank['serial']
            manifest['mis_status'] = bank['mis_status']
            if bank['skipped']:
                manifest['status'] = 'skipped_received_full'
                print('Preparation skipped: green MIS Received (Full). No Verify work.',flush=True)
                return
            page.goto(VERIFY_BASE+'/login',wait_until='domcontentloaded')
            page.get_by_role('button',name='Login',exact=True).wait_for()
            page.wait_for_timeout(2000)
            page.locator("input[type='text']").first.press_sequentially(creds['verify_email'],delay=35)
            page.locator("input[type='password']").fill(creds['verify_pass'])
            page.locator("button[type='submit']").click()
            page.wait_for_url('**/dashboard',wait_until='domcontentloaded',timeout=30000)
            page.goto(VERIFY_BASE+'/reports',wait_until='domcontentloaded')
            page.locator("input[placeholder*='Search files' i]").wait_for()
            page.wait_for_timeout(2000)
            expected_ids = {args.house_trip,args.office_trip}
            matches = [r for r in verify_search(page,args.applicant)
                       if norm(r['applicant']) == norm(args.applicant)
                       and r['file'].split('-')[-1] == args.serial
                       and 'city bank' in r['organization'].lower()
                       and expected_ids.issubset(set(r['trip_ids']))]
            if len(matches) != 1:
                # Wait for a potentially slow table refresh, without resubmitting
                # the search or touching any report data.
                page.wait_for_timeout(6000)
                existing_rows=[]
                for r in page.locator('table tr').all():
                    cells=r.locator(':scope > td')
                    if cells.count()>6 and norm(cells.nth(1).inner_text())==norm(args.applicant):
                        existing_rows.append({'file':cells.nth(2).inner_text().strip(),
                                              'organization':cells.nth(5).inner_text().strip(),
                                              'ids':re.findall(r'\d+',cells.nth(6).inner_text())})
                print(f'Visible exact-name candidates after wait: {existing_rows}',flush=True)
                for r in existing_rows:
                    if (r['file'].split('-')[-1]==args.serial and 'city bank' in r['organization'].lower()
                            and expected_ids.issubset(set(r['ids']))):
                        matches.append({'file':r['file'],'start_date':'confirmed by explicit trip identifiers'})
                if len(matches)!=1:
                    raise RuntimeError('Selected applicant/file/trip set is not unique or results did not load.')
            match=matches[0]
            manifest['verify_file']=match['file']
            manifest['report_start']=match['start_date']
            row=page.locator('table tr').filter(has=page.get_by_text(match['file'],exact=True)).filter(
                has=page.get_by_text(args.house_trip,exact=True))
            expect(row).to_have_count(1)
            row.locator("button:has(svg[data-icon='file-text'])").click()
            modal=page.get_by_role('dialog')
            modal.wait_for()
            expect(modal).to_contain_text(match['file'])
            page.wait_for_timeout(1500)
            all_ids=[re.search(r'\d+',s).group() for s in modal.get_by_text(re.compile(r'^Trip \d+$')).all_text_contents()]
            namepart = re.sub(r'[^A-Za-z0-9]+','_',args.applicant).strip('_')
            # Every category uses the same native Verify download sequence.
            # LOI alone excludes the report pages to remain a standalone document.
            specs=[('business',args.office_trip,'APPLICANT OFFICE','Business Address with Photo',False),
                   ('residence',args.house_trip,'APPLICANT RESIDENCE','Residence Address',False),
                   ('signature',args.office_trip,'APPLICANT SIGN','Office Address/Passport Size Lab Print Photo/Signature',False),
                   ('loi',args.office_trip,'LOI','Self Income Declaration (if any)',True)]
            for category,trip_id,label,bank_label,attachment_only in specs:
                filename=f'{args.serial}_{namepart}_{category}_trip{trip_id}.pdf'
                raw,count=native_attachment_download(
                    page,modal,trip_id,label,filename,directory,all_ids,
                    args.applicant,match['file'],attachment_only=attachment_only)
                item=finalize(raw,directory/'final'/filename,
                              args.applicant if not attachment_only else None,
                              match['file'])
                visual_checks=['all selected attachments present',
                               'Verify page layout and generated content preserved',
                               'all pages complete, correctly oriented and readable']
                if category=='signature':
                    visual_checks.extend(['applicant photo present','signature and stamp present'])
                item.update(category=category,trip_id=trip_id,attachment_label=label,
                            attachment_count=count,bank_label=bank_label,raw=str(raw),
                            download_method='verify_download_selected',
                            attachment_only=attachment_only,
                            original_generated_pdf=str(raw.parent/'verify_generated.pdf' if attachment_only else raw),
                            required_visual_checks=visual_checks)
                manifest['items'].append(item)
                save_manifest(directory,manifest)
                render_previews(Path(item['path']),directory/'previews')
                print(f"PREPARED {category}: {item['bytes']} bytes, {item['pages']} pages",flush=True)
            manifest['status']='prepared_awaiting_visual_review'
        except Exception as error:
            manifest['status']='blocked'
            manifest['error']=str(error)
            raise
        finally:
            save_manifest(directory,manifest)
            browser.close()
            print(f'Manifest: {directory/"manifest.json"}',flush=True)


if __name__=='__main__':
    main()
