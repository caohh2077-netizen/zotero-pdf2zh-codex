param([string]$InstallRoot,[string]$PythonPath,[string]$Profile)
$action = 'doctor'
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
