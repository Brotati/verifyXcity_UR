# Verify → City Bank: technical overview and operating handover

Last updated: **11 November 2026**

## 1. Start here

This project reduces the manual work of transferring applicant-verification documents from **Barikoi Verify** to the correct **City Bank CityFast UR upload fields**.

It is a **supervised Python/Playwright toolset**, not a fully autonomous production service. An operator must authorize the target files, resolve ambiguous source reports and mappings, visually review PDFs, and explicitly authorize any live upload.

### Three rules that must never be misunderstood

1. **Selecting a PDF in a City Bank UR file picker uploads it immediately.** Leaving Save unclicked does not make file selection a dry run. The bank can retain the uploaded file.
2. **Do not click Save on either portal.** The present workflow stops after uploads and their verification; final bank submission is intentionally outside scope. Never modify Verify answers, remarks, verification status, or other report data.
3. **Do not work on green “Received (Full)” MIS files.** Check bank status before source work and again before uploading. Only a positively read blank status is automatically eligible; an unknown status requires review.

### Current validation status

| Capability | Evidence/status |
|---|---|
| Portal access and login | Previously exercised successfully on the development machine/network. Access must be checked again on a new machine. |
| Bank/applicant matching and source inspection | Previously exercised for one supervised case. |
| Four file uploads without Save | Previously completed on 10 November 2026. Bank-returned PDFs were retrieved and matched local SHA-256 hashes. |
| Completeness of the old signature PDF | **Not correct:** the operator found that the old raw-image method omitted the applicant photo present in Verify's generated PDF. Matching upload hashes did not detect that semantic omission. |
| Corrected native download for all four categories | Implemented after operator feedback; **not subsequently tested**, per the request for code changes only. |
| Green/full MIS skip checker and approved-file queue | Implemented; **not yet tested** against the live portal. |
| Final Save, final submission, persisted saved-form result | Deliberately not implemented/tested. |

**Do not describe the current complete workflow as production-verified.** The first run after handover must be supervised and specifically validate the corrected downloads and MIS gate. A successful process exit alone is not sufficient evidence of correct documents.

---

## 2. System boundaries and terminology

### Portals

| System | Current code URL | Purpose |
|---|---|---|
| City Bank CityFast | `https://cityfastagent.citybankplc.com` | MY Q queue, applicant/file identity, MIS status, UR document destinations. |
| Barikoi Verify | `https://verify.bmapsbd.com` | Reports search, Update Topsheet for Trips, native document generation. |

The original [task document](verify-citybank-upload-agent-prompt.md) names an older Verify development hostname. **Current scripts use `CITY_BASE`/`VERIFY_BASE` from [agent/common.py](agent/common.py), initialized from process environment variables or the root `.env`, with the URLs above as defaults.** Set base origins only, without `/reports` or `/login`. Editing URLs in the legacy credential file alone does not switch the portals.

Run City Bank work only from a **bank-approved IP/network**. If access is rejected, stop and report the displayed message/support ID. Do not work around IP restrictions using an unapproved proxy or network.

### Identifiers

- **Full bank serial:** the complete City Bank File Serial No, including prefix, year/month, and numeric suffix.
- **Numeric serial:** the trailing bank identifier passed to the current CLI. Preserve all leading zeros.
- **Verify file number:** Verify's own file identifier, which need not equal the full bank serial.
- **Trip ID:** identifies a House, Office, Bank Verification, or other visit/verification within a source report.
- **Concern:** whose document it is: applicant, co-applicant, guarantor, etc. Never substitute another concern's attachments.
- **UR:** Upload Reports; **MY Q:** bank work queue.
- **MIS Report Receive Status:** the bank's completion indicator, independent of whether a row is selected/highlighted.

**Identity trap:** Verify search can match a trip ID or substring of another file number. Confirm the applicant name, file identifier, City Bank organization, and explicitly chosen trip set. Never trust the first result.

A single applicant/file can also have multiple report rows, for example an original visit and a later Re-CPV. Compare the bank request date/type with the source report dates and trips. The tool must not silently select an arbitrary duplicate.

---

## 3. Repository layout and active modules

