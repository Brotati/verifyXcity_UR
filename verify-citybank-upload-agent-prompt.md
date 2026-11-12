# Verify → City Bank: global operating and mapping rules

Updated: **12 November 2026**, following operator instructions and the Verify developers' confirmed download procedure.

These rules apply to **every authorized applicant/file**, not one historical case. The available City Bank fields and Verify attachments can vary per file. This document defines the required behavior; it does not establish that all of it is already implemented or tested.

## 1. Scope, portals, and permissions

Transfer complete verification documents from Verify to the correct City Bank CityFast UR fields.

- City Bank: https://cityfastagent.citybankplc.com/
- Verify: https://verify.bmapsbd.com/reports
- Runtime base origins are configured through the root `.env` / process environment.
- Use a City Bank-approved IP/network for bank access. On rejection, stop and report the displayed message/support ID; do not evade the restriction.
- Work only on operator-authorized files. Preserve leading zeros in identifiers.
- Never include passwords, session tokens, or cookies in logs, screenshots, reports, or source control.
- Exploration-only mode means **no Verify Save, no uploads, and no final submission**.
- Authorized processing requires **Verify Save to persist the intended attachment selection before native PDF generation**. This is a real source-side write, not read-only exploration.
- **City Bank Save/final submission remains prohibited in this workflow.** Selecting a UR file already causes an immediate upload; leaving Save unclicked does not undo that upload.

## 2. Bank identity and completion gate

1. Log into City Bank and click MY Q once.
2. Locate the authorized file by full serial or exact numeric suffix, using the serial filter if necessary.
3. Record the full File Serial No, numeric suffix, applicant name, and request context.
4. Read **MIS Report Receive Status**, using the status text/font rather than a row's selection background:
   - **Received (Full), green font:** skip the file without opening UR or preparing/downloading its source documents. Continue only to another explicitly authorized queue entry.
   - **Blank status:** eligible for further checks, not automatic permission to upload.
   - Other, ambiguous, or unreadable status: stop that file for review.
5. For an eligible file, open its UR action and read every requested upload label, report field, existing-document indicator, and file restriction.
6. Keep DOC/source links separate from existing uploaded Report documents. Do not replace an existing report without explicit instruction.
7. Recheck completion/identity before any later upload; do not trust an old pending result.

## 3. Match the Verify application and report

- Search by the bank identifier and applicant name.
- Verify is the source of truth for documents.
- A search result can match a trip ID or another identifier substring. Do not select the first result automatically.
- Confirm file identity, applicant, City Bank organization, concern/person, and relevant trip IDs.
- If multiple original/Re-CPV report rows exist, compare bank request context and source dates. Resolve the intended report before downloading or saving a selection.
- Missing, inconsistent, or unresolved identity means stop and report, not guess.
- Use applicant documents unless the bank explicitly requests a co-applicant or guarantor.

## 4. Global mapping rules

| City Bank requested item | Verify source and selection rule |
|---|---|
| **Business Address with Photo** | Relevant applicant Business/Office trip report with business-premises image attachments selected. A business visit may be labelled Office Visit in Verify; inspect its actual context. |
| **Residence Address / Image of Residence** | Applicant House trip report with residence image attachments selected. |
| **Image of Office** | Relevant Office trip report with office images selected; exclude unrelated LOI, payslip, signature, or other document attachments. |
| **Office Address / Passport Size Photo / Signature** | Relevant Office trip and Applicant Sign/photo-related attachment(s), using Verify's native generated PDF. Confirm required applicant photo, signature, and stamps are present. A raw attachment image may omit generated content. |
| **Self Declaration / Self Income Declaration** | OCR/read the actual contents of Verify LOI-category candidates and select the document that is genuinely a self/income declaration. Keep the requested document standalone. Do not map every LOI-category item to this field. |
| **Salary Certificate / Salary Certificate (Original)** | OCR/read Verify LOI-category candidates and select the actual employer salary certificate. Keep it standalone; do not substitute an unrelated declaration, payslip, or entire Office report. |
| **Pay Slip** | OCR/read Verify LOI-category candidates to identify the actual payslip. It can be labelled LOI in Verify. The label alone is neither proof nor a blocker when content can resolve the mapping. |
| **Bank Statement** | Relevant applicant Bank Verification trip and the actual bank-statement attachments. Match bank/account/person when the destination is bank-specific. |
| **Authorization / Withdrawal Letter** | Search the relevant **Bank Verification trip's attachments**, then OCR/read their contents to identify the actual authorization/withdrawal letter. Do not substitute a statement merely because it is nearby or share a document across different banks/accounts. |

