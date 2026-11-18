param([string]$InstallRoot,[string]$PythonPath,[string]$Profile,[switch]$Restore)
$action=if ($Restore) {'restore-prefs'} else {'use-codex'}
& (Join-Path $PSScriptRoot 'scripts\Entry.ps1') -Action $action -Options $PSBoundParameters
