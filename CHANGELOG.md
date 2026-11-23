# Changelog

## 1.6.6

- Marking someone as resigned works when the staff sheet's first column is blank.

## 1.6.5

- The daily attendance page no longer draws a late chart. Lateness stays on 遲到統計.

## 1.6.4

- The month-step status sits in a pill beside the step name. It no longer stacks down the side of the menu.

## 1.6.3

- The attendance chart names who was late and for how many minutes. A day with nobody late has no chart.

## 1.6.2

- Copying a roster from the shared drive no longer crashes when the drive rejects extra file attributes. If a copy still fails, the attendance page shows a message instead of an error number.

## 1.6.1

- Today's page can read the newest roster time again.

## 1.6.0

- GitHub runs the tests on every push. The page check also opens 假期, 名字配對, 月份紀錄, 使用說明, and 設定.
- The server update installs a version tag. Direct library versions are pinned.
- The service file keeps the process from gaining extra privileges. The live unit should keep its own account name.
- A backup script copies the data folder once a day and drops copies older than 30 days. Staff-file backups can be restored from the staff page.
- A page crash or a month takeover is emailed when GRAINHR_ALERT_TO is set and sendmail is installed.

## 1.5.0

- The month steps in the sidebar are 出勤, 遲到, 新同事, 審核, 薪金, and 出糧. Each one shows when its file was last saved, and 需更新 when an earlier file is newer.
- 出勤紀錄 sits with the monthly pages. 薪金表 is split into 新同事, 全職, and 兼職. 出糧 shows one payroll book at a time.
- A page error shows a number staff can quote.

## 1.4.0

- Pages that only show information no longer build the payroll draft. The draft is cached and rebuilt when a punch, roster fact, staff file, or adjustment changes.
- Salary grids save from one button, so editing a cell does not rewrite the workbook. The whole-month attendance table is shown 100 rows at a time, and the late export is built when it is downloaded.
- Repeated reads of punches, pay tables, and the month checklist wait until those files change.

## 1.3.1

- Opening a page that only displays information no longer locks the month. A save is refused when someone else has taken over.
- Taking over, making one payslip, and marking someone as resigned ask for confirmation. Salary amounts have a minimum and a maximum, and the salary change shows the old and new figures.
- The part-time transaction number is stored when its save button is pressed. Logging out releases the month lock.

## 1.3.0

- HR staff can no longer download office pay in the "download all" zip, or rebuild office payslips.
- Names and other text shown as HTML are escaped. Excel exports keep text that starts with = as text.
- A broken login file stops the app instead of leaving it open. On the server, a person who is not on the list is never an admin.
- Salary, part-time rate, and new-joiner changes record who made them.

## 1.2.4

- Shop names, folder paths, office nicknames, and the server account stay in company.toml. The public program only reads them.

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
