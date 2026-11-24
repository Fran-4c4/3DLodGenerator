<#
.SYNOPSIS
Prepare the isolated documentation environment and preview the English manual.
.DESCRIPTION
Runs from any working directory. Installs documentation dependencies only when
the environment is absent or its direct versions differ from docs/requirements.txt.
The first installation requires network access; later starts reuse the environment.
Ctrl+C stops the foreground server. This script never deploys a website.
.PARAMETER Port
Loopback TCP port, integer 1..65535. This launcher owns the convenience default
8000 and passes the address explicitly to MkDocs. No automatic port substitution.
.PARAMETER PythonCommand
Python executable used only to create a missing environment; default is python
resolved through PATH. An existing work/docs-env is used independently of PATH.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [string]$PythonCommand = 'python'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$docsEnvironment = Join-Path $projectRoot 'work/docs-env'
$docsPython = Join-Path $docsEnvironment 'Scripts/python.exe'
$requirements = Join-Path $projectRoot 'docs/requirements.txt'
$builder = Join-Path $projectRoot 'tools/build_docs.py'

if (-not (Test-Path -LiteralPath $docsPython)) {
    Write-Host 'Creating the documentation environment...'
    & $PythonCommand -m venv $docsEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the documentation environment.' }
}

# requirements.txt owns the pinned dependency versions. Do not duplicate pins.
$dependencyCheck = @'
import importlib.metadata
import pathlib
import sys
for raw in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#'):
        continue
    name, expected = line.split('==', 1)
    try:
        actual = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        raise SystemExit(1)
    if actual != expected:
        raise SystemExit(1)
'@
& $docsPython -c $dependencyCheck $requirements
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing documentation dependencies...'
    & $docsPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install documentation dependencies.' }
}

Write-Host "Documentation: http://127.0.0.1:$Port/"
Write-Host 'Keep this terminal open. Press Ctrl+C to stop.'
& $docsPython $builder --serve --dev-addr "127.0.0.1:$Port"
if ($LASTEXITCODE -ne 0) { throw "Documentation server exited with code $LASTEXITCODE." }
