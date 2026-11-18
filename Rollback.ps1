param([string]$InstallRoot,[string]$PythonPath)
$action = 'rollback'
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
