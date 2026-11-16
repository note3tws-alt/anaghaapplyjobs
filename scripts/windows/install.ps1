<#
  One-time setup on Anagha's Windows PC.
  Run in PowerShell from the project folder:
      powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -CvPath "C:\Users\<you>\Downloads\Anagha_P_CV.pdf"
#>
param(
    [string]$CvPath = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Root
Write-Host "Project folder: $Root"

# 1. Python 3.10+
$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3", "python")) {
    try {
        $v = & cmd /c "$cand --version" 2>$null
        if ($v -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) { $py = $cand; break }
    } catch {}
}
if (-not $py) {
    Write-Host "Python 3.10 or newer is needed. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Yellow
    exit 1
}
Write-Host "Using $py"

# 2. Virtual environment and packages
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv" }
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip | Out-Null
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 3. Browser: use installed Google Chrome; otherwise download Playwright's Chromium
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LocalAppData\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    Write-Host "Google Chrome not found: installing Playwright Chromium instead."
    & $vpy -m playwright install chromium
    $useChromium = $true
}

# 4. Local config, database, folders
if ($CvPath) { & $vpy -m jobbot init --cv "$CvPath" } else { & $vpy -m jobbot init }
if ($useChromium) {
    (Get-Content .env) -replace '^JOBBOT_BROWSER_CHANNEL=.*', 'JOBBOT_BROWSER_CHANNEL=chromium' | Set-Content .env
}

# 5. Private data stays private: only this Windows user can read data\, config\ and .env
foreach ($p in @("data", ".env", "config\candidate_private.yaml", "config\screening_answers.yaml", "config\settings.yaml")) {
    if (Test-Path $p) { icacls $p /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" /T /Q | Out-Null }
}

# 6. Desktop shortcuts
$desk = [Environment]::GetFolderPath("Desktop")
$ws = New-Object -ComObject WScript.Shell
foreach ($s in @(@{n="Job Assistant Dashboard"; f="start_dashboard.bat"}, @{n="Job Assistant - Sign in to Indeed"; f="login.bat"})) {
    $lnk = $ws.CreateShortcut((Join-Path $desk "$($s.n).lnk"))
    $lnk.TargetPath = Join-Path $Root "scripts\windows\$($s.f)"
    $lnk.WorkingDirectory = $Root
    $lnk.Save()
}

& $vpy -m jobbot doctor
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Green
Write-Host " 1. Double-click 'Job Assistant - Sign in to Indeed' on the desktop and sign in to Anagha's Indeed account."
Write-Host " 2. Check config\screening_answers.yaml (only answers marked verified: true are ever used)."
Write-Host " 3. Schedule it:  powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1"