```text
verifyXcity/
├── TECHNICAL_HANDOVER.md                 # This guide
├── verify-citybank-upload-agent-prompt.md # Original operational requirements
├── .env                                 # Private local settings; automatically loaded
├── .env.example                         # Safe blank configuration template
├── .gitignore                           # Excludes secrets and customer artifacts
├── creds.md                             # Legacy private credential fallback
├── images/                              # Reference screenshots; may contain customer data
├── runs/                                # Per-file evidence and sensitive documents
├── artifacts/                           # Older staging directory, not the active output path
└── agent/
    ├── README.md                        # Shorter operator guide
    ├── requirements.txt
    ├── .venv/                           # Machine-local Python environment
    ├── common.py                        # Paths, URLs, credential loading
    ├── city_status.py                   # Shared MIS completion gate
    ├── test_identity.py                 # Bank/source identity inspection and queue preflight
    ├── inspect_documents.py             # Source trip/attachment inventory
    ├── prepare_transfer_test.py          # Native downloads, local PDFs, previews, manifest
    ├── pdf_package.py                   # Local embedded-image compression
    ├── upload_no_save.py                # Authorized live UR uploads; never Save
    └── ...                              # Historical prototypes and DOM probes
```

### Module responsibilities

| Module | Main responsibilities |
|---|---|
| [common.py](agent/common.py) | Resolves project paths relative to the module; loads all four credentials; creates run directories; defines portal constants. |
| [city_status.py](agent/city_status.py) | Reads the MIS column/header and computed text colors. Returns skip/eligible or blocks for review. Makes no network requests itself. |
| [test_identity.py](agent/test_identity.py) | Logs into City Bank, checks target identity/MIS, inspects UR, searches Verify by serial and name, and inspects a unique matching Topsheet. Exports `city_check`, `norm`, and `verify_search` used by other scripts. |
| [inspect_documents.py](agent/inspect_documents.py) | Performs the bank gate, then inspects all matching source report rows and visible trips. Captures attachment labels/counts and screenshots without selecting/downloading attachments. |
| [prepare_transfer_test.py](agent/prepare_transfer_test.py) | Performs the bank gate, chooses an explicitly identified source report/trip pair, downloads four document categories using Verify's native UI, validates/compresses PDFs, and creates review evidence. |
| [pdf_package.py](agent/pdf_package.py) | `compress_images` resizes/re-encodes embedded images while retaining PDF text/pages. Its older `assemble_report` helper is **not used by the current native-download workflow**. |
| [upload_no_save.py](agent/upload_no_save.py) | Validates a reviewed manifest, rechecks bank identity/MIS, refuses existing report replacement, uploads through actual UR file inputs, verifies responses/links, and attempts uploaded-content hash verification. |

There is no required model API, MCP server, database, or web application to deploy. These are synchronous Python command-line scripts that drive Chromium.

### Do not use the older prototypes as the main workflow

- `stage_city.py` is intentionally disabled because its former “picker-only” assumption was unsafe.
- `prepare_docs.py` and `explore_verify.py` have older, unverified selectors/logic.
- `explore_city.py` has an MIS gate but remains an earlier explorer, not the recommended end-to-end entry point.
- Historical case-specific probes, explorers, `prepare_docs.py`, `stage_city.py`, and `try_compress.py` are excluded by `.gitignore` and may exist only on the original development machine. Their names are listed here as history, not required clone contents.
- `probe_native_download.py` is a retained generic diagnostic that takes explicit operator inputs; its private downloaded bundles/evidence remain ignored.
- Do not reintroduce customer-specific probes into source control, remove the staging safety exit in a local copy, or run an unfamiliar probe just because its filename looks relevant.

---

## 4. Prerequisites and installation

### Required

- Python with compatible Playwright and PyMuPDF packages. The historical development environment used **Python 3.14 on macOS**; this is not proof of compatibility on every platform/version.
- Network access to the approved bank portal and Verify.
- Working credentials for both portals, supplied through an approved private channel.
- A desktop/display session for the live uploader: it launches a **headed** browser. Discovery, inventory, and preparation use **headless** Chromium.
- Sufficient local storage for original PDFs, page previews, and downloaded server-check copies.

### Install on macOS/Linux

From the project root:

```bash
cd agent
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m playwright install chromium
```

The remaining commands in this guide assume the working directory is `agent/` and use the environment's Python directly. No shell activation is required.

On a Linux machine that lacks browser system libraries, an administrator may need Playwright's documented Chromium system dependencies. On Windows, use the virtual environment's `Scripts/python.exe` equivalent; Windows execution has not been validated here.

Current dependency lower bounds:

