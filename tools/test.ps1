# Run the GrainHR tests on demo data. Real staff, salary, and company files are not used.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$py = Join-Path $env:LOCALAPPDATA "GrainHR\runtime\python\python.exe"
if (-not (Test-Path $py)) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) { Write-Error "找不到 Python。" }
    $py = $found.Source
}
foreach ($name in @("PAYROLL_HOME", "PAYROLL_STAFF", "PAYROLL_SOURCE", "PAYROLL_DEMO")) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
# A company.toml beside the code supplies labels. PAYROLL_HOME stays empty so tests write under _tmp.
if (-not $env:PAYROLL_COMPANY) {
    $company = Join-Path $root "company.toml"
    if (Test-Path $company) { $env:PAYROLL_COMPANY = $company }
}
# These compare the private October payroll files, which are not in the demo copy.
$skip = @("test_october.py", "test_app.py", "test_books.py")
$failed = @()
foreach ($test in (Get-ChildItem "$root\tests\test_*.py" | Sort-Object Name)) {
    if ($skip -contains $test.Name) {
        Write-Output "SKIP $($test.Name)"
        continue
    }
    Write-Output "RUN $($test.Name)"
    & $py $test.FullName
    if ($LASTEXITCODE -ne 0) {
        $failed += $test.Name
    }
}
if ($failed.Count) {
    Write-Error ("Tests failed: " + ($failed -join ", "))
}
Write-Output "Tests passed."
