# Verify → City Bank Upload Agent Task

Run this task on a **City Bank-approved IP/network**. Supply credentials privately, outside this document.

## Agent task prompt

### Task

Transfer verification reports from Barikoi Verify to the correct City Bank CityFast upload fields.

### Sites

- City Bank: https://cityfastagent.citybankplc.com/
- Verify source: https://verify.new.barikoimaps.dev/reports

Use the supplied credentials. Never include passwords, session tokens, or cookies in logs or reports.

### 1. Open City Bank and log in

- If access is rejected, stop and report the displayed message/support ID.
- Click **MY Q** once to load the file list.
- Work only on the file(s) specified by the operator.

### 2. Identify the file

- Record the full **File Serial No**, its trailing numeric identifier, and applicant name.
- Preserve leading zeros.
- Click that row’s **UR (Upload Reports)** action.
- Read every requested upload label and any existing uploaded documents.
- Keep this page open.

### 3. Find the corresponding Verify application in another tab

- Search using the bank file identifier.
- Verify is the source of truth for documents.
- Do not assume the first search result is the correct file: search can match trip IDs.
- Confirm the file identity and applicant against City Bank.
- If the match is missing, ambiguous, or inconsistent, stop that file and report it.

### 4. Open Update Topsheet for Trips

- Open it from the matching report row.
- Identify each trip’s concern/person and type.
- Inspect its attachment labels before selecting anything.
- Do not edit report answers, remarks, verification status, or click **Save**.

### 5. Map documents according to City Bank’s exact upload labels

- **Residence Address / Image of Residence:** relevant House trip report PDF with residence attachments selected.
- **Image of Office:** relevant Office trip report PDF with office-image attachments selected; exclude LOI attachments.
- **Letter of Introduction (LOI) / Salary Certificate (Original):** standalone LOI PDF from the relevant Office trip; do not substitute the entire Office report.
- **Bank Statement:** relevant Bank Verification trip with **BANK STATEMENT** attachments.
- Use applicant documents unless City Bank explicitly requests co-applicant or guarantor documents.
- If a label does not clearly fit these rules, ask the operator.

### 6. Prepare and check each download

- Ensure the intended attachments are checked before downloading a trip report.
- Confirm the downloaded PDF belongs to the correct file, person, trip, and document category.
- Each upload file must be **no larger than 1 MB**.
- If oversized, use local compression and inspect the result for readability, page completeness, and correct orientation.
- Do not use third-party document-compression websites.
- If it cannot meet the size limit without losing required content, report the blocker.
- Use filenames containing the file identifier, concern, document category, and trip ID where applicable.

### 7. Upload only when execution is explicitly authorized

- Exploration-only instructions mean **no uploads or final submission**.
- Place each validated PDF in its exact City Bank upload field.
- Do not replace an existing document without explicit instruction.
- If attachments are missing, multiple candidates are ambiguous, or documents are already uploaded, report in the originating channel and await direction.
- After submitting, verify the bank’s saved result for each document.
- Do not blindly retry a failed upload: inspect whether it saved first.

### 8. Report results

Include:

- Bank full file serial and matched Verify application link.
- Requested upload label → source concern/trip → filename and size.
- Saved/uploaded status, supported by the bank’s visible result.
- Any skipped items, mismatches, errors, or unresolved questions.

**Never mix documents between files or people. Do not infer successful upload from file selection alone.**

## Screenshots the agent needs

Send these as numbered, readable screenshots:

1. **City Bank MY Q:** include the left-side **MY Q and UR controls**, plus the **Applicant Name and full File Serial No** columns. Mark the target row without covering its text.
2. **City Bank UR page — most important missing image:** capture **all upload labels, file pickers, existing-document indicators, size/type restrictions, and Upload/Submit buttons**. Include the file/applicant identity at the top.
3. **Verify search result:** include the **search text, applicant, file number, organization, trip IDs, and Actions column**. Mark the Update Topsheet action.
4. **Verify House panel:** show the **left trip list with concern/type/ID**, selected House trip, residence attachment labels and checkboxes, and download controls.
5. **Verify Office panel:** same framing, clearly showing **office images versus the LOI PDF**, their checkboxes, and download controls.
6. **Verify Bank Verification panel:** show the trip identity and **BANK STATEMENT** attachments.

Use a full-page view plus close-ups where labels are too small. Hide passwords and unrelated customer details.


1st thing 1st , dont think its lemon roy file 
it should be global. 
any files could have these fields. more or less 
1. Business Address with Photo = your concept is clear
2. Residence Address / Image of Residence = your concept is clear
3. Image of Office =  your concept is clear
4. Office Address / Passport Size Photo / Signature = your concept is clear
5. Loi term is different , in our verify loi is fixed term, and in city bank it is self Declaration, Salary certificate . your prime truth you have to choose ocr verify's Loi image 
6.  same as pay slip naming thing also could be named as Loi in verify , so you have to need ocr here 
7. Bank Statement = your concept is clear
8. Authorization / Withdrawal Letter = ocr need . have to find bank statement's  trip's attachements 
one more thing , 
my devs confirm the steps to download pdf from verify dashboard 
- clicked update topsheet , 
- select you desir trip , 
- choose attachments 
- then clicked the save button, make sure you clicked that otherwise only report page will downloaded
- then finally clicked the download selected button to download 