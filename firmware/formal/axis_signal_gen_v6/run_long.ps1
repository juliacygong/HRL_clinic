# Unattended runner for the long BMC tasks (timing, timing_dds, order).
# Launched via Scheduled Task "sg_v6_formal_long" so it survives closing the
# VS Code tunnel. Keeps the PC awake only while running.
$ErrorActionPreference = 'Continue'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$env_b = 'C:\Users\HRLLab\Downloads\oss-cad-suite\environment.bat'
$tasks = 'timing', 'timing_dds', 'order'
$log   = Join-Path $here 'run_long.log'
Set-Location $here

Add-Type -Namespace W -Name P -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);'
[W.P]::SetThreadExecutionState(0x80000001) | Out-Null   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED

function Say($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Add-Content $log }
function Verdict($t) {
    $f = Get-ChildItem "sg_v6_$t" -File -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -match '^(PASS|FAIL|ERROR|UNKNOWN|TIMEOUT)$' }
    if ($f) { $f.Name } else { 'NONE' }
}
function Launch($t) {
    Start-Process cmd.exe -ArgumentList "/c call `"$env_b`" && sby -f sg_v6.sby $t > run_long_$t.out 2>&1" `
        -WorkingDirectory $here -WindowStyle Hidden -PassThru
}

Say "start: $($tasks -join ', ')"
$procs = @{}
foreach ($t in $tasks) { $procs[$t] = Launch $t; Say "launched $t (pid $($procs[$t].Id))"; Start-Sleep 30 }

# One retry per task if it died early (e.g. Application Control WinError 4551 on yices).
$retried = @{}
while ($true) {
    $running = 0
    foreach ($t in $tasks) {
        $p = $procs[$t]
        if (-not $p.HasExited) { $running++; continue }
        if (-not $retried[$t] -and (Verdict $t) -in 'NONE', 'ERROR' -and
            (Select-String "run_long_$t.out" -Pattern '4551|blocked this file' -Quiet)) {
            $retried[$t] = $true; Start-Sleep 20
            $procs[$t] = Launch $t; $running++
            Say "retry $t after policy block (pid $($procs[$t].Id))"
        }
    }
    if ($running -eq 0) { break }
    Start-Sleep 60
}

foreach ($t in $tasks) { Say "done $t : $(Verdict $t)" }
Say 'all finished'
[W.P]::SetThreadExecutionState(0x80000000) | Out-Null
