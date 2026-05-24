param(
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

if (-not $Python) {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $Python = $pythonCmd.Source
    } else {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            $Python = $pyCmd.Source
        }
    }
}

if (-not $Python) {
    Write-Error "Python was not found. Install Python, activate your venv, or pass -Python C:\path\to\python.exe"
}

& $Python (Join-Path $RepoRoot "scripts\check_project.py")
exit $LASTEXITCODE
