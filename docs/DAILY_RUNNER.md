# Junior runbook: one-file daily runner

## What to hand over

The runnable implementation is **[daily_runner.py](../daily_runner.py)** at the project root. It is self-contained: it does not import `agent/` or another project Python file, and it does not require access to an AI assistant, model API, OCR service, or MCP server.

The junior needs:

1. `daily_runner.py`.
2. A privately supplied `.env` beside it, using the keys in [.env.example](../.env.example).
3. Python 3.10+, the dependencies below, Chromium, a visible desktop browser session, and bank-approved network access.
4. Authority to work on the selected Request Date and to make the prompted mapping/review decisions.

**Validation status:** the file and offline tests were implemented, but this assistant session could not execute them: shell execution and editor diagnostics were denied by the session's unavailable Auto-mode safety check. No live daily batch was run. The new runner is **for supervised validation, not an asserted production-ready unattended system**.

Prepare/run modes are locked until the junior successfully runs the embedded offline tests for the exact script and installed dependency versions. A passing local fixture still does not prove the live bank/date-widget/Verify contract; first live validation must be limited and supervised.

## 1. One-time setup

From the project root, use the project's virtual environment if it already exists:

```bash
python3 -m venv agent/.venv
./agent/.venv/bin/python -m pip install -r agent/requirements.txt
./agent/.venv/bin/python -m playwright install chromium
```

If handing over only the standalone file outside this repository:

```bash
python -m venv .venv
# macOS/Linux:
./.venv/bin/python -m pip install "playwright>=1.40" "PyMuPDF>=1.28.2" "python-dotenv>=1.0.1" "tzdata>=2024.1"
./.venv/bin/python -m playwright install chromium
```

On Windows use `.venv\Scripts\python.exe` in place of the environment's `bin/python` path. Use a terminal and visible desktop; this live runner is not configured as a headless cron service. Linux may additionally require the administrator-approved Chromium system packages.

Do not silently upgrade a working environment during live processing. After changing the runner or dependency versions, rerun its offline tests.

### Private configuration

The root `.env` is loaded automatically for live modes, independent of the shell's working directory. Existing process environment values take precedence; password interpolation is disabled.

Required keys: `VERIFY_EMAIL`, `VERIFY_PASS`, `CITY_ID`, `CITY_PASS`.

Optional origins: `VERIFY_BASE`, `CITY_BASE`. Origins must be HTTPS without `/reports`, `/login`, embedded credentials or query strings. Standard production origins are already defaults in the script.

`creds.md` is not a runtime fallback for the standalone runner. Use `.env`. Never paste passwords into CLI arguments, tickets, terminal output, or the Python file. The offline-test mode does not load `.env` or use real credentials.

## 2. Run offline tests first

```bash
./agent/.venv/bin/python daily_runner.py --offline-test
```

Or use `.venv/bin/python` if the file was handed over standalone.

The embedded tests create synthetic bank/source pages and synthetic PDFs. Browser traffic is intercepted and external origins are blocked; APIRequestContext retrievals are replaced with an in-memory reader. No real portal credentials are loaded. The test fixture's binary-safe transfer field is not part of the real bank contract.

The suite covers queue pages/date checks, MIS handling, exact identities, native selection Save/download, unrelated source-data changes, manual LOI mapping/PDF cards, standalone-page selection, PDF compression, size/hash/review gates, existing-document/rejection behavior, checkpoints, and blocked bank Save.

**All tests must finish successfully, with no errors/skips.** Successful results produce a private `runs/daily/runner_selftest.json` receipt bound to this script's SHA-256 and dependency/runtime fingerprint. Failed tests leave write modes locked. Do not edit the receipt or script to bypass the gate. Keep failures and ask the maintainer to resolve them; do not attempt a live write run.

## 3. Start with inspection

The single daily command is:

```bash
./agent/.venv/bin/python daily_runner.py
```

The startup menu offers:

| Choice | Mode | What it does |
|---|---|---|
| Enter / 1 | Inspect | Logs into the bank, discovers the selected day's requests and reads eligible UR fields. No Verify Save/download or bank upload. |
| 2 | Prepare | Also matches Verify, asks for mapping, Saves selected attachments in Verify, downloads/prepares PDFs and asks for visual review. No bank uploads. |
| 3 | Run | Preparation plus per-file-approved real bank uploads; **never City Bank Save**. |

