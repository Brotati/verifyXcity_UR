# Verify → City Bank Document Transfer Automation

Supervised Python/Playwright automation for preparing CPV verification PDFs from **Barikoi Verify** and safely uploading them to **City Bank CityFast UR** portal.

---

## 🛠️ One-Time Setup on a New PC (Windows PowerShell)

Requirements: **Python 3.10+** and **Git** installed on Windows.

### 1. Clone & Navigate to Repository
```powershell
git clone <REPO_URL>
cd verifyXcity_UR
git checkout windows-fixes-and-audit
```

### 2. Create Virtual Environment & Install Dependencies
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install playwright PyMuPDF python-dotenv tzdata
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 3. Configure Credentials (`.env`)
Create a `.env` file in the project root (reference `.env.example`) and set private portal credentials:
```env
VERIFY_BASE=https://verify.bmapsbd.com
CITY_BASE=https://cityfastagent.citybankplc.com

VERIFY_EMAIL=your_verify_email
VERIFY_PASS=your_verify_password
CITY_ID=your_city_bank_user_id
CITY_PASS=your_city_bank_password
```

---

## 🚀 Daily Pipeline Usage

All daily operations are handled by the single, self-contained production runner: **`daily_runner.py`**.

```powershell
# Interactive startup menu (Enter = Inspect mode)
.\.venv\Scripts\python.exe daily_runner.py

# Step 1: Read-only inspection of queue and UR field requirements
.\.venv\Scripts\python.exe daily_runner.py --mode inspect --date 2026-11-12

# Step 2: Prepare PDFs (Verify download, size optimization, visual review, Zero Bank Upload)
.\.venv\Scripts\python.exe daily_runner.py --mode prepare --limit 1 --date 2026-11-12

# Step 3: Supervised upload of approved packages (Zero Bank Save)
.\.venv\Scripts\python.exe daily_runner.py --mode run --limit 1 --date 2026-11-12
```

---

## 📁 Repository Structure

| File / Folder | Purpose |
| :--- | :--- |
| **`daily_runner.py`** | **Core standalone production pipeline.** Discovers queue, matches trips/attachments, downloads native PDFs, performs size optimization, and executes guarded uploads. |
| **`CODE_CHANGES_AUDIT.md`** | Comprehensive audit report detailing all Windows adaptations, bug fixes, and safety invariants. |
| **`docs/`** | Official engineering documentation (`DAILY_RUNNER.md`, `HYBRID_TESTING.md`, `TECHNICAL_HANDOVER.md`). |
| **`runs/`** | Clean local output directory storing state (`checkpoint.json`), audit report (`summary.csv`), and final reviewed PDFs (ignored in Git). |

---

## 🔒 Bank Safety Invariants

1. **City Bank Save Strictly Forbidden:** Never click `#btnSave` or submit files on City Bank portal. Automated guards enforce this boundary.
2. **Zero Empty Document Submissions:** Files without field photos are defensively held under `NEEDS_REVIEW` to prevent blank document uploads.
3. **Supervised Inspection:** Always inspect generated PDFs before authorizing upload.

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
