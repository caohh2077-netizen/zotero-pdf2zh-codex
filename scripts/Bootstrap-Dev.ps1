param([string]$PythonPath='python.exe')
$ErrorActionPreference='Stop'
$repo=Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    & $PythonPath -m venv .venv-dev
    if ($LASTEXITCODE) { throw 'venv failed' }
    & $PythonPath -I src/wheels.py .work/verified-wheels
    if ($LASTEXITCODE) { throw 'wheel verification failed' }
    & .\.venv-dev\Scripts\python.exe -m pip --disable-pip-version-check install --no-index --only-binary=:all: --no-deps --require-hashes --find-links .work/verified-wheels -r locks/windows-x64-py312.txt
    if ($LASTEXITCODE) { throw 'pip failed' }
} finally { Pop-Location }
