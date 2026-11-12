# Verify → City Bank upload test (Python + Playwright)

**New engineer / project handover:** read [TECHNICAL_HANDOVER.md](../TECHNICAL_HANDOVER.md)
for architecture, setup, the complete operating procedure, recovery, selector
maintenance, security controls, and tested-versus-untested behavior.

## Junior handover: use the standalone daily runner

The junior's one-file entry point is **[daily_runner.py](../daily_runner.py)**.
Read [the daily runbook](../docs/DAILY_RUNNER.md). It scans today's Request Date,
processes eligible files sequentially, asks for mappings/review, and keeps bank
Save blocked. It uses no AI/OCR or project-module imports. Run its embedded
`--offline-test` first: prepare/run modes are locked until that exact file and
environment pass. The new tests and live behavior have **not** been executed in
this assistant session due tool permissions. The commands below describe earlier
utilities, not the supported junior daily entry point.

## Latest global policy / legacy-code distinction

Read the [global operating rules](../verify-citybank-upload-agent-prompt.md).
Verify's fixed LOI category needs OCR/content classification for declarations,
salary certificates and payslips; authorization letters must be inspected in
Bank Verification attachments. The developer-confirmed processing sequence is
trip selection → attachment selection → **Verify Save** → Download Selected.
**City Bank Save remains forbidden**, and read-only inspection must not Save.

The older scripts in this directory still contain no-Verify-Save guards and
fixed mapping logic. The root daily runner implements controlled Verify Save and
human mapping, pending validation; OCR was explicitly skipped. Do not treat the
legacy commands below as the updated daily execution workflow.
Earlier no-Save download failures do not, by themselves, prove a backend defect.

## Historical validation and existing code safeguards

A supervised test for the operator-selected applicant/file on 2026-11-10 completed
four document uploads. The bank accepted each upload; the returned PDFs were
retrieved and their SHA-256 hashes matched the local PDFs. **Save was not clicked
on either portal.** This does not establish that arbitrary files/mappings work.

The operator subsequently identified a missing applicant photo in the old
signature PDF. All four download categories now use Verify's native attachment
selection → trip selection → Download Selected (1) flow. **This corrected flow
has not been tested**, per the operator's request for code changes only. The
previous upload/hash checks establish transfer integrity, not document completeness.

**Selecting a UR file uploads it immediately. Not clicking Save is NOT a dry run.**
The bank may retain uploaded files even when the final form is not saved.

`upload_no_save.py` requires `--live-upload`, visually reviewed manifest entries,
matching hashes, a matching bank identity, and unique destination labels. It
refuses to replace existing Report-column documents or reuse a manifest with
upload attempts. The UR Save click is blocked, form submissions are blocked,
and only each explicitly intended upload POST is allowed after opening UR.

## MIS completion checker (code-only change; not yet tested)

Before opening UR, discovery reads the **MIS Report Receive Status** column by
its header and checks the actual computed font color, not the row highlight.

- **Received (Full) in green:** record `skipped_received_full`; do not open UR,
  inspect/download Verify documents, or upload anything for that file.
- **Blank status:** eligible for the existing identity, mapping and upload checks.
- **Other status, unreadable column, or a full-received label without confirmed
  green text:** stop for operator review; never assume it is pending.

This gate is shared by discovery, inventory, document preparation and upload.
The upload script reads the bank status again immediately before opening UR so
it does not trust an earlier pending result.

For a single specified file, a completed status exits cleanly as skipped. To
skip completed entries and find the next pending file in an **operator-approved**
queue, provide a JSON file containing entries with `serial` and `applicant`:

```json
[
  {"serial": "0000001", "applicant": "Replace with first approved applicant"},
  {"serial": "0000002", "applicant": "Replace with next approved applicant"}
]
```

Replace all example values with the exact authorized files; keep serials as
strings to preserve zeros. Run from `agent/`:

```bash
python test_identity.py --queue /absolute/path/to/approved-files.json
```

The read-only queue checker skips green/full entries and stops at the first
blank-status entry for identity/source review. It does **not** automatically
download/upload the queue or select unrelated customers from MY Q. Missing files,
identity mismatches and unclear statuses block the queue for review.

## Setup

From the repository root:

```bash
cd agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Root `.env` is loaded automatically using `python-dotenv`; use `.env.example`
as the blank template on another machine. Credential precedence is existing
process variables → `.env` → legacy `creds.md`. Keys: `VERIFY_EMAIL`,
`VERIFY_PASS`, `CITY_ID`, `CITY_PASS`. Portal origins are configurable using
`VERIFY_BASE` and `CITY_BASE` (no `/reports` or `/login` suffix). Existing process
variables are not overwritten; password interpolation is disabled.

Never commit/share `.env`, `creds.md`, browser state, customer PDFs, screenshots,
or run directories. Root `.gitignore` excludes private configuration and artifacts.
No browser cookies/session tokens are persisted by these scripts.

## Supervised workflow

1. **Identity and bank labels, read-only:**
   ```bash
   python test_identity.py <numeric-serial> "<exact applicant name>"
   ```
   Searches Verify by both identifier and name. A trip-number substring match is
   insufficient. Multiple report rows require inspecting dates/trips before
   selecting one; the script does not automatically choose the first row.

2. **Trip/attachment inventory, read-only:**
   ```bash
   python inspect_documents.py <numeric-serial> "<exact applicant name>"
   ```
   Inspects all exact-name/file/organization matches. No downloads or Save.

3. **Prepare one explicitly selected House/Office report pair:**
   ```bash
   python prepare_transfer_test.py <numeric-serial> "<exact applicant name>" \
     --house-trip <house-trip-id> --office-trip <office-trip-id>
   ```
   Every category opens the relevant trip, selects only the intended attachment
   labels, selects that trip's left checkbox, then uses **Download Selected (1)**.
   Raw-image downloads and locally assembled photo annexes are no longer used.

   This test mapping is specific to the four labels inspected during the test:
   - Business Address with Photo: Office/business report + APPLICANT OFFICE images.
   - Residence Address: House report + APPLICANT RESIDENCE images.
   - Office Address/Passport Size Lab Print Photo/Signature: Verify-generated
     Office report with APPLICANT SIGN selected, including Verify's generated
     applicant-photo/stamp content (must be visually checked).
   - Self Income Declaration (if any): select LOI and download through Verify,
     then retain only its generated attachment pages as a standalone PDF. The
     original full download is retained for source checks.

   **These mappings are not universal.** This preparer does not handle arbitrary
   bank-statement rows, guarantor documents, or other destination labels.

   The original report-only downloads were not equivalent to the operator's
   native workflow. The corrected preparer stops if the generated PDF lacks
   attachment pages or the expected attachment/trip header; it does not fall
   back to raw images or recreate the report layout locally. LOI/signature are
   excluded from the business-photo selection and downloaded separately through
   that same native workflow. LOI page extraction preserves generated page content.

   Files are compressed locally with PyMuPDF to **strictly below 1,000,000 bytes**.
   All pages are retained and decoded; report identity/text is checked before
   and after compression. Full-page scans retain a higher image resolution.
   **Human visual review is still required** for source quality, missing pages,
   orientation, readable details, and correct mappings. Size/page-count checks
   alone are not proof of readability or semantic correctness.

4. **Review the generated PDFs and every preview page.** The generated
   `manifest.json` starts with `visual_reviewed: false` on each item. Change each
   to `true` only after actually reviewing it. Do not change recorded hashes to
   bypass integrity checks.

5. **Only with explicit upload authorization:**
   ```bash
   python upload_no_save.py /absolute/path/to/run/manifest.json --live-upload
   ```
   It uploads through the actual UR file inputs, checks the bank's success
   response and visible report link, and tries to retrieve/hash-check the
   uploaded PDF. Inspect each manifest upload status: server acceptance is not
   the same as a successful content hash check. **Never clicks Save.** Browser
   closes after the inspection hold (30 seconds by default); screenshot evidence
   remains. Final saved-form persistence is deliberately not tested.

## Evidence and partial failures

Runs are beneath `../runs/<serial>/`, not beneath `agent/runs/`:

- `test_<timestamp>/`: bank labels and identifier-search evidence.
- `inventory_<timestamp>/`: trip/attachment inventory and screenshots.
- `transfer_<timestamp>/downloads/`: original downloads and server-check copies,
  each in a separate new subdirectory.
- `transfer_<timestamp>/final/`: validated upload PDFs.
- `transfer_<timestamp>/previews/`: page renders and contact sheets.
- `transfer_<timestamp>/shots/`: before/after bank screenshots.
- `transfer_<timestamp>/manifest.json`: source trips, mapping, sizes, hashes,
  visual review, upload responses, and no-Save status.

If a run fails after any upload attempt, **inspect the bank before retrying**.
Do not create a fresh manifest just to bypass the retry guard. The network
allowlist and failure-stop behavior intentionally favor stopping over guessing.

## Earlier prototypes

`stage_city.py` is disabled because its old picker-only assumption was unsafe.
It, `prepare_docs.py`, the older explorers, case-specific probes, and
`try_compress.py` are private historical files excluded by `.gitignore`; they may
not exist in a fresh clone and are not required to run this project.
`probe_native_download.py` is the retained generic diagnostic using explicit
operator inputs. Use the documented workflows; never publish old case-specific
scripts or treat the old preparer as production-ready.