- `playwright>=1.40`
- `pypdf>=4.0`
- `PyMuPDF>=1.28.2`
- `python-dotenv>=1.0.1`

The active preparation code uses `pymupdf`; `pypdf` remains in requirements for older utilities. No Ghostscript, qpdf, pikepdf, or third-party compression website is required by the active workflow.

**There is no dependency lockfile.** Fresh installations can receive different package versions. Record a known-good environment after a supervised validation; do not assume installing the latest versions constitutes validation.

### Credentials

The root `.env` is automatically loaded when `common.py` is imported, regardless of the shell's working directory. On a new machine, copy `.env.example` to `.env` only if `.env` does not already exist, then fill the values privately and restrict access (for example, `chmod 600 .env` on macOS/Linux). No shell `source .env` command is needed.

| Variable | Meaning |
|---|---|
| `VERIFY_BASE` | Verify base origin; defaults to the portal URL above |
| `CITY_BASE` | City Bank base origin; defaults to the portal URL above |
| `VERIFY_EMAIL` | Verify login email |
| `VERIFY_PASS` | Verify password |
| `CITY_ID` | City Bank agent login ID |
| `CITY_PASS` | City Bank password |

Credential precedence is **existing process environment → root `.env` → legacy `creds.md` fallback**. The `.env` loader does not overwrite existing process variables, and interpolation is disabled so `$` characters in passwords are treated literally. Use `.env.example` as the shareable template; never share the populated `.env`.

Important details:

- All four values are required even when a script initially accesses only one portal.
- The legacy Markdown parser depends on simple labels/order: the first `pass:` is interpreted as Verify's password and the second as the bank password. It is not a general configuration parser.
- Keep credentials out of this guide, source code, command-line arguments, shell history, tickets, and screenshots shared outside the authorized team.
- Browser cookies/tokens are not deliberately persisted by these workflows. Do not add storage-state exports or traces containing credentials without an approved handling policy.

---

## 5. MIS checker and queue selection

The shared checker reads the actual **MIS Report Receive Status** column, not a row's yellow selection background.

| Observed status | Behavior |
|---|---|
| Exact normalized full-received status, with green computed font colors | Return `skip_received_full`. No UR or Verify work for that file. |
| Positively read blank status | Eligible for the remaining identity/document checks. Blank does not authorize an upload by itself. |
| Other nonblank status; full-received text without confirmed green font | Block for operator review. |
| Missing/ambiguous header/cell, unresolved column, or unrendered status cell | Block. Never assume the status is blank. |

Recognized full-received text normalizations are `receivedfull`, `receivedfully`, and `fullyreceived`. Green is determined by a computed RGB heuristic, not a particular CSS class, icon, or background. The checker recognizes two normalized header spellings: “MIS Report Receive Status” and “MIS Report Received Status.”

Discovery, source inventory, preparation, and upload share this gate. **Upload reads the bank status again** rather than trusting a status captured before PDF preparation.

### Single file

```bash
./.venv/bin/python test_identity.py "$SERIAL" "$APPLICANT"
```

Set the variables to an operator-approved numeric serial and exact applicant name first. A completed file exits as skipped. An eligible file receives bank/source identity inspection; no attachments are selected or uploaded.

### Approved queue

Create a private operator-approved JSON list. Example structure only—replace the dummy values:

```json
[
  {"serial": "0000001", "applicant": "Exact first approved applicant name"},
  {"serial": "0000002", "applicant": "Exact next approved applicant name"}
]
```

Then:

```bash
./.venv/bin/python test_identity.py --queue /absolute/path/to/approved-files.json
```

Behavior:

1. Validate that the queue is nonempty, serials are numeric **strings**, names are present, and serials are not duplicated.
2. Check entries in the provided order.
3. Skip green/full entries and continue to the next approved entry.
4. Stop at the first blank-status file for identity/source review—even if Verify subsequently reports an ambiguous match.
5. If every listed entry is complete, finish without source work.
6. Missing files, identity mismatches, and unclear statuses block the queue.

**This is not batch transfer.** It does not prepare/upload every queue entry or select unrelated customers from MY Q.

---

## 6. Operating procedure: one authorized file

### Step 0 — Confirm scope before running anything

Obtain from the operator:

- Approved numeric bank serial, retaining leading zeros.
- Exact applicant name.
- Permission for read-only exploration versus actual upload.
- Any case-specific destination mapping decisions.
- Confirmation that the network is bank-approved.

