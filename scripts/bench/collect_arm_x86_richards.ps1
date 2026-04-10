param(
  [string]$ArmHost = "124.70.162.35",
  [string]$X86Host = "106.14.164.133",
  [string]$User = "root",
  [string]$ArmVenv = "/root/venv-cinderx314",
  [string]$X86Venv = "/root/venv-cinderx314",
  [int]$Samples = 5,
  [int]$AutoJit = 50,
  [string]$OutDir = "artifacts/richards"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Exec {
  param([string]$Cmd)
  Write-Host ">> $Cmd"
  cmd.exe /c $Cmd
  if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Cmd" }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$runner = Join-Path $PSScriptRoot "run_richards_remote.sh"
$metrics = Join-Path $PSScriptRoot "richards_metrics.py"
if (-not (Test-Path $runner)) { throw "Missing runner: $runner" }
if (-not (Test-Path $metrics)) { throw "Missing metrics utility: $metrics" }

$timestamp = (Get-Date).ToString("yyyyMMdd_HHmmss")
$outRoot = Join-Path $repoRoot $OutDir
New-Item -ItemType Directory -Force -Path $outRoot | Out-Null

$sshOpts = "-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"
$remoteRunner = "/tmp/run_richards_remote.sh"
$armRemoteOut = "/tmp/richards_arm_${timestamp}.json"
$x86RemoteOut = "/tmp/richards_x86_${timestamp}.json"

$armLocal = Join-Path $outRoot "arm_samples_${timestamp}.json"
$x86Local = Join-Path $outRoot "x86_samples_${timestamp}.json"
$sumNojit = Join-Path $outRoot "summary_nojit_${timestamp}.json"
$sumJitlist = Join-Path $outRoot "summary_jitlist_${timestamp}.json"
$sumAuto = Join-Path $outRoot "summary_autojit50_${timestamp}.json"
$summaryCombined = Join-Path $outRoot "summary_arm_vs_x86_${timestamp}.json"

Exec ("scp {0} `"{1}`" {2}@{3}:{4}" -f $sshOpts, $runner, $User, $ArmHost, $remoteRunner)
Exec ("scp {0} `"{1}`" {2}@{3}:{4}" -f $sshOpts, $runner, $User, $X86Host, $remoteRunner)

Exec ("ssh {0} {1}@{2} `"chmod +x {3} && DRIVER_VENV={4} OUT={5} SAMPLES={6} AUTOJIT={7} {3}`"" -f `
    $sshOpts, $User, $ArmHost, $remoteRunner, $ArmVenv, $armRemoteOut, $Samples, $AutoJit)
Exec ("ssh {0} {1}@{2} `"chmod +x {3} && DRIVER_VENV={4} OUT={5} SAMPLES={6} AUTOJIT={7} {3}`"" -f `
    $sshOpts, $User, $X86Host, $remoteRunner, $X86Venv, $x86RemoteOut, $Samples, $AutoJit)

Exec ("scp {0} {1}@{2}:{3} `"{4}`"" -f $sshOpts, $User, $ArmHost, $armRemoteOut, $armLocal)
Exec ("scp {0} {1}@{2}:{3} `"{4}`"" -f $sshOpts, $User, $X86Host, $x86RemoteOut, $x86Local)

Exec ("python `"{0}`" --arm-samples-json `"{1}`" --x86-samples-json `"{2}`" --mode nojit --out `"{3}`"" -f `
    $metrics, $armLocal, $x86Local, $sumNojit)
Exec ("python `"{0}`" --arm-samples-json `"{1}`" --x86-samples-json `"{2}`" --mode jitlist --out `"{3}`"" -f `
    $metrics, $armLocal, $x86Local, $sumJitlist)
Exec ("python `"{0}`" --arm-samples-json `"{1}`" --x86-samples-json `"{2}`" --mode autojit50 --out `"{3}`"" -f `
    $metrics, $armLocal, $x86Local, $sumAuto)

$summary = [ordered]@{
  timestamp = $timestamp
  arm_host = $ArmHost
  x86_host = $X86Host
  samples = $Samples
  autojit = $AutoJit
  arm_samples_json = $armLocal
  x86_samples_json = $x86Local
  mode_compare = [ordered]@{
    nojit = (Get-Content $sumNojit -Raw | ConvertFrom-Json)
    jitlist = (Get-Content $sumJitlist -Raw | ConvertFrom-Json)
    autojit50 = (Get-Content $sumAuto -Raw | ConvertFrom-Json)
  }
}
$summary | ConvertTo-Json -Depth 16 | Set-Content $summaryCombined -Encoding UTF8

Write-Host "Combined summary:"
Write-Host $summaryCombined
Write-Host "AutoJIT50 speedup_pct (ARM faster positive):"
Write-Host $summary.mode_compare.autojit50.speedup_pct
