$ErrorActionPreference = 'Stop'
$taskName = 'WorkBuddy-Daily-CheckIn-1000'
$expected = 'WorkBuddyDailyAutomation: daily reward at 10:00, with logon/unlock catch-up.'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.Description -ne $expected) { throw 'Task ownership did not match; nothing removed.' }
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Write-Host 'Schedule removed. Script files and logs have been retained.'
