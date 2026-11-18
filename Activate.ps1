param([string]$InstallRoot,[string]$PythonPath)
$action = 'activate'
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