### Important: Verify LOI is a fixed category, not a document classification

In Verify, **LOI is the fixed attachment-category label** used for candidates that can actually be salary certificates, self declarations, payslips, or other documents. It does not mean every attachment has the same content or belongs in a City Bank LOI/declaration field.

**The actual document content is the deciding evidence for these mappings.** Use the exact City Bank field plus the document's title/body, source trip, applicant, employer/bank, relevant period/date, and other case context. There is no universal rule that the first LOI is a declaration or the second is a payslip.

## 5. OCR / image-reading requirements

**Current junior-runner mode:** OCR is disabled by operator choice. The junior
must read the visible images/PDFs and explicitly assign ambiguous documents.
The content/identity checks below still apply; no automated OCR classification
is claimed. If human review cannot resolve a mapping, hold that file.

Before choosing document attachments for content-dependent fields:

1. Collect candidates from the correct authorized file, concern, and trip.
2. OCR/read the original readable image/PDF pages, not only tiny UI thumbnails. Keep processing local unless another approved data-handling arrangement exists.
3. Inspect the title and body. Classification examples:
   - Self/income declaration: the applicant declares their personal income/circumstances.
   - Salary certificate: an employer certifies employment/salary.
   - Payslip: payroll period and earnings/deductions/net-pay information.
   - Bank statement: account transactions/balances for a bank/account/period.
   - Authorization/withdrawal letter: permission to obtain/withdraw a statement or carry out the stated action for the relevant bank/account/person.
4. Use OCR plus source/application context. A label, filename, keyword, OCR score, or handwritten name alone is not enough to prove the mapping.
5. Group pages only when the evidence shows they belong to the same complete document; multiple LOI attachments can be pages of one document or different candidates.
6. Record the selected source attachment IDs and the classification rationale in private run evidence. Do not expose financial/account text in public logs or repository files.
7. Visually review poor scans, handwriting, bilingual text, low-confidence classifications, conflicting identity, duplicate candidates, or unclear page grouping. Ask the operator if the ambiguity remains unresolved.

Multiple LOI candidates are **not** a reason to pick arbitrarily or always stop without inspection: first attempt content-based classification. If it still cannot distinguish the required documents safely, stop that item and report the uncertainty.

## 6. Developer-confirmed native Verify download procedure

For each requested document/report group in an authorized processing run:

1. Open **Update Topsheet for Trips** from the confirmed report row.
2. Select/open the desired trip and select its left-side trip checkbox. Clear unrelated trip selections for this download.
3. Choose only the attachments needed for the current bank field, using the content-based mapping above where necessary.
4. Confirm file, concern, trip, attachment selection, and the selected-trip count before saving.
5. Click **Save in Verify**. The developers confirmed that attachment selection must be saved; otherwise a download can contain only the report/topsheet, or reflect an earlier saved selection.
6. Wait for visible save success and verify that the intended selection persisted. Do not blindly retry an uncertain Save.
7. Click **Download Selected (1)** for a single selected trip, or the appropriate confirmed count if a future explicitly supported workflow intentionally needs more than one trip.
8. Inspect the generated PDF for correct identity, required report/attachment pages, applicant photo/signature/stamps where applicable, orientation, and completeness.

