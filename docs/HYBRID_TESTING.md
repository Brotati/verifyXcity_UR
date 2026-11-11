# Hybrid verification and offline bank-side testing

## Scope and result

On 11 November 2026, an operator-authorized case was inspected on live Verify.
Both exact file-number and applicant-name searches returned one matching City
Bank source report. Its trips/attachments were inventoried without saving data.
No real City Bank portal was accessed.

**The source document-preparation test did not pass.** All four unambiguous native
category downloads produced report-only PDFs, and the shared preparation guard
correctly rejected them. Four LOI-labelled attachments were also present; the
runner skipped that ambiguous category instead of selecting the first one.

Separately, **seven offline integration scenarios passed**, using clearly labelled
synthetic PDFs, a simulated bank page, and the existing `upload_no_save.main`
workflow. These results establish local test behavior, not real bank acceptance
or a complete transfer of the operator's source documents.

Case-specific names, files, downloaded PDFs, screenshots, and captured diagnostic
bundles are in private ignored `runs/` directories, not in this document.

## Commands

From the project root, using its installed virtual environment:

```bash
# OFFLINE: synthetic PDFs and intercepted local bank pages only.
./agent/.venv/bin/python agent/test_mock_bank.py

# LIVE VERIFY ONLY: inspect a specifically authorized file/applicant.
./agent/.venv/bin/python agent/hybrid_verify_test.py \
  '<EXACT-VERIFY-FILE-NUMBER>' '<EXACT-APPLICANT-NAME>'

# LIVE VERIFY ONLY: also attempt unambiguous native document-group downloads.
# This does not contact or upload to the real bank.
./agent/.venv/bin/python agent/hybrid_verify_test.py \
  '<EXACT-VERIFY-FILE-NUMBER>' '<EXACT-APPLICANT-NAME>' --prepare
```

Replace placeholders with operator-authorized values. Live Verify inspection
uses private `VERIFY_EMAIL`/`VERIFY_PASS` configuration. The offline test replaces
the bank base URL and credential loader **in memory**; it does not edit `.env`.

The hybrid runner does not read the real bank's UR labels or MIS status. Its
possible destination labels are simulated assumptions, not verified mappings for
the case. Do not use its partial manifest with the live uploader.

## Network isolation

### Live source stage

- Uses the configured Verify site and its normal source API/document assets.
- Does not invoke `city_check`, `inspect_documents.main`, the main preparation
  entry point, or the live bank uploader. Those normal workflows perform bank
  preflight checks and are intentionally unsuitable for this hybrid mode.
- Rejects a Verify base URL pointing to the configured bank host.
- Blocks browser requests to the configured bank hostname and `citybankplc.com`
  subdomains; Chromium host-resolution rules also prevent bank DNS resolution.
- Disables service workers in the browser context.
- Suppresses Verify Save clicks and never calls report-update actions.
- Records requested source hostnames and blocked-bank-request counts without
  logging authorization headers, cookies, or passwords.

### Offline bank stage

- Uses `http://mock-bank.test` as a simulated origin, with no real server.
- Intercepts every browser request and fulfills it in memory; unexpected origins
  are aborted. Chromium DNS resolution is disabled as an additional safeguard.
- Replaces `APIRequestContext.get` with an in-memory reader. Browser routes alone
  do not intercept Playwright APIRequestContext requests, so this second control
  is essential to prevent external retrievals.
- Uses fake bank credentials and synthetic document bytes only.
- Lets the production upload guard run through a route adapter whose
  `continue_()` falls back to the fixture instead of reaching the network.
- Uses a fixture-only base64 copy of the selected File to avoid Chromium routing
  limitations with binary multipart bodies. It is not part of the bank contract
  or production upload code. Thus this test does not prove real multipart
  transport/server behavior.

The actual bank URLs, credentials, and existing uploaded customer documents are
not changed by these tests.

## Offline scenarios

| Scenario | Expected and observed outcome |
|---|---|
| Success | Four synthetic files accepted by the mock; visible links and retrieved hashes match. |
| Received (Full), green | Completed file skipped before UR; no mock uploads. |
| Existing report | Replacement blocked before file selection. |
| Server rejection | First rejected upload stops the run; no automatic retry/remaining uploads. |
| Oversized document | A synthetic file of exactly 1,000,000 bytes is rejected before browser upload. |
| Changed content/hash | A file changed after manifest creation is rejected before browser upload. |
| Not visually reviewed | An unreviewed manifest item is rejected before browser upload. |

Every scenario asserts zero external-origin requests and zero Save requests.
The completed-file scenario also asserts that UR was never opened. These are
script-based integration checks; invoke the command above explicitly. The file
name alone does not mean a pytest-discovered test suite exists.

## Verify download finding

The captured current frontend's native download action dispatches a report
request with application identity, file number, trip IDs, and authentication. Its
GET URL contains `trip_ids[]`; the action does **not** pass the current attachment
checkbox selection. In the same frontend, attachment IDs are present in the
separate report-update/Save payload.

Observed behavior in the authorized case:

1. Correct attachment labels and one trip were selected.
2. The runner asserted that the expected checkboxes remained selected.
3. Download Selected (1) emitted one PDF download event.
4. The resulting PDF had only one report page, without the selected attachment
   pages. No later combined download arrived during the diagnostic wait.
5. The shared native-download validation rejected it rather than substituting
   raw images or locally rebuilding Verify's pages.

This is evidence that the current UI download path cannot be relied on to
include **unsaved** attachment selections. Backend handling of stored selections
has not been inspected; do not claim a particular backend implementation is
proven by frontend code alone.

**Do not click Save as a workaround.** The appropriate product fix is to support
transient attachment selection in read-only PDF generation and pass that
selection from the native download action, or confirm an existing supported
read-only generation path. Verify source-code/server changes are outside this
repository and were not performed by the test.

## Evidence and interpretation

- `runs/<serial>/hybrid_<timestamp>/result.json`: exact-match inventory, source
  trip metadata, source-only network audit, and preparation outcome.
- Its `manifest.json`: successful items, if any, and per-category blockers.
- `downloads/`: isolated original generated PDFs, including rejected report-only
  outputs retained for investigation.
- `shots/`: source row, attachment panels, and selection/failure evidence.
- `runs/<serial>/native_diagnostic_<timestamp>/`: native download events and
  captured frontend bundles for static inspection only. Never run downloaded
  JavaScript locally or publish bundles containing source configuration.
- `runs/offline_mock_tests/<timestamp>/test_results.json`: seven local scenario
  results, plus per-scenario synthetic manifests/screenshots.

A partial hybrid preparation can finish its inspection loop and exit normally
while recording blockers. Always inspect `status`, `blockers`, and item count;
process exit code alone is not a source-preparation pass.

No valid final PDF package was established for the tested customer case. No real
bank upload, bank login, final submission, or Verify Save was performed. The
source issue and LOI ambiguity must be resolved before claiming a successful
end-to-end transfer for that case.
