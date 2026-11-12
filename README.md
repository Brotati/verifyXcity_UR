# Verify → City Bank document-transfer tools

Supervised Python/Playwright scripts for preparing verification PDFs from Barikoi Verify and uploading them to the correct City Bank CityFast UR fields.

## Junior entry point: one self-contained Python file

Use **[daily_runner.py](daily_runner.py)**. It does not import `agent/` and needs
no AI/OCR access. The [junior runbook](docs/DAILY_RUNNER.md) covers one-time
installation, private `.env` setup, prompts, recovery and limitations.

```bash
# First: local synthetic tests; no .env or real portal access.
./agent/.venv/bin/python daily_runner.py --offline-test

# Then: startup menu; Enter defaults to bank inspection only.
./agent/.venv/bin/python daily_runner.py
```

The runner discovers today's **Request Date in Asia/Dhaka** across queue pages,
skips green/full files and checkpoints, and processes eligible files sequentially.
It asks the junior for ambiguous LOI/bank-document mappings and visual PDF review.
Prepare mode Saves selections in Verify; run mode additionally uploads approved
PDFs. **City Bank Save is always prohibited.**

**Validation warning:** implementation and embedded offline tests are provided,
but this session could not execute them because tool execution was blocked.
Prepare/run modes stay locked until this exact script/environment passes its
local offline suite. Supervised one-file live validation is still required; no
bulk live run was performed. Do not claim production readiness.

## Latest global workflow requirements — 12 November 2026

The authoritative [global operating rules](verify-citybank-upload-agent-prompt.md)
apply to every file, not one example applicant:

- OCR/read Verify's fixed **LOI** category to distinguish Self Declaration,
  Salary Certificate and Pay Slip by actual document content.
- OCR/read authorization/withdrawal letters in the relevant Bank Verification trip.
- For an authorized processing run: open the trip → choose attachments →
  **Save in Verify and confirm success** → Download Selected.
- Do not change Verify answers, remarks, bank details or verification status.
- **Never click City Bank Save/final submission.** Read-only exploration still
  must not Save on Verify either.

**Implementation distinction:** `daily_runner.py` implements controlled Verify
selection Save and junior-guided content mapping, pending execution/validation.
OCR is intentionally skipped. Older preparation helpers under `agent/` still
contain no-Verify-Save behavior/fixed mappings; do not use those legacy CLIs as
the new daily workflow.

## Taking over this project

Start with **[TECHNICAL_HANDOVER.md](TECHNICAL_HANDOVER.md)**. It covers:

- Environment setup, credentials, portal/network requirements, and module architecture.
- Exact CLI commands for identity checking, approved-file queue selection, document inventory, native downloads, PDF review/compression, and authorized uploads.
- MIS “Received (Full)” skipping, document mappings, manifest states, and evidence directories.
- Upload verification, failure recovery, selector maintenance, security, and known limitations.
- Which historical behavior was tested and which current changes remain untested.

For the shorter operating guide, see [agent/README.md](agent/README.md).

## Testing without the real bank

See [Hybrid and Offline Testing](docs/HYBRID_TESTING.md) for the live-Verify-only
runner and the isolated bank-side integration checks:

```bash
./agent/.venv/bin/python agent/test_mock_bank.py
```

Seven synthetic offline scenarios passed on 11 November 2026. Earlier live
Verify tests downloaded report-only PDFs without saving the selection. On
12 November the developers confirmed that Verify Save is required before
Download Selected. Those historical results do not establish a backend defect.
The new standalone save-then-download runner is implemented but not executed or
validated in this session; these historical tests do not establish its readiness.

## Before running anything

- **Selecting a UR file causes a real upload. Not clicking Save is not a dry run.**
- Never click **City Bank Save**. Verify Save is required only for an authorized processing run once its controlled implementation is ready; never Save during read-only exploration.
- Work only on explicitly authorized files from a bank-approved network.
- Skip green “Received (Full)” MIS files; unclear statuses require review.
- OCR is off; ambiguous mapping is manual. The new runner and its controlled Verify Save require offline and supervised live validation. Historical MIS fixtures are not proof of the new daily batch implementation. This is not an unattended production system.
- Do not commit or distribute credentials, customer PDFs, screenshots, run artifacts, or browser/session data.

The original operational requirements are in [verify-citybank-upload-agent-prompt.md](verify-citybank-upload-agent-prompt.md).
# verifyXcity_UR
