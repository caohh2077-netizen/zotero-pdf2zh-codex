param([string]$Action,[hashtable]$Options)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$python = $Options['PythonPath']
if (!$python) { $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source }
if (!$python) { throw 'Set -PythonPath to CPython 3.12.10 x64 python.exe.' }
$arguments = @('-I','-X','utf8',(Join-Path $project 'src\manage.py'),$Action)
$names = @{ InstallRoot='root'; ZoteroPath='zotero'; CodexPath='codex'; Source='source'; Target='target'; Version='version'; Wheelhouse='wheelhouse'; AssetDir='asset-dir'; Profile='profile' }
foreach ($name in $names.Keys) { if ($Options[$name]) { $arguments += @("--$($names[$name])",[string]$Options[$name]) } }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "$Action failed ($LASTEXITCODE)." }
