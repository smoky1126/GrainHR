# Edit Staff_info through Excel so the Sheet2 dropdowns stay in the file.
param(
    [Parameter(Mandatory = $true)][string]$JsonPath
)
$ErrorActionPreference = "Stop"
$payload = Get-Content -Raw -Encoding UTF8 $JsonPath | ConvertFrom-Json
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.ScreenUpdating = $false

function Release-Com($item) {
    if ($null -ne $item) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($item)
    }
}

function Find-HeaderRow($sheet) {
    $limit = [Math]::Min(20, $sheet.UsedRange.Rows.Count + $sheet.UsedRange.Row - 1)
    $cols = $sheet.UsedRange.Columns.Count + $sheet.UsedRange.Column - 1
    for ($row = 1; $row -le $limit; $row++) {
        for ($col = 1; $col -le $cols; $col++) {
            $text = ([string]$sheet.Cells.Item($row, $col).Text).Trim().TrimEnd("*")
            if ($text.StartsWith([string]"員工編號")) {
                return $row
            }
        }
    }
    throw "找不到「員工編號」標題。"
}

function Map-Columns($sheet, $headerRow) {
    $map = @{}
    $col = 1
    while ($true) {
        $text = ([string]$sheet.Cells.Item($headerRow, $col).Text).Trim().TrimEnd("*")
        if ($text -eq "") { break }
        if (-not $map.ContainsKey($text)) { $map[$text] = $col }
        $col++
        if ($col -gt 80) { break }
    }
    return $map
}

function Last-DataRow($sheet, $headerRow, $numberCol) {
    $row = $sheet.UsedRange.Row + $sheet.UsedRange.Rows.Count - 1
    while ($row -gt $headerRow) {
        $text = ([string]$sheet.Cells.Item($row, $numberCol).Text).Trim()
        if ($text -ne "") { return $row }
        $row--
    }
    return $headerRow
}

function Find-PersonRow($sheet, $headerRow, $columns, $number, $name) {
    $numberCol = $columns["員工編號"]
    $nameCol = $columns["中文姓名"]
    $last = Last-DataRow $sheet $headerRow $numberCol
    for ($row = $headerRow + 1; $row -le $last; $row++) {
        $gotNumber = ([string]$sheet.Cells.Item($row, $numberCol).Text).Trim()
        $gotName = ([string]$sheet.Cells.Item($row, $nameCol).Text).Trim()
        if ($gotNumber -eq $number -and $gotName -eq $name) { return $row }
    }
    return 0
}

function Set-Cell($sheet, $row, $col, $name, $value) {
    # Keep the range in one expression. Passing a Range into a function makes
    # PowerShell unwrap it into the cell value.
    $text = [string]$value
    $dates = @("入職日期", "到職日期", "離職日期", "出生日期", "合約完結日期")
    if ($text -eq "") {
        $sheet.Cells.Item($row, $col).ClearContents() | Out-Null
        return
    }
    if ($dates -contains $name -and $text -match "^\d{4}-\d{2}-\d{2}$") {
        $parsed = [datetime]::ParseExact($text, "yyyy-MM-dd", [cultureinfo]::InvariantCulture)
        $sheet.Cells.Item($row, $col).NumberFormat = "yyyy-mm-dd"
        $sheet.Cells.Item($row, $col).Formula = "=DATE($($parsed.Year),$($parsed.Month),$($parsed.Day))"
        return
    }
    $sheet.Cells.Item($row, $col).Value2 = $text
}

$book = $null
try {
    $book = $excel.Workbooks.Open($payload.path)
    if ($book.ReadOnly) {
        throw "請先關閉 Staff_info 檔案，然後再試。"
    }
    $sheet = $book.Worksheets.Item([string]$payload.sheet)
    $headerRow = Find-HeaderRow $sheet
    $columns = Map-Columns $sheet $headerRow
    if (-not $columns.ContainsKey("員工編號")) { throw "找不到「員工編號」標題。" }

    if ($payload.action -eq "resign" -and -not $columns.ContainsKey("離職日期")) {
        $newCol = ($columns.Values | Measure-Object -Maximum).Maximum + 1
        $sheet.Cells.Item($headerRow, $newCol).Value2 = "離職日期"
        $columns["離職日期"] = $newCol
    }

    $number = [string]$payload.employee_no
    $name = [string]$payload.name_zh
    if ($payload.action -eq "add") {
        $last = Last-DataRow $sheet $headerRow $columns["員工編號"]
        $row = $last + 1
        $width = ($columns.Values | Measure-Object -Maximum).Maximum
        $sheet.Rows.Item($last).Copy() | Out-Null
        $sheet.Rows.Item($row).PasteSpecial(-4122) | Out-Null
        for ($col = 1; $col -le $width; $col++) {
            $sheet.Cells.Item($row, $col).ClearContents() | Out-Null
        }
    } else {
        $row = Find-PersonRow $sheet $headerRow $columns $number $name
        if ($row -eq 0) { throw "找不到 $number $name。" }
    }

    foreach ($field in $payload.fields.PSObject.Properties) {
        if (-not $columns.ContainsKey($field.Name)) { continue }
        Set-Cell $sheet $row $columns[$field.Name] $field.Name $field.Value
    }

    if ($payload.action -eq "resign") {
        for ($col = 2; $col -le 12; $col++) {
            $paint = $sheet.Cells.Item($row, $col).Interior
            $paint.ThemeColor = 7
            $paint.TintAndShade = 0.4
        }
    }

    $book.Save()
    $book.Close($true)
    $book = $null
} catch {
    if ($null -ne $book) { $book.Close($false) | Out-Null }
    throw
} finally {
    $excel.Quit()
    Release-Com $excel
    [GC]::Collect()
}