Never use historical examples or trip IDs as a new target by default. Do not work on arbitrary files visible in MY Q.

### Step 1 — Inspect identity and UR labels

```bash
./.venv/bin/python test_identity.py "$SERIAL" "$APPLICANT"
```

Review the generated `result.json` and screenshots under the reported evidence directory.

Confirm the full bank serial, applicant, MIS result, exact UR labels, Verify file/organization, and whether there is a unique source report. Multiple matching rows require date/trip investigation, not first-result selection.

“Read-only” here means no report changes or document uploads. Login/search can still create sessions and use normal portal requests. For eligible files, the bank preflight opens UR to read labels.

### Step 2 — Inventory source trips and attachments

```bash
./.venv/bin/python inspect_documents.py "$SERIAL" "$APPLICANT"
```

This performs the bank gate again, then records matching reports, their visible sidebar trips, attachment labels/counts, and screenshots.

Choose the source report using the bank request context and explicit trip IDs. Check that the House and Office trips belong to the applicant and the same intended report row. Inventory records when a trip listed in a result is not present in the modal; do not assume an invisible trip has been inspected.

The current preparer requires a House/Office pair. If that is not the actual case structure, stop rather than forcing it into the supported mapping.

### Step 3 — Prepare documents, without uploading

Set `HOUSE_TRIP` and `OFFICE_TRIP` to the confirmed numeric IDs, then:

```bash
./.venv/bin/python prepare_transfer_test.py "$SERIAL" "$APPLICANT" \
  --house-trip "$HOUSE_TRIP" \
  --office-trip "$OFFICE_TRIP"
```

The script performs a fresh bank gate, matches one Verify row using name, file suffix, organization, and both explicit trip IDs, and prepares four categories.

#### Current mapping

| Category | Verify trip / exact attachment label | City Bank destination | Output |
|---|---|---|---|
| Business | Office/business trip / `APPLICANT OFFICE` | `Business Address with Photo` | Verify-generated report with selected business attachments. |
| Residence | House trip / `APPLICANT RESIDENCE` | `Residence Address` | Verify-generated report with selected residence attachments. |
| Signature | Office trip / `APPLICANT SIGN` | `Office Address/Passport Size Lab Print Photo/Signature` | Verify-generated report with Applicant Sign attachment; photograph/stamp presence needs visual review. |
| LOI | Office trip / `LOI` | `Self Income Declaration (if any)` | Standalone generated LOI attachment pages, per the operator's mapping instruction. |

These are **case-specific implemented mappings**, not universal bank policy. “Office Visit” can hold business documents in the current case structure. Do not infer that every Office trip satisfies every Business field.

Bank Statement mapping exists in the original requirements but is not implemented by this four-category preparer. Co-applicant, guarantor, arbitrary additional labels, and multiple bank-specific statement fields need separate explicit handling.

#### Required native Verify download sequence

For every category:

1. Open the relevant trip in Update Topsheet.
2. Clear prior left-side trip selections.
3. Select only the intended attachment label(s).
4. Select that trip's left checkbox.
5. Assert that exactly the intended trip is selected and the attachment selection remains correct.
6. Click **Download Selected (1)** and capture the generated PDF.

The active workflow does **not** fetch attachment image URLs or rebuild report/photo pages locally. It retains Verify's generated page content. This is necessary because a raw attachment image can omit generated content such as the applicant photo/stamp visible in a native download.

For LOI, the full generated download is retained, and pages from the first matching generated LOI attachment header onward are copied into a standalone PDF. This assumes all subsequent pages belong to that selected LOI; visually confirm the result. It does not recreate, crop, or paste the LOI from a raw thumbnail.

If the generated PDF contains only a report, lacks the expected attachment/trip header, or fails identity checks, the script blocks rather than falling back to raw images.

### Step 4 — Review the complete PDF package

The preparer prints a new `transfer_<timestamp>` directory. Review:

- `manifest.json`: identities, source trip IDs, categories, exact bank labels, attachment counts, sizes, page counts, hashes, and status.
- `final/`: the PDFs that would be uploaded.
- `previews/`: individual rendered pages and contact sheets.
- Original generated PDFs in isolated `downloads/` subdirectories when comparison is needed.

For **every** document, check:

