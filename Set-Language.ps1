param([string]$InstallRoot,[string]$PythonPath,[string]$Source,[string]$Target)
$action = 'language'
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
