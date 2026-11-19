param([ValidateSet('Offline','Lifecycle')][string]$Suite='Offline',[string]$PythonPath)
$ErrorActionPreference='Stop'
if (!$PythonPath) { $PythonPath=Join-Path (Split-Path -Parent $PSScriptRoot) '.venv-dev\Scripts\python.exe' }
$names=if ($Suite -eq 'Offline') { @('test_contract.py','test_fragments.py') } else { @('test_jobs.py') }
foreach ($name in $names) {
& $PythonPath -I -X utf8 (Join-Path $PSScriptRoot 'run_tests.py') $name
if ($LASTEXITCODE) { throw "$Suite tests failed" }
}
