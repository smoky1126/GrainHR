# Changelog

## 1.2.3

- Today's attendance counts someone as late as soon as they clock in, without waiting for the clock-out.

## 1.2.2

- The website trusts the Cloudflare Google sign-in, so people are not asked to sign in a second time.

## 1.2.1

- A saved attendance file that is not a real workbook is skipped, and that month is built again.

## 1.2.0

- Pages stop rewriting the month lock on every click, and Excel files are read again only when they change.
- Past months open the saved attendance export and the issued salary slips, without recalculating pay.
- Month records download a file only when it is clicked.
- The logo is read from beside company.toml when it is not in the program folder.
- A 使用說明 page explains the daily check, month end, and where old slips are.

## 1.1.0

- One command runs the tests, and a release copies that version onto the shared drive.
- Staff and roster files are read again only when the file changes.
- A page error is written to data/logs/grainhr.log, and an open Excel file gets a clear message.
- Shop codes use the labels in company.toml. The home page shows this month's payroll progress.
- Unmatched roster and DAKA names can be linked on 名字配對.
- Only an admin can change salary settings. Payroll adjustments are recorded.

## 1.0.0

- GrainHR is the payroll program, split by domain.
- Company names and folders live in company.toml, which is not committed.
- The home page greets the user, shows the time, and shows when DAKA, the rosters, and the staff file were last updated.
- The sidebar can be opened again with the 選單 button.