- Correct applicant, file, concern, trip, report date, and category.
- Every intended attachment is present; no unrelated LOI/signature/photos are mixed in.
- Correct orientation, no cropping/missing pages, and readable details at a reasonable zoom.
- Applicant photo, signatures, and stamp are present where required—especially the corrected Applicant Sign output.
- LOI remains standalone and is the intended income-declaration document for this case.
- Size is strictly below **1,000,000 bytes**.

The size limit is intentionally stricter than a 1 MiB interpretation. The portal's earlier inspected handler used 1,024 KB; the local guard avoids ambiguity.

Each manifest item starts with:

```json
"visual_reviewed": false
```

Only after reviewing that exact final PDF should the authorized reviewer change its item to:

```json
"visual_reviewed": true
```

There is currently no approval UI/CLI. Use an editor. Do not edit the recorded file hashes or sizes to bypass checks. If the PDF is modified afterward, regenerate and re-review the package; the uploader will reject a hash mismatch.

**Do not approve/upload a blocked or partially prepared package.** The current upload code validates the provided items but does not itself require a particular prepared-state string or exactly all four categories. The operator must verify overall status and the expected complete item set.

### Step 5 — Upload only with explicit authorization

This command performs actual server uploads:

```bash
./.venv/bin/python upload_no_save.py \
  /absolute/path/to/transfer_run/manifest.json \
  --live-upload
```

For more on-screen inspection time after upload:

```bash
./.venv/bin/python upload_no_save.py \
  /absolute/path/to/transfer_run/manifest.json \
  --live-upload --hold-seconds 120
```

The upload browser is visible. The default post-upload hold is 30 seconds, after which the browser closes. Files already uploaded can remain on the bank server; closing the browser is not rollback.

Before selecting a file, the script:

- Refuses any manifest with a prior recorded upload attempt.
- Verifies visual-review flags, final-directory containment, actual size, hash, and destination-label uniqueness.
- Matches the current bank serial and applicant.
- Rechecks MIS completion and skips green/full files.
- Opens UR and checks its identity.
- Matches destination rows by exact labels.
- Refuses pre-existing report URLs or visible document links in the **Report** cell.

The bank's **DOC** column can contain original/request documents. Those links are deliberately not treated as existing uploaded reports. Do not confuse the two columns during manual investigation.

### Step 6 — Verify results and stop without Save

For each item, the uploader records its attempt before choosing the file, waits for the upload response, requires the expected success status, and checks that the visible report link matches the bank-returned URL. It then attempts a GET of the uploaded file and compares the downloaded bytes' SHA-256 hash with the final local PDF.

Inspect each upload entry, not just the terminal summary:

- `upload_accepted_visible_no_save`: accepted with a visible matching link, but full byte-level verification is not established.
- `upload_accepted_visible_hash_verified_no_save`: accepted, visible, and retrieved bytes matched.
- `server_content_hash_matches: false`: investigate even if the overall run completed.

A failed retrieval/hash comparison does **not** currently make the whole upload command fail. Therefore `uploads_complete_save_not_clicked` means all provided files reached visible acceptance, not necessarily that every server hash matched.

**Never click Save as the last step of this runbook.** There is no supported final-submission command. Final saved-form persistence requires a separate authorization/design and is not established by upload acceptance.

---

## 7. PDF implementation details

`finalize()` in [prepare_transfer_test.py](agent/prepare_transfer_test.py) checks the input, preserves page count, applies relevant identity-text checks, saves an optimized candidate, and compresses only if needed.

`compress_images()` in [pdf_package.py](agent/pdf_package.py) works locally with PyMuPDF:

- Retains native PDF text and page structure rather than rasterizing the entire report.
- Resizes/re-encodes embedded images according to their displayed size.
- Handles image transparency/masks when replacing images.
- Tries nominal DPI/quality settings from 160/80 down to 100/60.
- Uses higher target floors for first-page images (200 DPI / quality 85) and later images occupying more than 55% of a page (160 DPI / quality 80).
- Does not improve an already low-resolution source.
- Stops if it cannot reach the size limit within its permitted settings.

These are image-compression policies, not guaranteed image quality measurements. Image bytes can change. Even the initial “lossless” path rewrites the PDF container; it does not preserve the original file bytes.

Current automated validation proves neither OCR correctness nor photograph presence, semantic completeness, readability, or correct orientation. Text checks can also reject scanned-only identity pages. Visual review is mandatory.

**Native layout takes precedence over forcing a size pass.** Do not reintroduce handmade four-photo annexes, drop attachments, or replace a generated document with its raw image just to get below 1 MB. Report the blocker if required content cannot remain readable within the limit.

