param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("exec", "upload", "download")]
    [string]$Action,

    [Parameter(Mandatory=$true)]
    [string]$ConfigFile,

    [string]$Command,
    [string]$LocalPath,
    [string]$RemotePath
)

$config = @{}
Get-Content $ConfigFile -ErrorAction Stop | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]+?)\s*=\s*(.+?)\s*$') {
        $config[$matches[1].Trim()] = $matches[2].Trim()
    }
}

$serverIp = $config['server_ip']
$user = $config['user']
$keyFile = $config['key_file'] -replace '^~', $env:USERPROFILE

if (-not $serverIp -or -not $user -or -not $keyFile) {
    Write-Error "config.ini missing required fields: server_ip, user, key_file"
    exit 1
}

if (-not (Test-Path $keyFile)) {
    Write-Error "SSH key file not found: $keyFile"
    exit 1
}

$sshOpts = @("-i", $keyFile, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL", "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10")
$target = "${user}@${serverIp}"

switch ($Action) {
    "exec" {
        if (-not $Command) {
            Write-Error "exec action requires -Command parameter"
            exit 1
        }
        ssh @sshOpts $target $Command
    }
    "upload" {
        if (-not $LocalPath -or -not $RemotePath) {
            Write-Error "upload action requires -LocalPath and -RemotePath parameters"
            exit 1
        }
        if (-not (Test-Path $LocalPath)) {
            Write-Error "Local file not found: $LocalPath"
            exit 1
        }
        $item = Get-Item $LocalPath
        if ($item.PSIsContainer) {
            scp @sshOpts -r $LocalPath "${target}:${RemotePath}"
        } else {
            scp @sshOpts $LocalPath "${target}:${RemotePath}"
        }
    }
    "download" {
        if (-not $LocalPath -or -not $RemotePath) {
            Write-Error "download action requires -LocalPath and -RemotePath parameters"
            exit 1
        }
        scp @sshOpts "${target}:${RemotePath}" $LocalPath
    }
}
