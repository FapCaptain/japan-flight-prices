# Daily flight price fetch for this PC (replaces the GitHub Actions schedule).
# Run by the Windows Task Scheduler task "Japan flight price fetch".
#
#   git pull -> python fetch_flights.py -> commit data/ if changed -> git push
#
# Safeguards:
#   - Skips the SerpApi fetch if data/runs/<Brisbane date>.json is already committed,
#     so retries or a second run on the same day don't spend credits. Use -Force to override.
#   - On failure it waits 15 minutes and tries once more.
#   - Everything is appended to run.log next to this script.

param([switch]$Force)

$ErrorActionPreference = 'Continue'
$Repo   = $PSScriptRoot
$Log    = Join-Path $Repo 'run.log'
$Python = 'C:\Program Files\Python313\python.exe'

$env:GCM_INTERACTIVE = 'never'      # never let Git Credential Manager pop up a sign-in window
$env:GIT_TERMINAL_PROMPT = '0'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:SERPAPI_KEY) {
    $env:SERPAPI_KEY = [Environment]::GetEnvironmentVariable('SERPAPI_KEY', 'User')
}

function Log([string]$msg) {
    Add-Content -Path $Log -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $msg) -Encoding UTF8
}

# Runs a program, logs its stdout and stderr, and returns its exit code.
function Run([string]$exe, [string[]]$argv) {
    $out = & $exe @argv 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $out) { Log ("    " + "$line") }
    return $code
}

function BrisbaneDate {
    $bne = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId((Get-Date), 'E. Australia Standard Time')
    return $bne.ToString('yyyy-MM-dd')
}

function WaitForNetwork {
    # After waking from sleep, Wi-Fi can take a little while to reconnect.
    for ($i = 0; $i -lt 24; $i++) {
        try {
            $null = [Net.Dns]::GetHostAddresses('github.com')
            return $true
        } catch { Start-Sleep -Seconds 5 }
    }
    return $false
}

function Attempt {
    Set-Location $Repo
    $today = BrisbaneDate

    if (-not (WaitForNetwork)) { Log "ERROR: no network (could not resolve github.com)"; return $false }

    Log "git pull"
    if ((Run 'git' @('pull', '--rebase')) -ne 0) { Log "ERROR: git pull failed"; return $false }

    $runFile = "data/runs/$today.json"
    & git cat-file -e "HEAD:$runFile" 2>$null
    $alreadyDone = ($LASTEXITCODE -eq 0)

    if ($alreadyDone -and -not $Force) {
        Log "Prices for $today are already committed, skipping the SerpApi fetch"
    } else {
        if (-not $env:SERPAPI_KEY) { Log "ERROR: SERPAPI_KEY is not set"; return $false }
        Log "python fetch_flights.py"
        if ((Run $Python @('fetch_flights.py')) -ne 0) {
            Log "ERROR: fetch_flights.py failed, discarding partial data"
            $null = & git checkout -- data 2>&1
            $null = & git clean -fq -- data 2>&1
            return $false
        }
        $null = Run 'git' @('add', 'data')
        & git diff --cached --quiet
        if ($LASTEXITCODE -ne 0) {
            Log "git commit"
            if ((Run 'git' @('commit', '-m', "Prices for $today")) -ne 0) { Log "ERROR: git commit failed"; return $false }
        } else {
            Log "No changes in data/, nothing to commit"
        }
    }

    # Push whenever we are ahead of GitHub (also covers a commit left over from an earlier failed push).
    $ahead = (& git rev-list --count '@{u}..HEAD' 2>$null)
    if ($ahead -and [int]$ahead -gt 0) {
        Log "git push"
        if ((Run 'git' @('push')) -ne 0) { Log "ERROR: git push failed"; return $false }
    }
    return $true
}

Log "===== Start (Brisbane date $(BrisbaneDate))$(if ($Force) { ' -Force' }) ====="
$ok = Attempt
if (-not $ok) {
    Log "Attempt 1 failed, retrying in 15 minutes"
    Start-Sleep -Seconds 900
    $ok = Attempt
}
if ($ok) { Log "===== Done =====" ; exit 0 }
Log "===== FAILED ====="
exit 1
