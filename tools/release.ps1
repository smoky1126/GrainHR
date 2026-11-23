# Copy a tagged GrainHR version onto the shared drive. Refuses to run with uncommitted changes.
param(
    [string]$Destination = $env:GRAINHR_DEST
)
$ErrorActionPreference = "Stop"
if (-not $Destination) { Write-Error "Pass -Destination or set GRAINHR_DEST." }
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$dirty = git status --porcelain
if ($dirty) {
    Write-Error "Commit or stash changes before releasing."
}
$version = (Get-Content "$root\VERSION" -Raw).Trim()
$py = Join-Path $env:LOCALAPPDATA "GrainHR\runtime\python\python.exe"
if (-not (Test-Path $py)) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) { Write-Error "找不到 Python。" }
    $py = $found.Source
}
$company = Join-Path $root "company.toml"
if (Test-Path $company) {
    $env:PAYROLL_COMPANY = $company
}
# test_october writes against the private October files, so a release does not run it.
$tests = @(
    "test_days.py", "test_holidays.py", "test_rosters.py", "test_today.py",
    "test_daka_inbox.py", "test_directory.py", "test_lateness.py",
    "test_product.py", "test_cloud.py", "test_access_token.py", "test_security.py", "test_improvements.py",
    "test_part_time.py", "test_staff_write.py"
)
foreach ($test in $tests) {
    Write-Output "RUN $test"
    & $py "tests\$test"
    if ($LASTEXITCODE -ne 0) { Write-Error "Test failed: $test" }
}
git tag "v$version"
New-Item -ItemType Directory -Force -Path "$Destination\app" | Out-Null
New-Item -ItemType Directory -Force -Path "$Destination\_releases" | Out-Null
if (Test-Path "$Destination\app\VERSION") {
    $previous = (Get-Content "$Destination\app\VERSION" -Raw).Trim()
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    robocopy "$Destination\app" "$Destination\_releases\$previous-$stamp" /MIR /NFL /NDL /NJH /NJS | Out-Null
}
robocopy $root "$Destination\app" /MIR /XD .git data months demo daka_inbox Oct_2026 templates _packages _tmp fixtures_private __pycache__ /XF company.toml local.bat *.xlsx *.csv *.docx /NFL /NDL /NJH /NJS | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText("$Destination\app\VERSION", ($version.Trim() + "`n"), $utf8)
Write-Output "Released GrainHR $version to $Destination\app"
