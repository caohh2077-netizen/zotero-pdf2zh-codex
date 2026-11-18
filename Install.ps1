param([string]$InstallRoot,[string]$PythonPath,[string]$ZoteroPath,[string]$CodexPath,[string]$Wheelhouse,[string]$AssetDir,[string]$Profile,[switch]$PrepareOnly)
$action = 'install'
if ($PrepareOnly) { $action='prepare' }
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
