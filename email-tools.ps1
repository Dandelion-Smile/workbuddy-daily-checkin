param([switch]$TestMail)
$ErrorActionPreference = 'Stop'
$runtimeFile = Join-Path $PSScriptRoot 'runtime-path.txt'
if (-not (Test-Path -LiteralPath $runtimeFile)) { throw 'Run install.cmd first.' }
$runtimePython = [IO.File]::ReadAllText($runtimeFile).Trim()
$helper = Join-Path $PSScriptRoot 'setup_email.py'
if ($TestMail) { & $runtimePython $helper --test }
else { & $runtimePython $helper }
exit $LASTEXITCODE