---

## 8. Output directories, evidence, and manifest states

All run paths are relative to the **project root**, not `agent/`:

```text
runs/<numeric-serial>/
├── raw/                         # Legacy compatibility directories from common.run_dir
├── compressed/
├── shots/
├── test_<timestamp>/
│   ├── result.json
│   ├── city_upload_handler.txt  # For an eligible bank preflight
│   └── shots/
├── inventory_<timestamp>/
│   ├── inventory.json
│   └── shots/
└── transfer_<timestamp>/
    ├── manifest.json
    ├── downloads/               # New isolated subdirectories per original/download check
    ├── final/                   # Final compressed/optimized upload PDFs
    ├── previews/                # Individual page renders and contact sheets
    └── shots/                   # Selection, pre-upload, post-upload, skip/error evidence
```

The authoritative upload paths are the exact `items[].path` entries in the selected run's manifest. Do not upload everything found in an old global staging folder.

Typical final filenames include serial, applicant, category, and trip ID:

```text
<serial>_<applicant_name>_<category>_trip<trip_id>.pdf
```

### Key manifest fields

| Field | Meaning |
|---|---|
| `serial`, `applicant`, `bank_serial`, `verify_file` | Target/source identity. |
| `mis_status` | Observed MIS text/colors and gate decision. |
| `items[]` | Prepared files and source/destination mapping. |
| `items[].path`, `raw`, `original_generated_pdf` | Final and source-document paths. |
| `bytes`, `pages`, `sha256`, `compression` | Size/content-integrity and compression evidence. |
| `trip_id`, `attachment_label`, `attachment_count`, `bank_label` | Exact source selection and bank destination. |
| `download_method`, `attachment_only` | Native download/extraction details. |
| `visual_reviewed`, `required_visual_checks` | Human approval gate and checks still requiring visual judgment. |
| `uploads[]` | Attempts/results; a nonempty list blocks automatic rerun. |
| `save_clicked` | Intended no-Save record; must remain false. It is not a substitute for checking actual behavior. |
| `status`, `error`, `blocked_requests` | Overall progress/failure context. |

### Typical states

- Discovery: `skipped_received_full`, `pending_file_selected`, or `blocked`.
- Preparation: `preparing` → `prepared_awaiting_visual_review`; alternatively `skipped_received_full` or `blocked`.
- Upload: `uploading_no_save` → `uploads_complete_save_not_clicked`; alternatively `skipped_received_full` or `blocked_inspect_before_retry`.
- Per upload: attempt started → visible acceptance → optionally hash-verified acceptance; server rejection blocks progress.

Inventory is a separate list format and can be empty or partial after an exception. It does not have the same overall failure-state schema as the transfer manifest. Review terminal errors alongside `inventory.json`.

---

## 9. Technical details for maintaining portal selectors

### City Bank

The queue is a **jqx-grid**, not an HTML `<table>` with `<tr>` rows.

The active identity/upload logic uses:

- Rows: `div[role='row']`.
- Cells: `[role='gridcell'][columnindex]`.
- Applicant column: currently `5`.
- File serial column: currently `6`.
- UR column: currently `2`, with an element whose handler starts `ur(`.
- UR modal content: iframe named **`pmbwidget`**.
- Actual file controls: `input[type='file']`, with an `uploadFile(...)` change handler.
- Save control: **`#btnSave`**, historically a JavaScript-bound `<div>`, not a normal submit button.

Only the MIS column is dynamically resolved by its header/metadata. The other column numbers remain assumptions that must be reviewed if the bank changes/reorders columns.

Bank lookup first checks the currently rendered rows, then uses `#file_serial_no` and `#grid_search` to filter for the exact authorized numeric suffix if needed. This is implemented in [agent/city_navigation.py](agent/city_navigation.py) and shared by discovery and upload. The filter was exercised on a live authorized file. There is still no general all-page/virtualized queue crawler: if the filtered target is missing or ambiguous, stop rather than choosing a neighboring file.

### Verify

The UI uses React/Ant Design. Important assumptions include:

- A text email input and password input on login; the script waits briefly for event hydration before filling.
- A login redirect to `/dashboard`.
- A Reports search input with a `Search files` placeholder and a Search button.
- Result data in table rows.
- A `file-text` icon button as the Update Topsheet action.
- A modal/dialog containing sidebar text `Trip <id>` and content heading `Trip #<id>`.
- Attachment card labels and checkboxes discoverable through image-card ancestors.
- A button labelled `Download Selected (1)`.
- Generated attachment headers containing the chosen category and trip ID.

