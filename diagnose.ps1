$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot 'runtime-path.txt'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run install.cmd first.' }
$runtimePython = [IO.File]::ReadAllText($runtimeFile).Trim()
& $runtimePython (Join-Path $PSScriptRoot 'workbuddy_checkin.py') --diagnose --verbose
$wbDiagnosticExit = $LASTEXITCODE
Write-Host "Diagnostic exit code: $wbDiagnosticExit. See last-diagnostic.json in runtime_directory."
exit $wbDiagnosticExit
