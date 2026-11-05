param([switch]$TestMail, [switch]$NotifyNow)
$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot 'runtime-path.txt'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run install.cmd first.' }
$runtimePython = [IO.File]::ReadAllText($runtimeFile).Trim()
if ($TestMail -and $NotifyNow) { throw 'Choose one email action.' }
if ($NotifyNow) {
    & $runtimePython (Join-Path $PSScriptRoot 'workbuddy_checkin.py') --notify-only
    $wbMailExitCode = $LASTEXITCODE
    if ($wbMailExitCode -ne 0) { Write-Host 'Notification failed. Check checkin.log; run setup-email.cmd if not configured.' }
    exit $wbMailExitCode
}
$helper = Join-Path $PSScriptRoot 'setup_email.py'
if ($TestMail) { & $runtimePython $helper --test }
else {
    $runtimePythonw = Join-Path (Split-Path -Parent $runtimePython) 'pythonw.exe'
    $guiHelper = Join-Path $PSScriptRoot 'setup_email_gui.pyw'
    Start-Process -FilePath $runtimePythonw -ArgumentList ('"' + $guiHelper + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Normal
    exit 0
}
exit $LASTEXITCODE
