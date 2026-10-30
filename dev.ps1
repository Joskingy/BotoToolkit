# Use the project's tested uv/Python without changing the caller's environment.
$ErrorActionPreference = 'Stop'
$commonDir = & git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$cloneRoot = Split-Path -Parent $commonDir
$uvBinary = Join-Path $cloneRoot '.uv/ci-tools/uv-0.13.4/uv.exe'
if (-not (Test-Path -LiteralPath $uvBinary)) {
    $uvBinary = (Get-Command uv -ErrorAction Stop).Source
}
$pythonBinary = Join-Path $cloneRoot '.uv/python/cpython-3.15.0-windows-x86_64-none/python.exe'
if (-not (Test-Path -LiteralPath $pythonBinary)) { $pythonBinary = '3.15.0' }
& $uvBinary run --no-project --python $pythonBinary (Join-Path $PSScriptRoot 'scripts/dev.py') @args
exit $LASTEXITCODE
