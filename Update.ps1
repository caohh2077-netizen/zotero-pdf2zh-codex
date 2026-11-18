param([string]$InstallRoot,[string]$PythonPath,[string]$Version)
$action = 'update'
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