Explicit inspection command:

```bash
./agent/.venv/bin/python daily_runner.py --mode inspect
```

Today means **City Bank Request Date in Asia/Dhaka**. The scope/date is printed and must be confirmed. This is a snapshot of files discovered at startup, not a background watcher for new arrivals.

The runner sets both Request Date endpoints and enumerates all filtered jqx pages. If it cannot recognize the date widget safely, it asks the junior to select the date through the visible bank calendar; it then validates the displayed values. It does not guess a date format or silently process older files.

Every returned row must match the requested date and have a serial/name/RRN identity. Changed totals, repeated pages, unreadable dates or incomplete counts block processing. Compare the discovery total/date with the visible bank queue before authorizing preparation.

### Completion handling

- Green **Received (Full)** text: skipped.
- Blank MIS: eligible for further checks, not automatically authorized to upload.
- Other/unreadable status: held for review.
- An earlier upload attempt, interrupted operation or uncertain source Save in this runner's checkpoint: no automatic retry.

Additional-person/unrecognized UR input layouts are held rather than mixing applicant and co-applicant/guarantor documents. Existing uploaded Report documents are never replaced automatically. DOC source links are not the same as uploaded Report links.

## 4. First supervised preparation and upload

Only after offline tests pass and inspection is confirmed:

```bash
# One eligible file only; real Verify selection Saves, no bank uploads:
./agent/.venv/bin/python daily_runner.py --mode prepare --limit 1

# One eligible file, with mapping, PDF review and real-upload approval prompts:
./agent/.venv/bin/python daily_runner.py --mode run --limit 1
```

`--limit` counts eligible processed files after skips, not every scanned row. Without it, the menu/run processes the discovered eligible requests sequentially.

For an explicitly authorized different date:

```bash
./agent/.venv/bin/python daily_runner.py --mode inspect --date YYYY-MM-DD
```

The runner does not execute automatically just because it was launched: date scope, source preparation and each final upload require explicit confirmations. Enter/default declines consent. `s` at mapping/page-selection prompts holds the file; `q` or Ctrl+C stops the day. Keep the browser open and do not edit Verify answers, remarks, verification state or bank details while reviewing candidates.

### The junior's mapping work (OCR is intentionally skipped)

- Clear Business/Office/House/Applicant Sign attachment labels receive a proposal, which still needs confirmation.
- LOI is a fixed source bucket, **not** a reliable document classification. For Self Declaration, Salary Certificate or Pay Slip, read the actual document and enter the correct attachment number(s). A single LOI candidate is not automatically assigned by label alone.
- Authorization/withdrawal letters are chosen from Bank Verification attachments. Read the document and confirm the bank/account/person; do not substitute a statement.
- When several source reports/trips/banks match, choose the correct version explicitly using request/report context. Never choose the first merely to continue.
- `p NUMBER` at the attachment prompt opens the visible image/PDF preview. Close the preview and return to the trip before continuing in the terminal. The junior can also inspect trips in the visible browser.
- Multiple attachment numbers can represent one multi-page document only after the junior confirms that grouping.
- Unknown fields require an explicit REPORT versus DOCUMENT decision. Unresolved mapping holds the whole file; the runner does not perform automatic partial uploads.

### Verify Save behavior

After the complete field plan is confirmed, each group uses:

**Open/select trip → select intended attachments → controlled Verify Save → fresh persisted-selection verification → Download Selected.**

The source Save guard checks the application/trip/attachment IDs and protected answer/remark/verification/bank values against server state. Non-attachment form values are checked before and after Save. Unknown API/state shapes block rather than guess. If substantive data changes or Save persistence cannot be confirmed, stop for investigation; do not click Save again blindly or auto-revert values.

This is a real source write. Inspect mode does not permit it. City Bank Save is independent and always blocked.

### PDF review

The original native generated PDF is retained. Missing attachment pages/identity evidence blocks the file; raw images are never substituted to fabricate a form.

For standalone documents, the junior explicitly chooses the complete attachment page range from the native generated PDF, excluding report sheets/unrelated pages. The original is retained.

