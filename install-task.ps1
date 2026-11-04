param(
    [string]$RuntimeDirectory = (Join-Path $env:LOCALAPPDATA 'WorkBuddyDailyAutomation\runtime'),
    [string]$PythonExecutable = 'python.exe'
)
$ErrorActionPreference = 'Stop'
$taskName = 'WorkBuddy-Daily-CheckIn-1000'
$ownerTag = 'WorkBuddyDailyAutomation: daily reward at 10:00, with logon/unlock catch-up.'
$scriptFile = Join-Path $PSScriptRoot 'workbuddy_checkin.py'
$requirementsFile = Join-Path $PSScriptRoot 'requirements.txt'
$runtimePython = Join-Path $RuntimeDirectory 'Scripts\python.exe'
$runtimePythonw = Join-Path $RuntimeDirectory 'Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    & $PythonExecutable -m venv $RuntimeDirectory
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
}
& $runtimePython -m pip install --disable-pip-version-check -r $requirementsFile
if ($LASTEXITCODE -ne 0) { throw 'Could not install required Python packages.' }
& $runtimePython $scriptFile --validate
if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed. Check bootstrap-error.log.' }
# Resolve Windows packaged-app filesystem redirects before storing a path that
# Task Scheduler will later open from a separate process.
$physicalPython = & $runtimePython -c 'import pathlib,sys; print(pathlib.Path(sys.executable).resolve())'
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the runtime executable.' }
$runtimePython = $physicalPython.Trim()
$runtimePythonw = Join-Path (Split-Path -Parent $runtimePython) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $runtimePythonw)) { throw 'pythonw.exe is missing.' }

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $ownerTag) {
    throw 'A different task uses this name. No task was overwritten.'
}
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$now = Get-Date
$start = $now.Date.AddHours(10)
if ($start -le $now) { $start = $start.AddDays(1) }
$boundary = $start.ToString('yyyy-MM-ddTHH:mm:ss')
$escapedPython = [Security.SecurityElement]::Escape($runtimePythonw)
$escapedScript = [Security.SecurityElement]::Escape($scriptFile)
$escapedDirectory = [Security.SecurityElement]::Escape($PSScriptRoot)
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$ownerTag</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$boundary</StartBoundary><Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger><Enabled>true</Enabled><UserId>$sid</UserId></LogonTrigger>
    <SessionStateChangeTrigger>
      <Enabled>true</Enabled><StateChange>SessionUnlock</StateChange><UserId>$sid</UserId>
    </SessionStateChangeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>$sid</UserId><LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled>
    <Hidden>false</Hidden><WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT3M</ExecutionTimeLimit><Priority>7</Priority>
    <RestartOnFailure><Interval>PT10M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>$escapedPython</Command>
    <Arguments>&quot;$escapedScript&quot; --scheduled</Arguments>
    <WorkingDirectory>$escapedDirectory</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'runtime-path.txt'), $runtimePython,
    [Text.UTF8Encoding]::new($false))
Get-ScheduledTaskInfo -TaskName $taskName | Select-Object NextRunTime, LastTaskResult
Write-Host 'Installed: daily at 10:00 (Windows local time); catch up after logon/unlock.'