Timing includes fixed waits and an extra passive wait for slow preparation search results. Search does not reliably prove all server results have settled just because a fixed interval elapsed. Native generation and headers can also change. Do not fix a timeout by removing identity/selection validation.

The current active search does not implement comprehensive date-range clearing, all-page searching, or a general date-filter strategy. Confirm the effective search scope if expected reports are absent; the old prototype behavior is not a guarantee about the active scripts.

### Upload request protection

After UR loads, the uploader suppresses Save clicks/form submissions, disables the Save control, and installs a routed request guard. It permits reads and one intended POST per file input to the expected `/cpv-agency/report_upload` endpoint, checking the multipart `agent_report` marker.

Unexpected routed writes are aborted. These protections are targeted safeguards against accidental actions in the known browser flow—not a formal guarantee against all possible portal side effects. The guard is installed after the initial UR load, and reads are allowed. Review the portal's behavior before adapting it to changed endpoints or UI controls.

No direct API integration is required to run the project. The upload endpoint is documented here to explain the guard, not as permission to bypass the UI/authorization workflow.

---

## 10. Failure handling and retry rules

### Before any upload attempt

If discovery or preparation fails, review the error and evidence. Resolve the actual cause—identity, scope, selector, missing attachment, PDF content, size, or network—and prepare a new reviewed package only when appropriate.

Some preparation failures leave valid earlier items in the manifest. That does **not** approve a partial upload. Inspect overall status and expected item set.

### After any upload attempt

**Stop and inspect the bank before retrying.** There is no transactional rollback, automatic resume, cleanup, or external idempotency key. An upload can have reached the server even if the response timed out.

1. Keep the original manifest and all screenshots.
2. Determine which fields show uploaded report links.
3. Where permitted, retrieve/check those files to reconcile the result.
4. Report accepted, unverified, rejected, and unattempted items separately.
5. Obtain explicit direction for any existing-document replacement/removal or recovery.

The script refuses any manifest whose `uploads` list is nonempty. Do not clear that list, create a fresh manifest to bypass the retry guard, or delete bank documents without authorization.

---

## 11. Troubleshooting reference

| Symptom | Likely cause / safe action |
|---|---|
| Browser executable missing | Install Chromium using the same virtual environment's Playwright command. |
| Import error for `pymupdf` | Confirm the environment and requirements installation. Do not install the unrelated `fitz` package as a substitute. |
| Headed browser cannot start | The uploader needs a desktop/display session. No general unattended-server deployment has been validated. |
| Bank access rejected/support ID shown | Stop; check bank-approved network access with the owner. Do not evade restrictions. |
| Missing credentials | All four values are required. Check environment variable presence privately and the legacy parser format without printing passwords. |
| Login form remains or times out | Check current login UI, credentials, hydration/loading, and any new MFA/CAPTCHA requirements. Do not loop login attempts. |
| Target not visible in MY Q | Current rendered-row limitation; inspect filters/page. Do not choose a neighboring file. |
| MIS check blocked | Check header/column metadata, rendered status text, and computed font color. Never convert a read failure into “blank.” |
| Multiple Verify reports match | Compare request/report dates and explicit trips with the operator. No first-row shortcut. |
| Source attachments/trips missing | Check identity, concern, report row, and modal. Inventory may list trips absent from the visible modal. |
| Generated PDF is report-only | Check exact attachment → trip → Download Selected sequence and selection persistence. Do not fall back to raw images. |
| PDF missing the applicant photo | Verify the native generated Applicant Sign output against the manual workflow. Header/page-count/hash checks cannot prove photo presence. |
| PDF has no extractable identity/header text | Current validation can reject scanned-only PDFs. Stop for a supervised design change; do not bypass identity checks. |
| PDF cannot fit below 1 MB | Review source quality/compression. Preserve required content/layout; report the blocker rather than dropping pages or overcompressing unreadably. |
| Existing uploaded report detected | Replacement is not authorized by default. Stop and ask the operator. DOC source links are different from Report links. |
| Unexpected write blocked | Inspect `blocked_requests` and the bank's current behavior. Do not broadly disable the guard. |
| Upload timeout/rejection after selection | It may already exist on the server. Reconcile before any retry. |
| Upload accepted but hash check false | Investigate retrieval status/content. Overall completion alone does not establish byte-level verification. |
| Documents disappear after reopening UR | Final Save was not performed. Distinguish stored uploaded files from persisted form associations; do not infer final submission. |