Every final PDF must be below **1,000,000 bytes**, renderable and page-complete, with relevant identity text preserved. Compression retains native layout/text and protects larger shared image uses. PDF pages and previews must still be visually checked for readable details, correct orientation, all attachments and required applicant photo/signature/stamp.

Only an explicit YES after reviewing the exact final file sets its review flag. A changed file hash invalidates approval. No size/hash check proves visual correctness.

### Upload behavior

The runner rechecks current bank identity, Request Date, MIS, destination input IDs/labels and existing Report documents before selecting any file. Duplicate labels can be distinguished by their stable input IDs; ambiguous identity is never inferred.

Each attempt is checkpointed before file selection. File selection sends a real upload. Visible acceptance/link checks are followed by a bank-origin GET/hash check where supported. The status distinguishes verified uploads from accepted-but-unverified uploads.

**City Bank Save, Submit, removal and replacement are not performed.** An uploaded file can remain on the bank server even without Save. Uploaded is not equivalent to saved-form persistence, Received Full or final submission.

## 5. Terminal updates and evidence

Typical stages include:

```text
DISCOVERY: page 1/3, ... requests collected
FILE: [2/15] <full serial> | <applicant>
SKIPPED: MIS Received (Full), green
UR: <exact requested fields>
PREPARE: 1/4 <field> from trip <id>
UPLOAD: <field> accepted; hash verified=True/False
DONE: UPLOADED_NO_BANK_SAVE
NEEDS_REVIEW / SOURCE_SAVE_NEEDS_REVIEW / UNKNOWN_UPLOAD / FAILED
SUMMARY: <summary.csv> ; <checkpoint.json>
```

Private outputs:

```text
runs/daily/
├── runner_selftest.json
└── YYYY-MM-DD/
    ├── terminal.log
    ├── discovery.json
    ├── checkpoint.json
    ├── summary.json
    ├── summary.csv
    └── <request-key>/<run-time>/
        ├── manifest.json
        ├── downloads/       # isolated native originals / intermediate candidates
        ├── previews/
        ├── final/           # only size/content-validated candidates
        └── bank_uploaded_NO_SAVE.png
```

Request checkpoints use full serial plus bank request reference, not just applicant name. Existing receipt/checkpoint files are never a reason to assume real bank completion; inspect actual statuses and bank evidence.

## 6. Failure/restart rules

1. After any upload attempt or uncertain source Save, **stop that file and reconcile manually**. No automatic retries, resume-upload, deletion or rollback are implemented.
2. A rerun skips such requests instead of uploading duplicates, even if MIS is still blank because Bank Save was not performed.
3. Never delete/edit a checkpoint, reset attempts or create a new request identity just to force a retry.
4. If a request is only mapped/inspected and no uncertain writes exist, a new authorized run can prepare it again. Existing prior artifacts remain under the earlier run directory.
5. Source/backend/UI contract changes, wrong date scope, invalid page totals and unexpected write-guard violations stop the day rather than silently bypassing checks.
6. Session/MFA/CAPTCHA behavior is not generalized. Unexpected login behavior requires operator intervention; do not loop login attempts.
7. Ctrl+C closes the browser, but it is not rollback. Inspect the checkpoint before restarting.

## Limits and rollout

- This remains a **supervised** workflow. It will pause for mapping, date-widget fallback and PDF review; it is not an unattended cron job.
- No OCR/vision classification is implemented. Human review replaces those content decisions.
- No bank final Save/submission, report replacement, automatic retry, account reconciliation or broad multi-person support is added.
- The source API/state/Save payload and bank grid/search contracts are checked conservatively. A changed contract may block a file until the maintainer adapts and retests it.
- The embedded browser fixtures and self-test receipt cannot prove the live sites behave identically. First real use requires a supervised one-file validation, separately authorized.
- Tests, syntax checks and live operation were **not executed in the current assistant session** due tool permissions. Do not represent this new script as live-verified; run its local tests first and report any failure to the maintainer.
- Existing `agent/` scripts remain historical/diagnostic tools; the junior's entry point is this root-level runner. No Git commit or push is part of this change.

Keep the `.env`, run directories, original PDFs, screenshots, manifests and logs private and out of version control. If handing the single file over outside this repository, provide equivalent ignore rules and approved storage/retention controls.
