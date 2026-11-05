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
else { & $runtimePython $helper }
exit $LASTEXITCODE
