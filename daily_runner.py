#!/usr/bin/env python3
"""Supervised Verify -> City Bank DAILY RUNNER. No AI/OCR account is required.

ONE-TIME SETUP (Python 3.10+; desktop/display required):
    python -m pip install playwright PyMuPDF python-dotenv tzdata
    python -m playwright install chromium
    Put private VERIFY_EMAIL, VERIFY_PASS, CITY_ID, CITY_PASS in .env beside this file.

RUN:
    python daily_runner.py                 # Safe startup menu; Enter = inspect only
    python daily_runner.py --mode inspect
    python daily_runner.py --mode prepare --limit 1
    python daily_runner.py --mode run --limit 1

Today means City Bank REQUEST DATE in Asia/Dhaka. Preparation SAVES attachment
selections in Verify. Run mode additionally uploads approved PDFs immediately.
CITY BANK SAVE/FINAL SUBMISSION IS ALWAYS FORBIDDEN. Unclear mappings are chosen
by the operator; PDF visual review is mandatory. Never blindly retry uploads.

Self-contained: does not import agent/ or any other project Python file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import io
import math
import shutil
import subprocess
import unicodedata
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, unquote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = "1.0.0-supervised"
ROOT = Path(__file__).resolve().parent
LIMIT = 1_000_000
TERMINAL_STATES = {"UPLOADED_NO_BANK_SAVE", "UPLOADED_UNVERIFIED_NO_BANK_SAVE", "SKIPPED_RECEIVED_FULL"}
pdf: Any = None
expect: Any = None


class StopDay(RuntimeError):
    """Session, date-scope, or unsafe-write failure: stop the entire run."""


class HoldFile(RuntimeError):
    """Needs human attention: no more writes for this file."""


class QuitDay(Exception):
    pass


def norm(value: Any) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(value or "").casefold()).split())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".checkpoint_", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)  # Only our own temporary checkpoint, never source evidence.


def prompt(message: str) -> str:
    try:
        answer = input(message + " ").strip()
    except (EOFError, KeyboardInterrupt):
        raise QuitDay("Operator stopped the run; inspect checkpoints before resuming.") from None
    if answer.casefold() in {"q", "quit"}:
        raise QuitDay("Operator stopped the run.")
    return answer


def confirm(message: str) -> bool:
    return prompt(message + " [type YES to confirm; Enter = no; q = stop]") == "YES"


def parse_date(text: str) -> date:
    """Parse bank English dates without relying on the machine locale."""
    value = html.unescape(text or "").strip()
    match = re.search(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", value)
    if match:
        return date(*map(int, match.groups()))
    match = re.search(r"\b(\d{1,2})[- /]([A-Za-z]{3,9})[- /](\d{2,4})\b", value)
    if match:
        day, month, year = match.groups()
        months = {name: i for i, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
        number = months.get(month[:3].casefold())
        year_number = int(year) + (2000 if len(year) == 2 else 0)
        if number:
            return date(year_number, number, int(day))
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(20\d{2})", value)
    if match:
        day, month, year = map(int, match.groups())
        return date(year, month, day)
    raise HoldFile("Cannot safely read the bank request date.")


def today_dhaka() -> date:
    try:
        return datetime.now(ZoneInfo("Asia/Dhaka")).date()
    except ZoneInfoNotFoundError:
        raise StopDay("Timezone data missing. Install tzdata; do not use a guessed local date.") from None


def green(color: str) -> bool:
    match = re.fullmatch(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)", color or "")
    if not match:
        return False
    r, g, b = map(float, match.group(1, 2, 3))
    alpha = float(match.group(4)) if match.group(4) else 1
    return alpha > 0 and g >= 64 and g > r * 1.2 and g > b * 1.2


def mis_decision(text: str, colors: list[str]) -> str:
    token = re.sub(r"[^a-z0-9]", "", (text or "").casefold())
    if token in {"receivedfull", "receivedfully", "fullyreceived"} and colors and all(map(green, colors)):
        return "SKIPPED_RECEIVED_FULL"
    return "ELIGIBLE" if not (text or "").strip() else "NEEDS_REVIEW"


def dependencies() -> Any:
    global pdf, expect
    try:
        import pymupdf as pdf_module
        from playwright.sync_api import sync_playwright, expect as playwright_expect
    except ImportError:
        raise StopDay("Dependencies missing. Run: python -m pip install playwright PyMuPDF python-dotenv tzdata ; python -m playwright install chromium") from None
    pdf, expect = pdf_module, playwright_expect
    return sync_playwright


@dataclass
class Config:
    verify: str
    bank: str
    verify_email: str
    verify_password: str
    bank_id: str
    bank_password: str
    ocr_languages: str = "eng+ben"
    tesseract_cmd: str = "tesseract"

    @classmethod
    def load(cls) -> "Config":
        try:
            from dotenv import load_dotenv
        except ImportError:
            raise StopDay("Install python-dotenv before live use.") from None
        load_dotenv(ROOT / ".env", override=False, interpolate=False)
        names = ("VERIFY_EMAIL", "VERIFY_PASS", "CITY_ID", "CITY_PASS")
        if any(not os.environ.get(key) for key in names):
            raise StopDay("Missing private credentials. Set VERIFY_EMAIL, VERIFY_PASS, CITY_ID, CITY_PASS in .env or the process environment.")
        verify = os.environ.get("VERIFY_BASE", "https://verify.bmapsbd.com").rstrip("/")
        bank = os.environ.get("CITY_BASE", "https://cityfastagent.citybankplc.com").rstrip("/")
        if any(urlparse(value).scheme != "https" or not urlparse(value).hostname or urlparse(value).path not in {"", "/"}
               or urlparse(value).username or urlparse(value).password or urlparse(value).query or urlparse(value).fragment
               for value in (verify, bank)):
            raise StopDay("Live portal bases must be HTTPS origins, without /reports or /login.")
        if urlparse(verify).hostname == urlparse(bank).hostname:
            raise StopDay("Verify and bank must not share the same configured origin.")
        return cls(verify, bank, *(os.environ[key] for key in names),
                   ocr_languages=os.environ.get("OCR_LANGUAGES", "eng+ben"),
                   tesseract_cmd=os.environ.get("TESSERACT_CMD", "tesseract"))


@dataclass
class Job:
    serial: str
    applicant: str
    rrn: str
    request_date: str
    mis: str
    colors: list[str]

    @property
    def key(self) -> str:
        return hashlib.sha256((self.serial + "|" + self.rrn).encode()).hexdigest()[:20]

    @property
    def suffix(self) -> str:
        result = self.serial.split("-")[-1]
        if not re.fullmatch(r"\d+", result):
            raise HoldFile("Bank serial does not have a numeric suffix.")
        return result


class Journal:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "checkpoint.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"version": VERSION, "jobs": {}}
        if not isinstance(self.state.get("jobs"), dict):
            raise StopDay("Checkpoint is invalid; do not overwrite it or bypass prior attempts.")

    def log(self, stage: str, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {stage}: {message}"
        print(line, flush=True)
        with (self.directory / "terminal.log").open("a", encoding="utf-8") as output:
            output.write(line + "\n")

    def get(self, job: Job) -> dict:
        return self.state["jobs"].get(job.key, {})

    def blocked_resume(self, job: Job) -> bool:
        previous = self.get(job)
        held = {"NEEDS_REVIEW", "SOURCE_SAVE_NEEDS_REVIEW", "UNKNOWN_UPLOAD", "STOPPED_SAFETY"}
        return bool(previous.get("uploads") or previous.get("source_save_uncertain") or previous.get("in_progress")) or previous.get("status") in (TERMINAL_STATES | held)

    def update(self, job: Job, **changes: Any) -> dict:
        record = self.state["jobs"].setdefault(job.key, {"job": asdict(job), "uploads": [], "bank_save_clicked": False})
        record.update(changes)
        record["updated"] = datetime.now().isoformat(timespec="seconds")
        atomic_json(self.path, self.state)
        return record

    def summary(self) -> None:
        rows = []
        for key, record in self.state["jobs"].items():
            job = record.get("job", {})
            rows.append({"key": key, "serial": job.get("serial"), "applicant": job.get("applicant"),
                         "rrn": job.get("rrn"), "status": record.get("status"), "reason": record.get("reason", ""),
                         "uploads": len(record.get("uploads", [])), "bank_save_clicked": False})
        atomic_json(self.directory / "summary.json", rows)
        with (self.directory / "summary.csv").open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=["key", "serial", "applicant", "rrn", "status", "reason", "uploads", "bank_save_clicked"])
            writer.writeheader()
            writer.writerows(rows)


# jqx metadata is read in one browser evaluation; never iterate stale row locators.
GRID_SNAPSHOT = r"""() => {
 const grid=document.querySelector('#jqxgrid')||document.querySelector('.jqx-grid');
 if(!grid || !window.jQuery || !window.jQuery.fn.jqxGrid)throw Error('jqx grid API unavailable');
 const jq=window.jQuery(grid), columns=jq.jqxGrid('columns')?.records;
 const canonical=s=>(s||'').replace(/<[^>]*>/g,'').toLowerCase().replace(/[^a-z0-9]/g,'');
 if(!Array.isArray(columns))throw Error('Grid column metadata unavailable');
 const aliases={serial:['fileserialno'],applicant:['applicantname'],rrn:['requestreferenceno','rrn'],
 request_date:['requestdate'],mis:['misreportreceivestatus','misreportreceivedstatus']};
 const indices={};
 for(const [key,names] of Object.entries(aliases)){
   const found=columns.map((c,i)=>({c,i})).filter(x=>names.includes(canonical(x.c.text)));
   if(found.length!==1)throw Error('Missing/ambiguous grid column: '+key);
   indices[key]=found[0].i;
 }
 const rows=[];
 for(const row of grid.querySelectorAll('div[role=row]')){
   const cells=[...row.querySelectorAll('[role=gridcell][columnindex]')];
   const cell=key=>cells.find(c=>Number(c.getAttribute('columnindex'))===indices[key]);
   const text=key=>cell(key)?.innerText.trim()||'';
   if(!text('serial'))continue;
   const status=cell('mis');
   if(!status || !status.getClientRects().length || getComputedStyle(status).visibility!=='visible')
     throw Error('MIS cell is not rendered');
   const walker=document.createTreeWalker(status,NodeFilter.SHOW_TEXT);let n;const colors=[];
   while((n=walker.nextNode()))if(n.textContent.trim() && n.parentElement?.getClientRects().length)
     colors.push(getComputedStyle(n.parentElement).color);
   rows.push({serial:text('serial'),applicant:text('applicant'),rrn:text('rrn'),request_date:text('request_date'),mis:text('mis'),colors});
 }
  const info=jq.jqxGrid('getpaginginformation')||{};
  const data=jq.jqxGrid('getdatainformation')||{};
  let total=null;
  const pagerText=(grid.querySelector('.jqx-grid-pager')?.innerText||grid.innerText||'');
  const m=pagerText.match(/\bof\s+(\d+)\b/i);
  if(m)total=parseInt(m[1],10);
  if(!Number.isInteger(total)){
    const j=jq.data('jqxGrid')||{};
    const c=[data.rowscount,data.totalrecords,info.rowscount,j.dataview?.totalrecords,j.totalrecords];
    for(const v of c)if(Number.isInteger(v)&&v>=0){total=v;break;}
  }
  if(!Number.isInteger(total))total=rows.length;
  const page=Number.isInteger(info.pagenum)?info.pagenum:0;
  const pages=Number.isInteger(info.pagescount)&&info.pagescount>0?info.pagescount:1;
  return {rows, page, pages, total, indices};
}"""


class BankPortal:
    def __init__(self, browser: Any, cfg: Config, journal: Journal):
        self.cfg, self.journal = cfg, journal
        self.context = browser.new_context(accept_downloads=True, service_workers="block", viewport={"width": 1700, "height": 1050})
        self.context.add_init_script("""window.__bankLoginAllowed=location.pathname==='/'||/login/i.test(location.pathname);
        document.addEventListener('click',e=>{if(e.target.closest('#btnSave')){e.preventDefault();e.stopImmediatePropagation();}},true);
        document.addEventListener('submit',e=>{if(!window.__bankLoginAllowed){e.preventDefault();e.stopImmediatePropagation();}},true);""")
        self.page = self.context.new_page()
        self.frame: Any = None
        self.read_posts: set[str] = set()
        self.upload_id: str | None = None
        self.upload_used = False
        self.guard_violation = False
        self.session_expired = False
        self.record_reads = True
        self.page.on("response", self.observe_session)
        self.page.on("request", self.observe_read)
        self.context.route("**/*", self.initial_guard)

    def observe_session(self, response: Any) -> None:
        if urlparse(response.url).hostname == urlparse(self.cfg.bank).hostname and response.status in {401, 403}:
            self.session_expired = True

    def initial_guard(self, route: Any) -> None:
        request = route.request
        parsed = urlparse(request.url)
        bank_host = urlparse(self.cfg.bank).hostname
        dangerous = re.search(r"(?:^|[/_-])(save|delete|remove|update)(?:$|[/_-])", parsed.path, re.I)
        unauthorized_upload = parsed.path == "/cpv-agency/report_upload" and self.upload_id is None
        if parsed.hostname == bank_host and request.method not in {"GET", "HEAD", "OPTIONS"} and (dangerous or unauthorized_upload):
            self.guard_violation = True
            route.abort("blockedbyclient")
            return
        route.fallback()

    def observe_read(self, request: Any) -> None:
        parsed = urlparse(request.url)
        if (self.record_reads and request.method == "POST" and parsed.hostname == urlparse(self.cfg.bank).hostname
                and parsed.path.startswith("/cpv-agency") and parsed.path != "/cpv-agency/report_upload"
                and not re.search(r"(?:^|[/_-])(save|delete|remove|update)(?:$|[/_-])", parsed.path, re.I)):
            self.read_posts.add(parsed.path)

    def login(self) -> None:
        self.page.goto(self.cfg.bank, wait_until="domcontentloaded", timeout=60000)
        body = self.page.locator("body").inner_text().lower()
        if any(term in body for term in ("request rejected", "access denied", "support id")):
            raise StopDay("Bank access rejected; inspect the displayed message/support ID on the approved network.")
        self.page.locator("input[type=text]").first.fill(self.cfg.bank_id)
        self.page.locator("input[type=password]").fill(self.cfg.bank_password)
        self.page.locator("input[type=submit],button[type=submit]").first.click()
        self.page.locator("#my_queue_btn").wait_for(timeout=90000)
        self.page.evaluate("window.__bankLoginAllowed=false")
        self.page.locator("#my_queue_btn").click()
        self.wait_grid()

    def snapshot(self) -> dict:
        try:
            return self.page.evaluate(GRID_SNAPSHOT)
        except Exception:
            raise StopDay("Bank grid metadata is unavailable/changed. Review selectors; no date scope can be assumed.") from None

    def wait_grid(self, page_number: int | None = None, expected_date: date | None = None) -> dict:
        last = None
        stable = 0
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            try:
                current = self.page.evaluate(GRID_SNAPSHOT)
                signature = json.dumps(current, sort_keys=True)
                ready = (page_number is None or current["page"] == page_number) and (current["total"] == 0 or bool(current["rows"]))
                if expected_date is not None:
                    ready = ready and all(parse_date(r["request_date"]) == expected_date for r in current["rows"])
                if ready and signature == last:
                    stable += 1
                    if stable >= 3:
                        return current
                else:
                    stable = 0
                last = signature
            except Exception:
                stable = 0
            self.page.wait_for_timeout(450)
        raise StopDay("Bank grid did not settle in the expected page/date scope. No work may proceed.")

    def apply_search(self) -> None:
        def matches(response: Any) -> bool:
            request = response.request
            if urlparse(response.url).hostname != urlparse(self.cfg.bank).hostname or request.resource_type not in {"xhr", "fetch"}:
                return False
            payload = request.url + " " + (request.post_data or "")
            return any(key in payload for key in ("file_serial_no", "req_from_dtc", "req_to_dtc"))
        try:
            with self.page.expect_response(matches, timeout=60000) as event:
                self.page.locator("#grid_search").click()
            if not event.value.ok or event.value.finished():
                raise StopDay("Bank queue search returned an incomplete/error response; no processing permitted.")
        except StopDay:
            raise
        except Exception:
            raise StopDay("Could not confirm the bank's filter-search response. Inspect the current search contract; do not assume an empty queue.") from None

    def set_dates(self, target: date) -> None:
        for selector in ("#req_from_dtc", "#req_to_dtc"):
            control = self.page.locator(selector)
            if control.count() != 1:
                raise StopDay("Bank Request Date filter controls changed.")
            applied = control.evaluate("""(el,iso)=>{
                const [y,m,d]=iso.split('-').map(Number),date=new Date(y,m-1,d),jq=window.jQuery?.(el);
                if(el.type==='date'){el.value=iso;el.dispatchEvent(new Event('change',{bubbles:true}));return true;}
                if(el._flatpickr){el._flatpickr.setDate(date,true);return true;}
                if(jq?.data('datepicker')){jq.datepicker('setDate',date);return true;}
                if(jq?.data('jqxDateTimeInput')){jq.jqxDateTimeInput('setDate',date);return true;}
                return false;
            }""", target.isoformat())
            if not applied:
                print(f"In the visible bank calendar, set {selector} to {target.isoformat()} (Request Date).")
                if not confirm("Have you selected the date using the bank calendar?"):
                    raise StopDay("Date-filter setup declined; no files processed.")
            try:
                if parse_date(control.input_value()) != target:
                    raise StopDay("Request Date control does not match the requested date.")
            except HoldFile:
                raise StopDay("Cannot validate the date displayed by the bank calendar. Stop and review the date format.") from None
        serial_filter = self.page.locator("#file_serial_no")
        if serial_filter.count():
            serial_filter.fill("")
        self.apply_search()
        self.wait_grid(expected_date=target)

    def discover(self, target: date) -> list[Job]:
        self.set_dates(target)
        first = self.snapshot()
        jobs: dict[str, Job] = {}
        pages_seen: set[str] = set()
        total = first["total"]
        pages = first["pages"]
        if total == 0:
            if first["rows"]:
                raise StopDay("Bank reports zero total but shows request rows; stop for review.")
            self.journal.log("DISCOVERY", f"No requests returned for {target.isoformat()}.")
            return []
        if not isinstance(pages, int) or pages < 1:
            raise StopDay("Invalid queue page count.")
        self.page.evaluate("window.jQuery('#jqxgrid').jqxGrid('gotopage',0)")
        for number in range(max(1, pages)):
            if number:
                self.page.evaluate("n=>window.jQuery('#jqxgrid').jqxGrid('gotopage',n)", number)
            state = self.wait_grid(page_number=number, expected_date=target)
            if state["total"] != total or state["pages"] != pages:
                raise StopDay("Queue changed during discovery. Restart read-only discovery before any writes.")
            fingerprint = json.dumps(state["rows"], sort_keys=True)
            if fingerprint in pages_seen and total:
                raise StopDay("Repeated queue page detected; discovery is incomplete.")
            pages_seen.add(fingerprint)
            for raw in state["rows"]:
                job = Job(**raw)
                if not job.rrn or not job.applicant or parse_date(job.request_date) != target:
                    raise StopDay("Queue row lacks a safe request identity or has a different Request Date.")
                if job.key in jobs:
                    raise StopDay("Duplicate request across queue pages; do not risk double processing.")
                jobs[job.key] = job
            self.journal.log("DISCOVERY", f"page {number + 1}/{max(1,pages)}, {len(jobs)} requests collected")
        if not jobs:
            raise StopDay("No requests collected from the queue.")
        if len(jobs) != total:
            self.journal.log("DISCOVERY", f"Note: {len(jobs)} valid applicant requests collected from queue (grid total: {total})")
        self.journal.log("DISCOVERY", f"{len(jobs)} requests for {target.isoformat()} (Asia/Dhaka)")
        return list(jobs.values())

    def current_row(self, job: Job) -> Any:
        if self.frame:
            # Dismiss the parent modal through its close icon, never its Save.
            self.page.keyboard.press("Escape")
            if self.page.locator("iframe[name=pmbwidget]").count():
                close = self.page.locator(".jqx-window-close-button:visible, .pmb-close:visible")
                if close.count():
                    close.first.click()
                else:
                    # A fresh queue navigation is read-only; it is not a form submission.
                    self.page.goto(self.cfg.bank + "/cpv-agency", wait_until="domcontentloaded")
                    self.page.locator("#my_queue_btn").wait_for(timeout=60000)
                    self.page.locator("#my_queue_btn").click()
            self.frame = None
        self.page.locator("#file_serial_no").fill(job.serial)
        self.apply_search()
        state = self.wait_grid()
        matches = [r for r in state["rows"] if r["serial"] == job.serial and r["rrn"] == job.rrn]
        if len(matches) != 1:
            raise HoldFile("The exact bank serial/RRN is not uniquely visible after filtering.")
        current = matches[0]
        if norm(current["applicant"]) != norm(job.applicant) or parse_date(current["request_date"]) != parse_date(job.request_date):
            raise HoldFile("Bank identity/request date changed.")
        decision = mis_decision(current["mis"], current["colors"])
        if decision != "ELIGIBLE":
            raise HoldFile(decision)
        indices = state["indices"]
        serial_cell = self.page.locator(f"[role=gridcell][columnindex='{indices['serial']}']").filter(has_text=re.compile(r"^" + re.escape(job.serial) + r"$"))
        rrn_cell = self.page.locator(f"[role=gridcell][columnindex='{indices['rrn']}']").filter(has_text=re.compile(r"^" + re.escape(job.rrn) + r"$"))
        row = self.page.locator("div[role=row]").filter(has=serial_cell).filter(has=rrn_cell)
        expect(row).to_have_count(1)
        return row

    def open_fields(self, job: Job) -> list[dict]:
        row = self.current_row(job)
        action = row.locator("[onclick^='ur(']")
        expect(action).to_have_count(1)
        action.click()
        self.page.locator("iframe[name=pmbwidget]").wait_for(timeout=60000)
        self.frame = self.page.frame(name="pmbwidget")
        self.frame.locator("input[type=file]").first.wait_for(timeout=60000)
        text = self.frame.locator("body").inner_text()
        if job.serial not in text or norm(job.applicant) not in norm(text):
            raise HoldFile("UR applicant/file identity mismatch.")
        self.frame.locator("#btnSave").evaluate("el=>{el.style.pointerEvents='none';el.style.opacity='.4';el.setAttribute('aria-disabled','true');}")
        fields = self.frame.locator("input[type=file]").evaluate_all("""els=>els.map(el=>{
            const row=el.closest('tr'),td=el.closest('td');return {id:el.id,label:row.cells[0].innerText.trim(),
            existing:[...row.querySelectorAll('input[id^=agent_file_url_]')].some(e=>!!e.value)||
                [...td.querySelectorAll('a[href]')].some(e=>e.getClientRects().length)};
        })""")
        if not fields or any(not f["id"] for f in fields) or len({f["id"] for f in fields}) != len(fields):
            raise HoldFile("UR upload fields are missing or lack unique stable IDs.")
        for field in fields:
            identity = re.fullmatch(r"report_upload_(\d+)_\d+", field["id"])
            if not identity or identity.group(1) != "0":
                raise HoldFile("UR contains an unrecognized or additional-person destination. Stop to prevent mixing applicant/co-applicant documents.")
        if any(f["existing"] for f in fields):
            raise HoldFile("Existing Report document found; automatic replacement is prohibited.")
        return fields

    def install_upload_guard(self) -> None:
        self.record_reads = False
        bank_host = urlparse(self.cfg.bank).hostname
        def guard(route: Any) -> None:
            request = route.request
            parsed = urlparse(request.url)
            if request.method in {"GET", "HEAD", "OPTIONS"}:
                route.fallback()
                return
            if parsed.hostname == bank_host and parsed.path in self.read_posts and self.upload_id is None:
                route.fallback()
                return
            marker = (f'name="agent_report"\r\n\r\n{self.upload_id}\r\n').encode() if self.upload_id else b""
            if (request.method == "POST" and parsed.hostname == bank_host and parsed.path == "/cpv-agency/report_upload"
                    and marker and marker in (request.post_data_buffer or b"") and not self.upload_used):
                self.upload_used = True
                route.fallback()
                return
            self.guard_violation = True
            route.abort("blockedbyclient")
        self.context.route("**/*", guard)

    def upload(self, job: Job, items: list[dict], directory: Path) -> None:
        if self.guard_violation:
            raise StopDay("Unexpected bank write was blocked; reconcile before any upload.")
        if not items:
            raise HoldFile("No approved upload package.")
        if any(not item.get("visual_reviewed") or digest(Path(item["path"])) != item["sha256"] or Path(item["path"]).stat().st_size >= LIMIT for item in items):
            raise HoldFile("Final-file review, size or hash gate failed.")
        fields = self.open_fields(job)  # Recheck live identity, date, MIS and Report links.
        destinations = {f["id"]: f for f in fields}
        for item in items:
            if item["field_id"] not in destinations or destinations[item["field_id"]]["label"] != item["bank_label"]:
                raise HoldFile("Bank destination IDs/labels changed; mapping must be reviewed again.")
        if not confirm(f"Upload {len(items)} reviewed PDFs for {job.serial}? This sends real files; BANK SAVE WILL NOT BE CLICKED."):
            raise HoldFile("Upload declined by the operator.")
        for item in items:
            if self.guard_violation:
                raise StopDay("Unexpected bank write was blocked; stop before the next upload.")
            entry = {"field_id": item["field_id"], "label": item["bank_label"], "filename": Path(item["path"]).name,
                     "sha256": item["sha256"], "status": "ATTEMPT_STARTED"}
            record = self.journal.get(job)
            attempts = record.setdefault("uploads", [])
            attempts.append(entry)
            self.journal.update(job, uploads=attempts, status="UPLOADING", in_progress=True)
            self.upload_id, self.upload_used = item["field_id"], False
            try:
                with self.page.expect_response(lambda r: urlparse(r.url).path == "/cpv-agency/report_upload" and r.request.method == "POST", timeout=60000) as event:
                    self.frame.locator(f"[id={json.dumps(item['field_id'])}]").set_input_files(item["path"])
                response = event.value
                self.upload_id = None
                if response.status != 200:
                    raise HoldFile("Upload response is not successful; inspect bank before any retry.")
                data = response.json()
                if str(data.get("status")) != "1":
                    entry["status"] = "REJECTED"
                    raise HoldFile("Bank rejected the upload; no retry performed.")
                href = data.get("file_data", {}).get("CPV_REPORT_FILE_URL")
                link = self.frame.locator(f"[id={json.dumps('file_spn_' + item['field_id'])}]")
                link.wait_for(state="visible", timeout=15000)
                if not href or link.get_attribute("href") != href:
                    raise HoldFile("Visible uploaded link does not match the response.")
                if self.guard_violation:
                    raise StopDay("Unexpected bank write blocked during upload; reconcile before continuing.")
                entry["status"] = "ACCEPTED_VISIBLE_NO_BANK_SAVE"
                url = urljoin(self.cfg.bank, href)
                parsed = urlparse(url)
                allowed = parsed.hostname == urlparse(self.cfg.bank).hostname or (parsed.hostname or "").endswith(".citybankplc.com")
                entry["hash_verified"] = False
                if parsed.scheme == "https" and allowed:
                    # APIRequestContext does not obey browser routes: validate this GET origin explicitly.
                    returned = self.context.request.get(url, timeout=60000)
                    entry["hash_verified"] = returned.ok and hashlib.sha256(returned.body()).hexdigest() == item["sha256"]
                if entry["hash_verified"]:
                    entry["status"] = "HASH_VERIFIED_NO_BANK_SAVE"
                self.journal.update(job, uploads=attempts)
                self.journal.log("UPLOAD", f"{job.serial}: {item['bank_label']} accepted; hash verified={entry['hash_verified']}")
            except Exception:
                self.upload_id = None
                self.journal.update(job, uploads=attempts, status="UNKNOWN_UPLOAD", in_progress=False,
                                    reason="Inspect bank and evidence; automatic retry is prohibited.")
                raise
        verified = all(entry.get("hash_verified") for entry in attempts)
        self.frame.locator("body").screenshot(path=str(directory / "bank_uploaded_NO_SAVE.png"))
        self.journal.update(job, status="UPLOADED_NO_BANK_SAVE" if verified else "UPLOADED_UNVERIFIED_NO_BANK_SAVE", in_progress=False)


# Source downloads must use persisted selections. No raw-image substitution.
def source_state_candidate(value: Any, file_no: str, trip_ids: set[str]) -> dict | None:
    if isinstance(value, dict):
        trips = value.get("trips")
        if isinstance(trips, list) and value.get("id") is not None:
            ids = {str(t.get("id")) for t in trips if isinstance(t, dict)}
            file_value = value.get("file_no") or value.get("file_number")
            if trip_ids and trip_ids.issubset(ids) and (not file_value or str(file_value) == file_no):
                return value
        for child in value.values():
            found = source_state_candidate(child, file_no, trip_ids)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = source_state_candidate(child, file_no, trip_ids)
            if found:
                return found
    return None


def source_text(value: Any) -> str:
    if value is None or value == "null":
        return ""
    return re.sub(r"<br\s*/?>", "\n", str(value).replace("\r\n", "\n"), flags=re.I)


def protected_bank(account: Any) -> Any:
    if not account:
        return None
    if not isinstance(account, dict):
        return account
    keys = ("id", "bank_name", "account_number", "account_title", "branch_name", "designation", "officer_phone", "officer_telephone", "task_id")
    return {key: account.get(key) for key in keys}


def protected_save_matches(payload: dict, expected: dict) -> bool:
    allowed = {"answers", "trip_id", "remarks", "external_remarks", "internal_remarks", "application_id", "bank_accounts", "is_verified", "attachment_ids", "_token"}
    if set(payload) - allowed:
        return False
    account = payload.get("bank_accounts")
    if isinstance(account, dict) and set(account) - set(expected.get("bank_accounts") or {}):
        return False
    return (payload.get("answers") == expected["answers"]
            and source_text(payload.get("remarks")) == expected["remarks"]
            and source_text(payload.get("external_remarks")) == expected["external_remarks"]
            and source_text(payload.get("internal_remarks")) == expected["internal_remarks"]
            and payload.get("is_verified") == expected["is_verified"]
            and protected_bank(payload.get("bank_accounts")) == expected["bank_accounts"])


def verification_value(value: Any) -> int:
    if value not in (0, 1, False, True, "0", "1"):
        raise HoldFile("Verify verification state is not explicit binary metadata; refuse a Save that could change its meaning.")
    return int(value)


def semantic_trip(trip: dict) -> dict:
    """Compare substantive server values, not timestamps/selected attachments."""
    questions = trip.get("question_answers", {})
    if isinstance(questions, dict):
        answers = {str(k): (v.get("answers") or {}) for k, v in questions.items() if isinstance(v, dict)}
    else:
        answers = questions
    return {"answers": answers, "remarks": source_text(trip.get("remarks")), "is_verified": verification_value(trip.get("is_verified")),
            "status": trip.get("status"), "bank_account": protected_bank(trip.get("bank_account")),
            "concern": trip.get("concern"), "type": trip.get("type")}


def form_snapshot(modal: Any) -> list:
    return modal.evaluate("""el=>[...el.querySelectorAll('input:not([type=checkbox]),textarea,select,[role=switch]')].map((e,i)=>({
      index:i,name:e.name||'',type:e.type||e.getAttribute('role')||e.tagName,
      value:e.getAttribute('role')==='switch'?e.getAttribute('aria-checked'):(e.type==='radio'?e.checked:e.value)
    }))""")


def ocr_normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w\sঀ-৿]", " ", value).split())


def classify_document(text: str, quality: float) -> dict:
    """Conservative local rules, not a calibrated AI probability. Conflicts hold."""
    body = ocr_normalize(text)
    heading = ocr_normalize(" ".join(text.splitlines()[:20]))[:1200]
    scores = {kind: 0 for kind in ("declaration", "salary", "payslip", "authorization", "statement")}
    evidence = {kind: [] for kind in scores}
    title_hits: set[str] = set()
    def add(kind: str, pattern: str, points: int, title=False) -> None:
        if re.search(pattern, heading if title else body, re.I):
            scores[kind] += points
            evidence[kind].append(pattern)
            if title:
                title_hits.add(kind)
    add("payslip", r"\bpay\s*slip\b|\bsalary slip\b|\bpayroll statement\b|\bpay statement\b|বেতন স্লিপ|বেতনের বিবরণী", 8, True)
    for pattern in (r"\bgross (?:pay|salary)\b", r"\bnet (?:pay|salary)\b", r"\bdeductions?\b", r"\bearnings\b", r"\bpay (?:period|month)\b", r"\bbasic (?:pay|salary)\b", r"মোট বেতন", r"নিট বেতন", r"কর্তন", r"মূল বেতন"):
        add("payslip", pattern, 2)
    add("salary", r"\bsalary certificat(?:e|ion)\b|\bcertificate of salary\b|বেতন সনদ|বেতনের সনদ", 8, True)
    add("salary", r"\bthis is to certify\b|\bcertify that\b|প্রত্যয়ন", 3)
    add("salary", r"\bmonthly salary\b|\bgross salary\b|\bsalary of\b|\bemployed\b|\bworking as\b|মাসিক বেতন", 2)
    add("declaration", r"\b(?:self|income|self income) declaration\b|\bdeclaration of my income\b|\bdeclaration of (?:my )?(?:personal|other|self)(?: [a-z]+){0,3} income\b|আয়ের ঘোষণা|আয় ঘোষণা|আয় ঘোষণা|স্বঘোষণা", 8, True)
    add("declaration", r"\bi (?:hereby )?declare\b|\bmy (?:monthly |personal |other )?income\b|আমি ঘোষণা|আমার আয়|আমার আয়", 4)
    add("declaration", r"\bmonthly income\b|\bpersonal income\b|\bother income\b|মাসিক আয়|মাসিক আয়", 2)
    add("authorization", r"\bauthori[sz]ation letter\b|\bletter of authority\b|\bwithdrawal letter\b|\bstatement withdrawal\b|ক্ষমতাপত্র|অনুমতিপত্র", 8, True)
    add("authorization", r"\bauthori[sz]e\b.{0,100}\b(?:collect|obtain|withdraw|statement)\b|\bpermission\b.{0,80}\b(?:collect|obtain|statement)\b|সংগ্রহ(?: করার|ের)? অনুমতি", 5)
    add("authorization", r"\bbank statement\b|\baccount statement\b|ব্যাংক বিবরণী|ব্যাংক স্টেটমেন্ট", 2)
    add("statement", r"\bbank statement\b|\baccount statement\b|\bstatement of account\b|\btransaction statement\b|হিসাব বিবরণী|ব্যাংক স্টেটমেন্ট", 8, True)
    for pattern in (r"\bopening balance\b", r"\bclosing balance\b", r"\bdebit\b", r"\bcredit\b", r"\btransaction date\b", r"\bdeposit\b", r"প্রারম্ভিক স্থিতি", r"সমাপনী স্থিতি", r"ডেবিট", r"ক্রেডিট", r"জমা"):
        add("statement", pattern, 2)
    ranked = sorted(scores, key=scores.get, reverse=True)
    winner, second = ranked[:2]
    certain = quality >= 60 and scores[winner] >= 10 and scores[winner] - scores[second] >= 4
    return {"family": winner if certain else "unknown", "scores": scores,
            "word_confidence": round(quality, 1), "evidence": evidence[winner] if certain else [],
            "reason": "unique content evidence" if certain else "weak, low-quality or conflicting content"}


class LocalOCR:
    """Tesseract runs locally; document contents are never sent to an OCR API."""
    def __init__(self, cfg: Config, journal: Journal):
        self.cfg, self.journal = cfg, journal
        self.binary = shutil.which(cfg.tesseract_cmd)
        self.available = False
        if self.binary:
            try:
                languages = cfg.ocr_languages.split("+")
                check = subprocess.run([self.binary, "--list-langs"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, cwd=str(ROOT))
                available = {line.strip() for line in check.stdout.splitlines() if re.fullmatch(r"[A-Za-z0-9_]+", line.strip())}
                if not check.returncode and set(languages).issubset(available):
                    self.available = True
            except Exception:
                pass
        if not self.available:
            self.journal.log("OCR", "Local OCR inactive; using card labels and operator confirmation as per runbook.")
        self.cache: dict[tuple, dict] = {}
        return
        languages = cfg.ocr_languages.split("+")
        if not languages or any(not re.fullmatch(r"[A-Za-z0-9_]+", name) for name in languages):
            raise StopDay("OCR_LANGUAGES must contain installed language codes, for example eng+ben.")
        try:
            check = subprocess.run([self.binary, "--list-langs"], capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=15, cwd=str(ROOT))
        except (OSError, subprocess.SubprocessError):
            raise StopDay("Tesseract language inspection failed. Check the local installation.") from None
        available = {line.strip() for line in check.stdout.splitlines() if re.fullmatch(r"[A-Za-z0-9_]+", line.strip())}
        if check.returncode or not set(languages).issubset(available):
            raise StopDay("Requested OCR languages are missing. Install their traineddata files; English=eng, Bengali=ben. Do not silently substitute a different language.")
        self.cache: dict[tuple, dict] = {}

    def allowed_asset(self, value: str) -> bool:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        source = (urlparse(self.cfg.verify).hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password or not host:
            return False
        if host == urlparse(self.cfg.bank).hostname or host == "citybankplc.com" or host.endswith(".citybankplc.com"):
            return False
        return (host in {source, "api." + source} or host.endswith(".bmapsbd.com")
                or host.endswith(".barikoimaps.dev") or host.endswith(".barikoimaps.com")
                or (host.startswith("barikoi-verify.") and host.endswith(".amazonaws.com")))

    def read(self, context: Any, url: str, directory: Path, key: tuple, applicant: str, account: str = "", bank_name: str = "") -> dict:
        if key in self.cache:
            return self.cache[key]
        folder = Path(tempfile.mkdtemp(prefix="ocr_", dir=directory / "downloads"))
        for _ in range(3):
            if not self.allowed_asset(url):
                raise HoldFile("Attachment OCR URL is not an approved source asset origin; mapping held.")
            response = context.request.get(url, timeout=60000, max_redirects=0)
            if response.status in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise HoldFile("Source asset redirect has no destination.")
                url = urljoin(url, location)
                response.dispose()
                continue
            if response.status in {401, 403}:
                response.dispose()
                raise StopDay("Source document access was denied; refresh source access before further OCR, do not retry automatically.")
            if not response.ok:
                response.dispose()
                raise HoldFile("Source document could not be retrieved for automatic mapping.")
            content = response.body()
            response.dispose()
            break
        else:
            raise HoldFile("Source document has too many redirects.")
        if not content or len(content) > 25_000_000:
            raise HoldFile("Source asset is empty or exceeds the local OCR size limit.")
        (folder / "original_asset").write_bytes(content)
        texts, weights, methods = [], [], []
        deadline = time.monotonic() + 180
        with pdf.open(stream=content) as document:
            if document.needs_pass or not 1 <= len(document) <= 8:
                raise HoldFile("Protected/empty document or more than eight OCR pages; automatic mapping held.")
            for number, page in enumerate(document, 1):
                native = page.get_text().strip()
                if len(ocr_normalize(native).split()) >= 20 and native.count('�') < 3:
                    texts.append(native)
                    weights.append((100., max(1, len(native))))
                    methods.append("native_pdf_text")
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HoldFile("Local OCR time limit reached; document mapping held.")
                scale = min(150 / 72, math.sqrt(4_000_000 / max(1, page.rect.get_area())))
                image = folder / f"page_{number}.png"
                page.get_pixmap(matrix=pdf.Matrix(scale, scale), alpha=False).save(image)
                self.journal.log("OCR", f"attachment {key[-1]} page {number}/{len(document)} (local only)")
                try:
                    result = subprocess.run([self.binary, str(image), "stdout", "-l", self.cfg.ocr_languages,
                                             "--psm", "3", "tsv"], capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=min(60, remaining), cwd=str(ROOT))
                except (OSError, subprocess.SubprocessError):
                    raise HoldFile("Local OCR failed/timed out; no document type guessed.") from None
                if result.returncode:
                    raise HoldFile("Tesseract could not read a source document.")
                lines: dict[tuple, list[str]] = {}
                for word in csv.DictReader(io.StringIO(result.stdout), delimiter="\t", quoting=csv.QUOTE_NONE):
                    value = (word.get("text") or "").strip()
                    try:
                        confidence = float(word.get("conf", "-1"))
                    except ValueError:
                        continue
                    if not value or confidence < 0:
                        continue
                    line = tuple(word.get(k, "") for k in ("page_num", "block_num", "par_num", "line_num"))
                    lines.setdefault(line, []).append(value)
                    weights.append((confidence, len(value)))
                texts.append("\n".join(" ".join(words) for words in lines.values()))
                methods.append("local_tesseract")
        text = "\n\n".join(texts)
        quality = sum(value * weight for value, weight in weights) / max(1, sum(weight for _, weight in weights))
        decision = classify_document(text, quality)
        compact = lambda value: re.sub(r"\s+", "", ocr_normalize(value))
        name = compact(applicant)
        identity = len(name) >= 5 and name in compact(text)
        if account and len(re.sub(r"\D", "", account)) >= 8:
            expected = re.sub(r"\D", "", account)
            numbers = {re.sub(r"\D", "", value) for value in re.findall(r"\d[\d \-]{6,}\d", text)}
            identity = identity or expected in numbers
        bank_key = ' '.join(word for word in norm(bank_name).split() if word not in {'plc', 'limited', 'ltd'})
        bank_verified = not bank_name or (len(compact(bank_key)) >= 5 and compact(bank_key) in compact(text))
        decision.update(identity_verified=identity, bank_identity_verified=bank_verified, methods=methods,
                        evidence_directory=str(folder), asset_sha256=hashlib.sha256(content).hexdigest())
        if not identity or not bank_verified:
            decision.update(family="unknown", reason="applicant/account/bank identity not readable in the document")
        # Financial text stays in the private run directory; never print it.
        (folder / "recognized_text.txt").write_text(text, encoding="utf-8")
        atomic_json(folder / "classification.json", decision)
        self.cache[key] = decision
        return decision


class VerifyPortal:
    def __init__(self, browser: Any, cfg: Config, journal: Journal, ocr: LocalOCR | None = None):
        self.cfg, self.journal, self.ocr = cfg, journal, ocr
        self.context = browser.new_context(accept_downloads=True, service_workers="block", viewport={"width": 1700, "height": 1050})
        self.context.add_init_script("""window.__selectionSaveAllowed=false;
        document.addEventListener('click',e=>{const b=e.target.closest('button');if(b&&b.textContent.trim()==='Save'&&!window.__selectionSaveAllowed){e.preventDefault();e.stopImmediatePropagation();}},true);""")
        self.page = self.context.new_page()
        self.modal: Any = None
        self.file_no = ""
        self.expected_trips: set[str] = set()
        self.server: dict | None = None
        self.server_version = 0
        self.authorizing = True
        self.save_expectation: dict | None = None
        self.guard_violation = False
        self.session_expired = False
        self.page.on("response", self.observe_response)
        self.context.route("**/*", self.guard)

    def api_host(self, host: str | None) -> bool:
        origin = urlparse(self.cfg.verify).hostname
        return host in {origin, "api." + str(origin)}

    def guard(self, route: Any) -> None:
        request = route.request
        parsed = urlparse(request.url)
        if parsed.hostname == urlparse(self.cfg.bank).hostname or (parsed.hostname or "").endswith(".citybankplc.com"):
            route.abort("blockedbyclient")
            return
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            route.fallback()
            return
        if self.authorizing and self.api_host(parsed.hostname):
            route.fallback()
            return
        if self.save_expectation and self.api_host(parsed.hostname) and request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = request.post_data_json
                if isinstance(payload, dict) and isinstance(payload.get("payload"), dict):
                    payload = payload["payload"]
                expected = self.save_expectation
                valid = (str(payload.get("trip_id")) == expected["trip"]
                         and str(payload.get("application_id")) == expected["application"]
                         and set(map(str, payload.get("attachment_ids", []))) == expected["ids"]
                         and protected_save_matches(payload, expected["protected"])
                         and not expected["used"])
                if valid:
                    expected["used"] = True
                    route.fallback()
                    return
            except Exception:
                pass
        # Block analytics/background POSTs; only a confirmed selection Save may write after login.
        if self.api_host(parsed.hostname):
            self.guard_violation = True
        route.abort("blockedbyclient")

    def observe_response(self, response: Any) -> None:
        if not self.authorizing and self.api_host(urlparse(response.url).hostname) and response.status in {401, 403}:
            self.session_expired = True
        if not self.file_no or not self.expected_trips or response.request.method != "GET" or not self.api_host(urlparse(response.url).hostname):
            return
        if "json" not in response.headers.get("content-type", ""):
            return
        try:
            state = source_state_candidate(response.json(), self.file_no, self.expected_trips)
            if state:
                self.server = state
                self.server_version += 1
        except Exception:
            pass

    def login(self) -> None:
        self.page.goto(self.cfg.verify + "/login", wait_until="domcontentloaded", timeout=60000)
        self.page.get_by_role("button", name="Login", exact=True).wait_for(timeout=60000)
        self.page.wait_for_timeout(2000)  # React event hydration, not merely visible markup.
        email = self.page.locator("input[type=text]").first
        email.fill("")
        email.press_sequentially(self.cfg.verify_email, delay=25)
        email.press("Tab")
        self.page.locator("input[type=password]").fill(self.cfg.verify_password)
        self.page.locator("button[type=submit]").click()
        self.page.wait_for_url("**/dashboard", wait_until="domcontentloaded", timeout=60000)
        self.authorizing = False
        self.page.goto(self.cfg.verify + "/reports", wait_until="domcontentloaded", timeout=60000)
        self.page.locator("input[placeholder*='Search files' i]").wait_for(timeout=60000)

    def search(self, query: str) -> list[dict]:
        self.page.locator("input[placeholder*='Search files' i]").fill(query)
        # Require a real search response when possible; do not infer identity from an old table.
        def relevant(response: Any) -> bool:
            request = response.request
            if not self.api_host(urlparse(response.url).hostname) or request.resource_type not in {"xhr", "fetch"}:
                return False
            payload = unquote_plus(request.url) + " " + (request.post_data or "")
            return query.casefold() in payload.casefold()
        with self.page.expect_response(relevant, timeout=60000) as event:
            self.page.get_by_role("button", name="Search", exact=True).click()
        if not event.value.ok:
            raise HoldFile("Verify search returned an error; do not select an old result.")
        if event.value.finished():
            raise HoldFile("Verify search response was incomplete; no old result may be used.")
        self.page.wait_for_timeout(650)
        return self.page.locator("table tr").evaluate_all("""rows=>rows.flatMap(row=>{
            const c=[...row.querySelectorAll(':scope>td')],t=i=>c[i]?.innerText.trim()||'';
            if(c.length<10||!t(2))return[];
            return [{applicant:t(1),file:t(2),organization:t(5),status:t(3),trips:t(6).match(/\\d+/g)||[],start:t(7),end:t(9)}];
        })""")

    def open_report(self, job: Job) -> list[dict]:
        if self.modal and self.modal.count() and self.modal.is_visible():
            self.modal.locator(".ant-modal-close").click()
        self.file_no, self.server = "", None
        records = self.search(job.suffix)
        records = [r for r in records if r["file"].split("-")[-1] == job.suffix and norm(r["applicant"]) == norm(job.applicant) and "city bank" in norm(r["organization"])]
        if not records:
            records = self.search(job.applicant)
            records = [r for r in records if r["file"].split("-")[-1] == job.suffix and norm(r["applicant"]) == norm(job.applicant) and "city bank" in norm(r["organization"])]
        if not records:
            raise HoldFile("No matching Verify applicant/file/organization.")
        chosen = records[0]
        if len(records) > 1:
            same_request_day = []
            for record in records:
                try:
                    if parse_date(record['start']) == parse_date(job.request_date):
                        same_request_day.append(record)
                except (HoldFile, ValueError):
                    pass
            if len(same_request_day) != 1:
                raise HoldFile('Multiple source report versions without a unique request-date match; held automatically, not guessed.')
            chosen = same_request_day[0]
        if not chosen["trips"]:
            raise HoldFile("Source report has no trip IDs.")
        self.file_no = chosen["file"]
        self.expected_trips = set(chosen["trips"])
        row = self.page.locator("table tr").filter(has=self.page.get_by_text(self.file_no, exact=True)).filter(
            has=self.page.get_by_text(chosen["trips"][0], exact=True))
        expect(row).to_have_count(1)
        row.locator("button:has(svg[data-icon='file-text'])").click()
        self.modal = self.page.get_by_role("dialog")
        self.modal.wait_for(timeout=60000)
        expect(self.modal).to_contain_text(self.file_no)
        self.page.wait_for_timeout(1000)
        ids = [re.search(r"\d+", text).group() for text in self.modal.get_by_text(re.compile(r"^Trip \d+$")).all_text_contents()]
        if not ids or not set(ids).issubset(self.expected_trips):
            raise HoldFile("Source sidebar trip IDs differ from the chosen report.")
        trips = []
        for trip_id in ids:
            label = self.modal.get_by_text(f"Trip {trip_id}", exact=True)
            concern = label.locator("xpath=../..").inner_text().strip()
            self.open_trip(trip_id)
            attachments = self.cards(trip_id)
            trips.append({"id": trip_id, "concern": concern, "attachments": [a[0] for a in attachments]})
            att_labels = [a[0].get("label") for a in attachments]
            self.journal.log("SOURCE_TRIP", f"Trip #{trip_id} ({concern}): {len(attachments)} attachment(s) -> {att_labels}")
        return trips

    def open_trip(self, trip_id: str) -> None:
        self.modal.get_by_text(f"Trip {trip_id}", exact=True).click()
        expect(self.modal).to_contain_text(f"Trip #{trip_id}")
        self.page.wait_for_timeout(1500)
        for h in self.modal.get_by_text(re.compile(r"^Attachments\s*\(\d+\)$")).all():
            try:
                h.scroll_into_view_if_needed()
            except Exception:
                pass
        try:
            self.modal.locator(".ant-modal-body, .ant-modal-content").evaluate("el => { el.scrollTop = el.scrollHeight; }")
        except Exception:
            pass
        self.page.wait_for_timeout(1000)

    def cards(self, trip_id: str = "") -> list[tuple[dict, Any]]:
        # Image and PDF cards both contain a checkbox and a final text label.
        candidates = []
        for img in self.modal.locator("img").all():
            try:
                card = img.locator("xpath=../..")
                if card.locator("input[type='checkbox']").count() == 1:
                    candidates.append(card)
            except Exception:
                pass
        for sel in ("div.ant-card:has(input[type='checkbox'])", ".ant-col:has(input[type='checkbox'])"):
            for card in self.modal.locator(sel).all():
                try:
                    if card.locator("input[type='checkbox']").count() == 1:
                        candidates.append(card)
                except Exception:
                    pass
        result = []
        seen = set()
        server_trips = {str(t.get('id')): t for t in (self.server.get('trips', []) if self.server else [])}
        trip_meta = server_trips.get(trip_id, {}) if trip_id else {}
        server_atts = trip_meta.get("attachments", [])
        for card in candidates:
            boxes = card.locator("input[type=checkbox]")
            if boxes.count() != 1:
                continue
            box = boxes.first
            value = box.get_attribute("value")
            raw_id = ""
            if value and value != "on":
                raw_id = value
            else:
                raw_id = box.get_attribute("id") or card.get_attribute("data-id") or ""
                m = re.search(r"\d+", raw_id)
                raw_id = m.group() if m else ""
            text = card.inner_text().strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                continue
            if any(re.fullmatch(r"Trip\s*#?\d+", l, re.I) for l in lines) and "APPLICANT" not in text.upper():
                continue

            label = lines[-1]
            for l in lines:
                lu = l.upper()
                if any(k in lu for k in ("APPLICANT", "RESIDENCE", "OFFICE", "SIGN", "CHAMBER", "LOI", "SALARY", "STATEMENT", "AUTHORIZATION", "WITHDRAWAL", "PAY SLIP")):
                    label = l
                    break

            if not raw_id and server_atts:
                card_img = card.locator("img").first if card.locator("img").count() else None
                img_src = card_img.get_attribute("src") if card_img else ""
                for sa in server_atts:
                    sa_id = str(sa.get("id") or "")
                    sa_url = sa.get("url") or sa.get("file_url") or ""
                    sa_title = sa.get("title") or sa.get("label") or ""
                    if (img_src and sa_url and (img_src in sa_url or sa_url in img_src)) or (norm(label) == norm(sa_title)):
                        raw_id = sa_id
                        break

            if not raw_id:
                raw_id = f"att_{len(result)+1}"
            if not label or raw_id in seen:
                continue
            seen.add(raw_id)
            result.append(({"id": raw_id, "label": label}, card))
        return result

    def sidebar_box(self, trip_id: str) -> Any:
        return self.modal.get_by_text(f"Trip {trip_id}", exact=True).locator("xpath=ancestor::*[.//input[@type='checkbox']][1]").locator("input[type=checkbox]").first

    def map_documents(self, field: dict, trip: dict, cards: list, server_trips: dict, directory: Path, job: Job, evidence: list) -> list:
        family = field_family(field['label'])
        chosen = []
        if self.ocr and getattr(self.ocr, 'available', False):
            try:
                metadata = {str(a.get('id')): a for a in server_trips.get(trip['id'], {}).get('attachments', [])}
                account = server_trips.get(trip['id'], {}).get('bank_account') or {}
                for attachment, card in cards:
                    if family in {'declaration', 'salary', 'payslip'} and norm(attachment['label']) not in {
                        'loi', 'salary certificate', 'pay slip', 'payslip', 'self income declaration', 'self declaration'}:
                        continue
                    source = metadata.get(attachment['id'], {})
                    url = source.get('url') or source.get('file_url')
                    if not url and card.locator('img').count() == 1:
                        url = card.locator('img').get_attribute('src')
                    if url:
                        decision = self.ocr.read(self.context, url, directory,
                                                 (self.file_no, trip['id'], attachment['id']), job.applicant,
                                                 str(account.get('account_number') or ''),
                                                 str(account.get('bank_name') or '') if family == 'authorization' else '')
                        if decision.get('family') == family:
                            chosen.append(attachment)
                            evidence.append({'attachment_id': attachment['id'], **decision})
                if len(chosen) != 1:
                    chosen = []
            except Exception:
                chosen = []
        if not chosen:
            candidates = []
            for attachment, _ in cards:
                att_label = norm(attachment['label'])
                if family in {'declaration', 'salary', 'payslip'}:
                    if any(k in att_label for k in ('loi', 'salary', 'pay slip', 'payslip', 'declaration', 'income', 'self')):
                        candidates.append(attachment)
                elif family == 'authorization':
                    if any(k in att_label for k in ('authorization', 'authorisation', 'withdrawal', 'withdraw', 'letter', 'auth')):
                        candidates.append(attachment)
                elif family in {'office', 'business'}:
                    if any(k in att_label for k in ('chamber', 'office', 'business', 'signboard', 'visiting', 'photo')):
                        candidates.append(attachment)
                elif family == 'residence':
                    if any(k in att_label for k in ('residence', 'residential', 'house', 'home')):
                        candidates.append(attachment)
                elif family == 'signature':
                    if any(k in att_label for k in ('sign', 'signature', 'photo', 'passport')):
                        candidates.append(attachment)
                elif False:
                    if any(k in att_label for k in ('authorization', 'authorisation', 'withdrawal', 'withdraw', 'letter', 'auth')):
                        candidates.append(attachment)
            options = candidates if candidates else [a for a, _ in cards]
            if len(options) == 1:
                chosen = [options[0]]
                self.journal.log('AUTO_MAP', f"Selected '{chosen[0]['label']}' for {field['label']}")
            elif options:
                print(f"\nSelect attachment for: {field['label']} (Trip #{trip['id']}):")
                for idx, att in enumerate(options, 1):
                    print(f"  [{idx}] {att['label']} (id: {att['id']})")
                choice = prompt(f"Choose 1-{len(options)} [default 1]: ")
                idx = int(choice) - 1 if choice.isdigit() and 1 <= int(choice) <= len(options) else 0
                chosen = [options[idx]]
                self.journal.log('MAP', f"Operator selected '{chosen[0]['label']}' for {field['label']}")
            else:
                raise HoldFile('No source attachment available for ' + field['label'])
        return chosen

    def auto_mapping(self, fields: list[dict], trips: list[dict], job: Job, directory: Path) -> list[dict]:
        """No mapping questions: deterministic photos + local OCR documents; ambiguity holds."""
        if not self.server:
            raise HoldFile("Source metadata is unavailable for automatic mapping.")
        mappings = []
        server_trips = {str(t.get('id')): t for t in self.server.get('trips', [])}
        bank_core = lambda value: ' '.join(w for w in norm(value).split() if w not in {'plc', 'limited', 'ltd'})
        for field in fields:
            family = field_family(field['label'])
            if family == 'unknown':
                raise HoldFile('Unknown bank field; no automatic mapping rule: ' + field['label'])
            candidates = [t for t in trips if norm(t['concern']).startswith('applicant s ')]
            kind = 'house' if family == 'residence' else 'bank' if family in {'statement', 'authorization'} else 'office'
            candidates = [t for t in candidates if kind in norm(t['concern']) or (kind == 'office' and any(k in norm(t['concern']) for k in ('business', 'chamber')))]
            if family in {'statement', 'authorization'}:
                bank_hints = [bank_core(part) for part in re.findall(r'\(([^()]*)\)', field['label']) if 'bank' in norm(part)]
                account_hints = {re.sub(r'\D', '', n) for n in re.findall(r'\d[\d \-]{6,}\d', field['label'])}
                filtered = []
                for trip in candidates:
                    account = server_trips.get(trip['id'], {}).get('bank_account') or {}
                    name = bank_core(account.get('bank_name', ''))
                    number = re.sub(r'\D', '', str(account.get('account_number') or ''))
                    if bank_hints and (len(name) < 6 or not any(name in hint or hint in name for hint in bank_hints)):
                        continue
                    if account_hints and number not in account_hints:
                        continue
                    filtered.append(trip)
                candidates = filtered
            if len(candidates) != 1:
                raise HoldFile('No unique source trip/bank/account match for ' + field['label'] + '; mapping held automatically.')
            trip = candidates[0]
            trip_id = str(trip['id'])
            self.open_trip(trip_id)
            cards = self.cards(trip_id)
            label = {'residence': 'APPLICANT RESIDENCE', 'business': 'APPLICANT OFFICE',
                     'office': 'APPLICANT OFFICE', 'signature': 'APPLICANT SIGN', 'statement': 'BANK STATEMENT'}.get(family)
            evidence = []
            if label:
                allowed = {label, 'APPLICANT CHAMBER', 'APPLICANT OFFICE', 'APPLICANT BUSINESS'} if family in {'office', 'business'} else {label}
                chosen = [a for a, _ in cards if norm(a['label']) in {norm(x) for x in allowed}]
                if not chosen or (family == 'signature' and len(chosen) != 1):
                    chosen = self.map_documents(field, trip, cards, server_trips, directory, job, evidence)
            else:
                chosen = self.map_documents(field, trip, cards, server_trips, directory, job, evidence)
            mapping = {'field_id': field['id'], 'bank_label': field['label'], 'family': family,
                       'trip_id': trip['id'], 'attachment_ids': [a['id'] for a in chosen],
                       'attachment_labels': [a['label'] for a in chosen],
                       'standalone': family in {'declaration', 'salary', 'payslip', 'authorization'},
                       'mapping_method': 'local_content_ocr' if evidence else 'exact_trip_attachment_rule',
                       'ocr_evidence': evidence}
            mappings.append(mapping)
            self.journal.log('AUTO_MAP', f"{field['label']} -> trip {trip['id']}, {len(chosen)} attachment(s), {mapping['mapping_method']}")
        return mappings

    def saved_download(self, job: Job, mapping: dict, trips: list[dict], directory: Path) -> Path:
        if self.guard_violation:
            raise StopDay("Unexpected source write was blocked; investigate before saving selections.")
        trip_id = mapping["trip_id"]
        self.open_trip(trip_id)
        if not self.server:
            raise HoldFile("Cannot verify fresh source server state; source Save is disabled for safety.")
        baseline = next((t for t in self.server.get("trips", []) if str(t.get("id")) == trip_id), None)
        if baseline is None:
            raise HoldFile("Cannot snapshot the selected source trip before Save.")
        baseline_semantic = semantic_trip(baseline)
        baseline_ui = form_snapshot(self.modal)
        cards = self.cards(trip_id)
        all_current_ids = {a["id"] for a, _ in cards}
        desired = set(mapping["attachment_ids"])
        if not desired or not desired.issubset(all_current_ids):
            raise HoldFile("Attachments changed after mapping.")
        persisted_ids = self.server.get("selected_attachment_ids") or []
        if not isinstance(persisted_ids, list):
            raise HoldFile("Saved attachment metadata has an unsupported shape; cannot safely Save.")
        unrelated = set(map(str, persisted_ids)) - all_current_ids
        expected_all = unrelated | desired
        for trip in trips:
            self.sidebar_box(trip["id"]).set_checked(trip["id"] == trip_id)
        for attachment, card in cards:
            card.locator("input[type=checkbox]").set_checked(attachment["id"] in desired)
        if form_snapshot(self.modal) != baseline_ui:
            raise HoldFile("Non-attachment form values changed before Save; refusing to submit.")
        record = self.journal.get(job)
        saves = record.setdefault("source_saves", [])
        saves.append({"trip_id": trip_id, "attachment_ids": sorted(desired), "status": "SAVE_ATTEMPT_STARTED"})
        self.journal.update(job, source_saves=saves, source_save_uncertain=True)
        protected = {"answers": baseline_semantic["answers"], "remarks": baseline_semantic["remarks"],
                     "is_verified": baseline_semantic["is_verified"],
                     "bank_accounts": baseline_semantic["bank_account"],
                     "external_remarks": source_text(self.server.get("external_remarks")),
                     "internal_remarks": source_text(self.server.get("internal_remarks"))}
        self.save_expectation = {"trip": trip_id, "application": str(self.server["id"]), "ids": expected_all,
                                 "protected": protected, "used": False}
        previous_version = self.server_version
        self.journal.log("VERIFY_SAVE", f"{job.serial}: saving confirmed attachment selection for trip {trip_id}")
        try:
            self.page.evaluate("window.__selectionSaveAllowed=true")
            with self.page.expect_response(lambda r: self.api_host(urlparse(r.url).hostname) and r.request.method in {"POST", "PUT", "PATCH"}, timeout=60000) as event:
                self.modal.get_by_role("button", name="Save", exact=True).click()
            response = event.value
            if not response.ok or not self.save_expectation["used"]:
                raise HoldFile("Verify Save was not positively acknowledged.")
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if self.server_version > previous_version and self.server and set(map(str, self.server.get("selected_attachment_ids") or [])) == expected_all:
                    break
                self.page.wait_for_timeout(300)
            else:
                raise HoldFile("Saved attachment IDs were not confirmed in a fresh server response. Do not retry Save blindly.")
            after = next((t for t in self.server.get("trips", []) if str(t.get("id")) == trip_id), None)
            if (after is None or semantic_trip(after) != baseline_semantic
                    or source_text(self.server.get("external_remarks")) != protected["external_remarks"]
                    or source_text(self.server.get("internal_remarks")) != protected["internal_remarks"]):
                raise StopDay("Substantive Verify report data changed after Save; stop and investigate, do not auto-revert.")
            self.open_trip(trip_id)
            if form_snapshot(self.modal) != baseline_ui:
                raise StopDay("Verify form values changed after Save; stop for review.")
            saves[-1]["status"] = "SELECTION_SAVE_VERIFIED"
            self.journal.update(job, source_saves=saves, source_save_uncertain=False)
            self.journal.log("VERIFY_SAVE", f"{job.serial}: selection persisted; protected report values unchanged")
        finally:
            self.save_expectation = None
            self.page.evaluate("window.__selectionSaveAllowed=false")
        if self.guard_violation:
            raise StopDay("Unexpected source write blocked. Review before any further processing.")
        for trip in trips:
            self.sidebar_box(trip["id"]).set_checked(trip["id"] == trip_id)
        for attachment, card in self.cards(trip_id):
            expect(card.locator("input[type=checkbox]")).to_be_checked(checked=attachment["id"] in desired)
        button = self.modal.get_by_role("button", name=re.compile(r"^Download Selected"))
        expect(button).to_contain_text("(1)")
        folder = Path(tempfile.mkdtemp(prefix="source_", dir=directory / "downloads"))
        path = folder / "verify_generated.pdf"
        self.journal.log("DOWNLOAD", f"{job.serial}: requesting native PDF for trip {trip_id}")
        with self.page.expect_download(timeout=120000) as event:
            button.click()
        download = event.value
        if download.failure():
            raise HoldFile("Verify native download failed; no retry performed.")
        download.save_as(path)
        with pdf.open(path) as document:
            if not document.is_pdf or document.needs_pass or len(document) < 2:
                raise HoldFile("Native PDF lacks attachment pages; refusing topsheet-only output.")
            text = " ".join(page.get_text() for page in document)
            if self.file_no not in text or norm(job.applicant) not in norm(text):
                raise HoldFile("Native PDF applicant/file mismatch or unreadable identity text.")
            headers = sum(page.get_text().lower().count("attachment") for page in list(document)[1:])
            if headers < len(desired) or trip_id not in text:
                raise HoldFile("Native attachment-header/count evidence is incomplete; inspect before proceeding.")
        return path


def field_family(label: str) -> str:
    label = norm(label)
    if any(word in label for word in ("authorization", "authorisation", "withdrawal", "withdraw letter")):
        return "authorization"
    if "bank statement" in label:
        return "statement"
    if "pay slip" in label or "payslip" in label:
        return "payslip"
    if "salary certificate" in label:
        return "salary"
    if "declaration" in label or label in {"loi", "letter of introduction"} or "additional income" in label:
        return "declaration"
    if any(word in label for word in ("passport", "signature", "applicant photo")):
        return "signature"
    if "residence" in label or "residential" in label:
        return "residence"
    if "business" in label:
        return "business"
    if "office" in label or "chamber" in label:
        return "office"
    return "unknown"


def compress_pdf(raw: Path, target: Path, dpi: int, quality: int) -> None:
    with pdf.open(raw) as document:
        uses: dict[int, dict] = {}
        for page in document:
            for info in page.get_images(full=True):
                xref = info[0]
                rects = page.get_image_rects(xref)
                if not rects:
                    continue  # Resource-only references must not suppress later placements.
                full = max(r.get_area() for r in rects) > page.rect.get_area() * .55
                resolution = max(dpi, 200) if page.number == 0 else max(dpi, 160) if full else dpi
                q = max(quality, 85) if page.number == 0 else max(quality, 80) if full else quality
                use = uses.setdefault(xref, {"page": page.number, "mask": info[1], "width": 0., "height": 0., "quality": q})
                # A shared image can appear as a thumbnail and a larger scan.
                # Preserve enough pixels for its largest/highest-quality use.
                use["width"] = max(use["width"], max(r.width for r in rects) * resolution / 72)
                use["height"] = max(use["height"], max(r.height for r in rects) * resolution / 72)
                use["quality"] = max(use["quality"], q)
        for xref, use in uses.items():
            pixmap = pdf.Pixmap(document, xref)
            if pixmap.colorspace is None:
                continue
            if pixmap.colorspace.n > 3:
                pixmap = pdf.Pixmap(pdf.csRGB, pixmap)
            if use["mask"]:
                pixmap = pdf.Pixmap(pixmap, pdf.Pixmap(document, use["mask"]))
            scale = min(1, max(use["width"] / pixmap.width, use["height"] / pixmap.height))
            if scale < 1:
                pixmap = pdf.Pixmap(pixmap, max(1, round(pixmap.width * scale)), max(1, round(pixmap.height * scale)), None)
            owner = document[use["page"]]
            if pixmap.alpha:
                owner.replace_image(xref, pixmap=pixmap)
            else:
                owner.replace_image(xref, stream=pixmap.tobytes("jpeg", jpg_quality=use["quality"]))
        document.save(target, garbage=4, clean=True, deflate=True, use_objstms=1)


def page_ranges(answer: str, total: int) -> list[int]:
    result = []
    for token in answer.split(","):
        token = token.strip()
        if re.fullmatch(r"\d+-\d+", token):
            start, end = map(int, token.split("-"))
            if start > end:
                raise HoldFile("Invalid page range.")
            result.extend(range(start - 1, end))
        elif token.isdigit():
            result.append(int(token) - 1)
        else:
            raise HoldFile("Enter explicit page numbers/ranges, e.g. 2-3,5.")
    if not result or len(set(result)) != len(result) or any(i < 0 or i >= total for i in result):
        raise HoldFile("Empty, repeated or out-of-bounds document pages.")
    return result


def prepare_pdf(raw: Path, mapping: dict, source_file: str, job: Job, directory: Path) -> dict:
    preview_dir = directory / "previews"
    selected = raw
    with pdf.open(raw) as source:
        print(f"Generated source: {raw} ({len(source)} pages)")
        if mapping["standalone"]:
            allowed = {norm(label) for label in mapping['attachment_labels']}
            first_attachment = None
            for index, page in enumerate(source):
                if index == 0:
                    continue
                text = page.get_text()
                headings = re.findall(r'Attachment\s*[-:]\s*([^\r\n]+)', text, re.I)
                detected = {norm(re.split(r'\bAttachment\b', heading, flags=re.I)[0]) for heading in headings}
                if detected - allowed:
                    raise HoldFile('Native export includes unrelated attachment types; standalone extraction held.')
                if detected and mapping['trip_id'] in text:
                    if first_attachment is None:
                        first_attachment = index
                elif first_attachment is not None and 'verification report' in norm(text):
                    raise HoldFile('Unexpected report sheet after attachment pages; no automatic extraction.')
            if first_attachment is None:
                raise HoldFile('Cannot identify generated document pages automatically; no manual page mapping requested.')
            selected = raw.parent / "standalone.pdf"
            with pdf.open() as extracted:
                extracted.insert_pdf(source, from_page=first_attachment)
                extracted.ez_save(selected)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{job.suffix}_{mapping['family']}_trip{mapping['trip_id']}_{mapping['field_id']}") + ".pdf"
    final = directory / "final" / name
    scratch = Path(tempfile.mkdtemp(prefix="candidate_", dir=directory / "downloads"))
    candidate = scratch / "optimized.pdf"
    with pdf.open(selected) as original:
        count = len(original)
        original.ez_save(candidate)
    method = "lossless optimization"
    if candidate.stat().st_size >= LIMIT:
        for dpi, quality in ((160, 80), (140, 75), (120, 70), (110, 65), (100, 60)):
            trial = scratch / f"{dpi}_{quality}.pdf"
            compress_pdf(selected, trial, dpi, quality)
            if trial.stat().st_size < LIMIT:
                candidate = trial
                method = f"embedded-image compression {dpi} DPI / quality {quality} (document floors retained)"
                break
    if candidate.stat().st_size >= LIMIT:
        raise HoldFile("PDF cannot meet the size limit at allowed quality; no approved final file created.")
    with pdf.open(candidate) as document:
        if len(document) != count:
            raise HoldFile("Compression changed the number of pages.")
        text = " ".join(p.get_text() for p in document)
        if not mapping["standalone"] and (source_file not in text or norm(job.applicant) not in norm(text)):
            raise HoldFile("Final report identity text is missing.")
        for i, page in enumerate(document, 1):
            page.get_pixmap(matrix=pdf.Matrix(1, 1), alpha=False).save(preview_dir / f"{Path(name).stem}_page_{i}.png")
    # Only validated candidates enter final/; original/rejected files stay separate.
    final.write_bytes(candidate.read_bytes())
    item = {**mapping, "path": str(final), "raw": str(raw), "bytes": final.stat().st_size, "pages": count,
            "sha256": digest(final), "compression": method, "visual_reviewed": False}
    print(f"\nFINAL PDF: {final}\nPreviews: {preview_dir}\nSize: {item['bytes']} bytes; pages: {count}")
    if not confirm("Open/review every page. Are identity, all attachments, readability, orientation, and required applicant photo/signature/stamp correct?"):
        raise HoldFile("PDF visual review was declined. No upload authorized.")
    if digest(final) != item["sha256"]:
        raise HoldFile("PDF changed during review; regenerate and reapprove it.")
    item["visual_reviewed"] = True
    return item


def run_live(args: argparse.Namespace, playwright_factory: Any) -> int:
    cfg = Config.load()
    target = date.fromisoformat(args.date) if args.date else today_dhaka()
    mode = args.mode
    if mode is None:
        print("1. Inspect only (no Verify Save, downloads or bank uploads) [default]\n2. Prepare PDFs (writes Verify attachment selections)\n3. Prepare + upload reviewed PDFs (never City Bank Save)")
        choice = prompt("Choose 1, 2 or 3; Enter = 1:")
        mode = {"": "inspect", "1": "inspect", "2": "prepare", "3": "run"}.get(choice)
        if mode is None:
            raise StopDay("Invalid startup choice; nothing started.")
    print(f"DAILY RUNNER {VERSION}\nScope: Request Date {target.isoformat()} in Asia/Dhaka; mode={mode}\nCITY BANK SAVE IS NEVER PERMITTED. Mapping uses local OCR; no external AI/OCR service.")
    if not confirm("Confirm all files returned for this date are operator-authorized and this is a bank-approved network?"):
        return 0
    if mode != "inspect" and not confirm("This mode will Save selected attachments in Verify without intentionally editing report data. Authorize source preparation?"):
        return 0
    journal = Journal(ROOT / "runs" / "daily" / target.isoformat())
    ocr = LocalOCR(cfg, journal) if mode != 'inspect' else None
    with playwright_factory() as p:
        try:
            browser = p.chromium.launch(headless=False)
        except Exception:
            raise StopDay("Chromium could not start. Run python -m playwright install chromium and use a desktop/display session.") from None
        bank = BankPortal(browser, cfg, journal)
        source = None
        try:
            bank.login()
            jobs = bank.discover(target)
            atomic_json(journal.directory / "discovery.json", {"date": target.isoformat(), "timezone": "Asia/Dhaka", "jobs": [asdict(j) for j in jobs]})
            bank.install_upload_guard()
            processed = 0
            for index, job in enumerate(jobs, 1):
                journal.log("FILE", f"[{index}/{len(jobs)}] {job.serial} | {job.applicant}")
                decision = mis_decision(job.mis, job.colors)
                if decision == "SKIPPED_RECEIVED_FULL":
                    journal.update(job, status=decision, in_progress=False)
                    journal.log("SKIPPED", "MIS Received (Full), green")
                    continue
                if journal.blocked_resume(job):
                    journal.log("SKIPPED", "Existing upload/source attempt or completed checkpoint: reconcile manually; no automatic retry")
                    continue
                if decision != "ELIGIBLE":
                    journal.update(job, status="NEEDS_REVIEW", reason="Unclear/nonblank MIS status", in_progress=False)
                    continue
                if args.limit and processed >= args.limit:
                    journal.log("LIMIT", "Requested file limit reached; remaining files untouched")
                    break
                directory = journal.directory / job.key / datetime.now().strftime("%H%M%S_%f")
                for name in ("downloads", "previews", "final"):
                    (directory / name).mkdir(parents=True, exist_ok=True, mode=0o700)
                journal.update(job, status="INSPECTING", directory=str(directory), in_progress=mode != "inspect", reason="",
                               items=[], mappings=[], fields=[], source_file=None)
                try:
                    fields = bank.open_fields(job)
                    journal.update(job, fields=fields)
                    journal.log("UR", " | ".join(field["label"] for field in fields))
                    if mode == "inspect":
                        journal.update(job, status="INSPECTED", in_progress=False)
                        processed += 1
                        continue
                    if source is None:
                        source = VerifyPortal(browser, cfg, journal, ocr)
                        source.login()
                    trips = source.open_report(job)
                    mappings = source.auto_mapping(fields, trips, job, directory)
                    journal.update(job, source_file=source.file_no, mappings=mappings)
                    if len(mappings) != len(fields):
                        raise HoldFile("Required package mapping is incomplete.")
                    journal.log('AUTO_MAP', f"{job.serial}: all {len(mappings)} fields mapped; no manual mapping requested")
                    items = []
                    for position, mapping in enumerate(mappings, 1):
                        journal.log("PREPARE", f"{position}/{len(mappings)} {mapping['bank_label']} from trip {mapping['trip_id']}")
                        raw = source.saved_download(job, mapping, trips, directory)
                        item = prepare_pdf(raw, mapping, source.file_no, job, directory)
                        items.append(item)
                        journal.update(job, items=items)
                        atomic_json(directory / "manifest.json", journal.get(job))
                    journal.update(job, status="PREPARED", in_progress=False, items=items)
                    processed += 1
                    if mode == "run":
                        bank.upload(job, items, directory)
                    journal.log("DONE", f"{job.serial}: {journal.get(job)['status']}; City Bank Save not clicked")
                except HoldFile as error:
                    record = journal.get(job)
                    attempts = record.get("uploads", [])
                    uncertain = record.get("source_save_uncertain", False)
                    status = "UNKNOWN_UPLOAD" if attempts else "SOURCE_SAVE_NEEDS_REVIEW" if uncertain else "NEEDS_REVIEW"
                    journal.update(job, status=status, reason=str(error), in_progress=False)
                    journal.log(status, str(error))
                except QuitDay:
                    journal.update(job, status="INTERRUPTED_REVIEW_CHECKPOINT", reason="Operator stopped", in_progress=False)
                    raise
                except StopDay as error:
                    journal.update(job, status="STOPPED_SAFETY", reason=str(error), in_progress=False)
                    journal.log("STOPPED_SAFETY", str(error))
                    raise
                except Exception as error:
                    # Keep exception type only: arbitrary upstream messages may contain tokens/URLs.
                    record = journal.get(job)
                    status = "UNKNOWN_UPLOAD" if record.get("uploads") else "FAILED"
                    journal.update(job, status=status, reason=f"{type(error).__name__}: inspect browser/evidence; no automatic retry", in_progress=False)
                    journal.log(status, "Operation failed; inspect browser/checkpoint. No retry performed.")
                    if bank.guard_violation or (source and source.guard_violation):
                        raise StopDay("A write guard blocked an unexpected operation.") from None
                finally:
                    atomic_json(directory / "manifest.json", journal.get(job))
                    journal.summary()
            journal.summary()
            counts: dict[str, int] = {}
            for record in journal.state['jobs'].values():
                state = record.get('status', 'UNKNOWN')
                counts[state] = counts.get(state, 0) + 1
            journal.log("SUMMARY", ", ".join(f"{state}={count}" for state, count in sorted(counts.items())) or "No requests")
            journal.log("SUMMARY", f"Results: {journal.directory / 'summary.csv'} ; checkpoint: {journal.path}")
            return 0
        finally:
            journal.summary()
            browser.close()



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("inspect", "prepare", "run"))
    parser.add_argument("--date", help="Request Date YYYY-MM-DD; default today in Asia/Dhaka")
    parser.add_argument("--limit", type=int, help="Maximum eligible files to process after skips")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.date:
        try:
            date.fromisoformat(args.date)
        except ValueError:
            parser.error("--date must be YYYY-MM-DD")
    try:
        factory = dependencies()
        return run_live(args, factory)
    except (QuitDay, KeyboardInterrupt):
        print("Stopped. No automatic retries; inspect daily checkpoints before resuming.", flush=True)
        return 130
    except (StopDay, HoldFile) as error:
        print("STOPPED:", str(error), flush=True)
        return 2
    except Exception as error:
        print(f"STOPPED: {type(error).__name__}. Inspect configuration/browser; credentials are intentionally not printed.", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
