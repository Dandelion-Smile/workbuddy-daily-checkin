$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot 'runtime-path.txt'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run install.cmd first.' }
$runtimePython = [IO.File]::ReadAllText($runtimeFile).Trim()
& $runtimePython (Join-Path $PSScriptRoot 'workbuddy_checkin.py') --verbose
$result = $LASTEXITCODE
Write-Host "Exit code: $result (0 = success, 75 = failed; see checkin.log)."
exit $result
