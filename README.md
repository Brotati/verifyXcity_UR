# Verify → City Bank document-transfer tools

Supervised Python/Playwright scripts for preparing verification PDFs from Barikoi Verify and uploading them to the correct City Bank CityFast UR fields.

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

Seven synthetic offline scenarios passed on 11 November 2026. A live Verify test
also exposed report-only native downloads despite selected attachments; that
source-side issue currently blocks the tested customer document package. These
results do not establish real bank acceptance or production readiness.

## Before running anything

- **Selecting a UR file causes a real upload. Not clicking Save is not a dry run.**
- Never click Save on either portal in the current workflow.
- Work only on explicitly authorized files from a bank-approved network.
- Skip green “Received (Full)” MIS files; unclear statuses require review.
- The native-download test is currently blocked by missing generated attachment pages. The MIS checker passed its local green/full fixture, but still needs live validation. This is not a production-verified unattended system.
- Do not commit or distribute credentials, customer PDFs, screenshots, run artifacts, or browser/session data.

The original operational requirements are in [verify-citybank-upload-agent-prompt.md](verify-citybank-upload-agent-prompt.md).
# verifyXcity_UR
