param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("build", "test", "test-single", "build-and-test", "check", "clean")]
    [string]$Action,

    [string]$TestFilter,

    [string]$TestPath,

    [string]$SourceDir,

    [switch]$VerboseOutput,

    [switch]$EnablePGO,

    [switch]$EnableLTO
)

$ConfigFile = Join-Path $PSScriptRoot "..\config.ini"

$config = @{}
Get-Content $ConfigFile -ErrorAction Stop | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+?)\s*=\s*(.+?)\s*$') {
        $config[$matches[1].Trim()] = $matches[2].Trim()
    }
}

$ProjectRoot = $config['work_dir']
if (-not $ProjectRoot) { Write-Error "config.ini missing required field: work_dir"; exit 1 }

$RemoteScript = Join-Path $ProjectRoot "scripts\remote.ps1"

if (-not $SourceDir) {
    $SourceDir = $config['upload_dir']
    if (-not $SourceDir) { Write-Error "config.ini missing required field: upload_dir and -SourceDir not specified"; exit 1 }
}

$PythonExe = $config['remote_python']
if (-not $PythonExe) { Write-Error "config.ini missing required field: remote_python"; exit 1 }

function Invoke-Remote {
    param([string]$Command)
    if ($VerboseOutput) { Write-Host "[REMOTE] $Command" -ForegroundColor Cyan }
    powershell -ExecutionPolicy Bypass -File $RemoteScript -Action exec -ConfigFile $ConfigFile -Command $Command
    if ($LASTEXITCODE -ne 0) { Write-Error "Remote command failed with exit code $LASTEXITCODE"; exit $LASTEXITCODE }
}

function Invoke-RemoteTransfer {
    param([string]$ActionType, [string]$LocalPath, [string]$RemotePath)
    if ($VerboseOutput) { Write-Host "[$ActionType] $LocalPath <-> $RemotePath" -ForegroundColor Cyan }
    if ($ActionType -eq "upload") {
        powershell -ExecutionPolicy Bypass -File $RemoteScript -Action upload -ConfigFile $ConfigFile -LocalPath $LocalPath -RemotePath $RemotePath
        if ($LASTEXITCODE -ne 0) { Write-Error "Upload failed with exit code $LASTEXITCODE"; exit $LASTEXITCODE }
    } else {
        $dir = Split-Path -Parent $LocalPath
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        powershell -ExecutionPolicy Bypass -File $RemoteScript -Action download -ConfigFile $ConfigFile -RemotePath $RemotePath -LocalPath $LocalPath
    }
}

function Sync-Source {
    Write-Host "=== Syncing source code to remote server ===" -ForegroundColor Green
    Invoke-Remote "rm -rf $SourceDir && mkdir -p $SourceDir"

    $archiveName = "cinderx_source.tar.gz"
    $archivePath = Join-Path $env:TEMP $archiveName

    Write-Host "  Packing source code..." -ForegroundColor Cyan
    $excludes = @("--exclude=*.pyc", "--exclude=__pycache__", "--exclude=.git",
                  "--exclude=*.egg-info", "--exclude=build", "--exclude=dist", "--exclude=.cache")
    $tarArgs = $excludes + @("-czf", $archivePath, "-C", $ProjectRoot,
        "cinderx", "CMakeLists.txt", "setup.py", "pyproject.toml", "MANIFEST.in", "LICENSE", "README.md")
    & tar $tarArgs
    if ($LASTEXITCODE -ne 0) { Write-Error "Failed to create source archive"; exit 1 }

    Write-Host "  Uploading & extracting..." -ForegroundColor Cyan
    Invoke-RemoteTransfer upload $archivePath "$SourceDir/$archiveName"
    Invoke-Remote "cd $SourceDir && tar -xzf $archiveName && rm -f $archiveName"
    Remove-Item $archivePath -Force -ErrorAction SilentlyContinue
    Write-Host "Source code synced." -ForegroundColor Green
}

function Get-BuildCmd {
    $envPrefix = ""
    if ($EnablePGO) { $envPrefix += "CINDERX_ENABLE_PGO=1 " }
    if ($EnableLTO) { $envPrefix += "CINDERX_ENABLE_LTO=1 " }
    return "cd $SourceDir && ${envPrefix}$PythonExe -m pip install --no-build-isolation -e . 2>&1"
}

function Get-TestCmd {
    param([string]$Filter)
    $base = "cd $SourceDir && $PythonExe -m pytest cinderx/PythonLib/test_cinderx/ -v"
    if ($Filter) { return "$base -k '$Filter' 2>&1" }
    return "$base 2>&1"
}

$CheckCmd = "cd $SourceDir && $PythonExe -c 'import cinderx; print(cinderx.get_import_error()); assert cinderx.is_initialized()'"

switch ($Action) {
    "build" {
        Sync-Source
        Write-Host "=== Building CinderX ===" -ForegroundColor Green
        Invoke-Remote (Get-BuildCmd)
        Write-Host "=== Build completed ===" -ForegroundColor Green
    }

    "test" {
        Write-Host "=== Running tests ===" -ForegroundColor Green
        Invoke-Remote (Get-TestCmd $TestFilter)
        Write-Host "=== Tests completed ===" -ForegroundColor Green
    }

    "test-single" {
        if (-not $TestPath) {
            Write-Error "test-single requires -TestPath (e.g. 'test_jit_disable.py' or 'test_jit_disable.py::Cls::method')"
            exit 1
        }
        Write-Host "=== Running single test: $TestPath ===" -ForegroundColor Green

        $fileName = $TestPath -split '::' | Select-Object -First 1
        $testSelector = if ($TestPath -match '::') { $TestPath.Substring($fileName.Length) } else { '' }

        $findCmd = "cd $SourceDir && found=`$(find cinderx/PythonLib/test_cinderx -name '$fileName' -type f | head -1)`; if [ -z `"`${found}`" ]; then echo 'ERROR: Test file not found: $fileName' >&2; exit 1; fi; echo `${found}${testSelector}"
        $resolvedPath = powershell -ExecutionPolicy Bypass -File $RemoteScript -Action exec -ConfigFile $ConfigFile -Command $findCmd 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to find test file: $fileName"; exit 1 }
        $resolvedPath = $resolvedPath.Trim()

        if ($VerboseOutput) { Write-Host "  Resolved: $resolvedPath" -ForegroundColor Cyan }
        Invoke-Remote "cd $SourceDir && $PythonExe -m pytest $resolvedPath -v --tb=long 2>&1"
        Write-Host "=== Single test completed ===" -ForegroundColor Green
    }

    "build-and-test" {
        Write-Host "=== Full pipeline: Build + Check + Test ===" -ForegroundColor Green
        Sync-Source
        Write-Host "`n--- Building ---" -ForegroundColor Yellow
        Invoke-Remote (Get-BuildCmd)
        Write-Host "`n--- Checking module loads ---" -ForegroundColor Yellow
        Invoke-Remote $CheckCmd
        Write-Host "`n--- Running tests ---" -ForegroundColor Yellow
        Invoke-Remote (Get-TestCmd $TestFilter)
        Write-Host "`n=== Pipeline completed ===" -ForegroundColor Green
    }

    "check" {
        Write-Host "=== Checking CinderX module loads ===" -ForegroundColor Green
        Invoke-Remote $CheckCmd
        Write-Host "=== Check passed ===" -ForegroundColor Green
    }

    "clean" {
        Write-Host "=== Cleaning remote build artifacts ===" -ForegroundColor Green
        Invoke-Remote "rm -rf $SourceDir"
        Write-Host "=== Clean completed ===" -ForegroundColor Green
    }
}