---

## 12. Known limits and safe extension points

The current implementation does not provide:

- A complete automatic batch download/upload runner.
- General queue pagination or virtualized-row discovery.
- Universal upload-label mapping or bank-statement/co-applicant/guarantor workflows.
- Automatic selection of the right duplicate/Re-CPV source report.
- Automatic verification of applicant photo presence, image completeness, or readable text inside scans.
- Automatic human approval.
- Resume, rollback, duplicate-upload reconciliation, or approved replacement of existing reports.
- Final Save/submission.
- A production deployment, scheduler, service supervisor, or CI test suite.

`test_identity.py` is a live smoke/inspection script, **not a conventional unit-test suite**. The repository currently has no configured pytest/CI harness or dependency lockfile.

Recommended engineering work, in order:

1. Add offline fixture/unit tests for MIS text/color classification and jqx column resolution without bank access.
2. Add manifest-schema/completeness validation so a partial/blocked package cannot be uploaded inadvertently.
3. Validate the corrected native downloads in a supervised, explicitly approved case, including applicant photo/stamp and standalone LOI extraction.
4. Validate all MIS decisions and approved-queue behavior against the current UI.
5. Replace fragile sleeps with measured UI/network readiness while retaining identity/selection guards.
6. Implement authorized-file search/pagination and stronger column resolution.
7. Add explicit, reviewed mapping support for additional document categories.
8. Design reconciliation/idempotency and retention controls before unattended operation.

Do not treat this list as authorization for live uploads or existing-document replacement.

---

## 13. Security, privacy, and handover handling

This project handles bank/customer records, signatures, photographs, financial declarations, and login credentials.

- Keep original downloads, scripts, and generated outputs separated. Download directories are created as fresh isolated subdirectories; do not execute code from them or use them as interpreter working directories.
- Keep processing/compression local. Do not upload customer PDFs to external compression/OCR/debugging websites.
- Keep `creds.md`, `.venv/`, `runs/`, `artifacts/`, screenshots, and any future browser storage/trace files out of version control and public/shared repositories.
- The present directory is not initialized as a Git repository. If adding version control, establish ignore rules **before** the first add/commit and inspect what will be included.
- Screenshots, manifests, HTML/handler evidence, error messages, and private queue files can contain identifiers or unrelated visible customers. They are not automatically fully redacted. Review/redact before sharing externally.
- Do not assume every directory/file is encrypted or that creation modes fully constrain inherited permissions. Use approved storage/access controls and a bank/customer-data retention policy.
- Do not delete historical evidence or bank uploads as “cleanup” without the authorized retention/recovery decision.
- Share this technical guide and sanitized source separately from credential/customer-artifact handover.

---

## 14. Completion report and next-engineer checklist

For each authorized run, report:

- Full bank serial and confirmed Verify file/application reference.
- MIS outcome and any skipped file.
- Requested bank label → concern/trip/category → final filename, page count, and exact byte size.
- Whether all required content was visually reviewed, including the applicant photo when applicable.
- Each upload's visible acceptance and whether server content hash verification succeeded.
- Any rejected, unverified, skipped, or unattempted item.
- **Save not clicked; no final submission**, unless a separate future authorized workflow explicitly establishes otherwise.

Before taking over operationally:

- [ ] Read this guide and the original task requirements.
- [ ] Obtain private credentials and approved-network access.
- [ ] Install an isolated environment and Chromium.
- [ ] Understand that file selection is a live upload.
- [ ] Use only operator-approved target identities/queue entries.
- [ ] Validate the new MIS/native-download behavior under supervision before relying on it.
- [ ] Confirm the exact source report/trips and case-specific mappings.
- [ ] Review every final PDF and record approval for the exact files.
- [ ] Obtain explicit live-upload authorization.
- [ ] Inspect per-item upload evidence rather than only terminal success.
- [ ] Leave Save untouched and retain the evidence according to policy.

For a shorter command-oriented entry point, see [agent/README.md](agent/README.md). For the original business task, see [verify-citybank-upload-agent-prompt.md](verify-citybank-upload-agent-prompt.md).