### Save boundaries

- **Verify Save is required for the attachment selection during authorized processing.** This supersedes the previous blanket instruction never to click Verify Save.
- Do not edit report answers, remarks, bank details, verification results, or statuses. Saving the selection must not be used as permission to change those fields.
- The Save form can carry other current report values. Implementation must snapshot/check them before saving and verify that no unrelated values changed. Stop if values are stale, unexpectedly dirty, or concurrently changed.
- Discovery/read-only inspection must not Save. No new target file is authorized merely by a global workflow change.
- **City Bank Save is a different action and remains forbidden.** Its guard must not be removed when enabling the required Verify Save.

The earlier report-only test results were obtained without this required Save step. They do **not**, by themselves, establish a backend defect. Do not require a new backend API merely on the basis of those historical tests.

## 7. Prepare the final PDFs

- Use the native Verify-generated content. Do not recreate missing generated photos/stamps by pasting raw images into a substitute form.
- Keep LOI-category documents standalone where the bank requests a declaration, salary certificate, or payslip. Retain all relevant pages of the correctly classified document and exclude unrelated Office report pages from that standalone output.
- Preserve the full original download as source evidence before any extraction/compression.
- Each upload PDF must be **strictly below 1,000,000 bytes** under the tool's conservative limit.
- Compress locally only. Do not use third-party compression websites.
- Verify readability, page count/completeness, orientation, identity, and required photos/signatures/stamps after compression. If required content cannot remain readable under the limit, report the blocker.
- Use filenames containing the file identifier, applicant/concern, document category, and trip ID where applicable.
- Record size/hash and require visual review of the exact final PDF before upload. Do not mark an incomplete or ambiguously mapped PDF as approved.

## 8. Bank upload and no-final-submission rule

- Upload only when execution is explicitly authorized for the target file and document fields.
- Recheck file identity, MIS status, exact UR destinations, and existing reports.
- Place each validated PDF in its exact field. **File selection causes a real server upload.**
- Do not click **City Bank Save**, Submit, or any final-submission control.
- Do not replace/delete existing uploaded documents without separate explicit direction.
- If any required document is missing, mapping remains uncertain, or preparation is partial, report it and obtain direction before a partial live upload.
- Require visible upload acceptance; retrieve/hash-check the uploaded file where supported. Do not infer success from file selection alone.
- On an upload failure/timeout, inspect whether it already reached the bank before considering any retry. No blind retries or silent rollback.

## 9. Report results

Include:

- Full bank serial, numeric identifier, applicant, and matched Verify report/application reference.
- MIS status and any skipped authorized file.
- Each bank label → source concern/trip/attachment IDs → OCR/content classification and selected document → final filename, pages, bytes, and hash.
- Whether Verify Save succeeded for the intended selection, and whether unrelated report values remained unchanged.
- Download completeness and visual-review outcome, including generated applicant photos when required.
- Upload acceptance and retrieval/hash outcome for each bank field.
- Explicit **City Bank Save not clicked / no final submission** status.
- Every blocked, skipped, ambiguous, rejected, or unattempted item and any required operator decision.

Keep evidence private and never mix documents between files, people, periods, banks, or accounts.

## 10. Implementation status / next work

These are the latest **global requirements**. The operator has temporarily skipped OCR and chosen junior-guided document reading/mapping instead. Root `daily_runner.py` implements that supervised path and controlled Verify selection Save, with a mandatory offline-validation gate and no bank final Save. The new runner has not been executed/validated in the assistant session because tool execution was blocked; run its offline tests and supervise one-file live validation before trusting it. Older `agent/` preparation CLIs still contain earlier no-Verify-Save guards/fixed mappings and are not the new daily workflow.

Do not simply remove every Save guard. Keep read-only inspection and City Bank protections intact; enable only the deliberate Verify selection-save operation for an authorized execution target.
