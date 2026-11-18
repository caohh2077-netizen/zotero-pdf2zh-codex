param([ValidateSet('Offline','Lifecycle')][string]$Suite='Offline',[string]$PythonPath)
if (!$PythonPath) { $PythonPath=Join-Path (Split-Path -Parent $PSScriptRoot) '.venv-dev\Scripts\python.exe' }
$name=if ($Suite -eq 'Offline') { 'test_contract.py' } else { 'test_jobs.py' }
& $PythonPath -I -X utf8 (Join-Path $PSScriptRoot 'run_tests.py') $name
if ($LASTEXITCODE) { throw "$Suite tests failed" }
