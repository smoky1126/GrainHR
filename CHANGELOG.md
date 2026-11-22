# Changelog

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
