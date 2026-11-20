# GrainHR

Payroll and attendance for a multi-shop company. Double-click `薪酬系統.bat`. The browser opens a page. There is no separate login: the Windows user name is mapped in `company.toml`.

Copy `company.example.toml` to `company.toml` and fill in your own names, shops, and folders. `company.toml` is not committed.

Copy `local.bat.example` to `local.bat` if the payroll files live in another folder. Set `PAYROLL_HOME` to that folder.

To try the app without changing real files, double-click `示範.bat`.

Python packages install into `_packages` and are not committed.
