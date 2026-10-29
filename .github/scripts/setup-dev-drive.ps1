# Configure a fast drive for Windows CI jobs.
#
# GitHub-hosted Windows runners do not always expose a secondary D: volume. When
# they do not, create a Dev Drive VHD. CI depends on this path for its
# build directories where CI spends significant time doing I/O, so fail the
# job if no real Dev Drive is available.

function Test-DevDrive {
    param([string]$Drive)

    if ($Drive -notmatch '^[A-Za-z]:$') {
        return $false
    }
    $Volume = Get-Volume -DriveLetter $Drive.Substring(0, 1) -ErrorAction Stop
    # A successful fsutil query does not establish the queried file system.
    # Dev Drive is specifically a local ReFS volume, so validate it explicitly.
    if ($Volume.FileSystem -ne "ReFS" -or $Volume.DriveType -ne "Fixed") {
        Write-Host "Volume $Drive is $($Volume.FileSystem)/$($Volume.DriveType), not a local ReFS Dev Drive."
        return $false
    }
    & fsutil devdrv query $Drive *> $null
    return $LASTEXITCODE -eq 0
}

function Invoke-BestEffort {
    param([scriptblock]$Script, [string]$Description)

    try {
        & $Script
    } catch {
        Write-Warning "$Description failed: $($_.Exception.Message)"
    }
}

if ($env:CI_BUILD_ROOT -and (Test-DevDrive $env:CI_BUILD_ROOT)) {
    Write-Output "Reusing verified Dev Drive at $env:CI_BUILD_ROOT"
    $Drive = $env:CI_BUILD_ROOT
} elseif ((Test-Path "D:\") -and (Test-DevDrive "D:")) {
    Write-Output "Using existing Dev Drive at D:"
    $Drive = "D:"
} else {
    if (Test-Path "D:\") {
        Write-Output "Existing D: volume is not a Dev Drive; provisioning a new Dev Drive VHD."
    }

    try {
        $VhdName = "codex-dev-drive-$([Guid]::NewGuid().ToString('N')).vhdx"
        $VhdPath = Join-Path $env:RUNNER_TEMP $VhdName
        $SizeBytes = 64GB

        New-VHD -Path $VhdPath -SizeBytes $SizeBytes -Dynamic -ErrorAction Stop | Out-Null
        $Mounted = Mount-VHD -Path $VhdPath -Passthru -ErrorAction Stop
        $Disk = $Mounted | Get-Disk -ErrorAction Stop
        $Disk | Initialize-Disk -PartitionStyle GPT -ErrorAction Stop
        $Partition = $Disk | New-Partition -AssignDriveLetter -UseMaximumSize -ErrorAction Stop
        $Volume = $Partition | Format-Volume -FileSystem ReFS -NewFileSystemLabel "CodexDevDrive" -DevDrive -Confirm:$false -Force -ErrorAction Stop

        $Drive = "$($Volume.DriveLetter):"

        if (-not (Test-DevDrive $Drive)) {
            throw "Provisioned volume at $Drive did not pass Dev Drive verification."
        }

        Invoke-BestEffort { fsutil devdrv trust $Drive } "Trusting Dev Drive $Drive"
        Invoke-BestEffort { fsutil devdrv enable /disallowAv } "Disabling AV filter attachment for Dev Drives"

        Write-Output "Using Dev Drive at $Drive"
    } catch {
        throw "Failed to create Dev Drive: $($_.Exception.Message)"
    }
}

"CI_BUILD_ROOT=$Drive" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
