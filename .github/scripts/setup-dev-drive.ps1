# Configure a fast drive for Windows CI jobs.
#
# GitHub-hosted Windows runners do not always expose a secondary D: volume. When
# they do not, create a Dev Drive VHD. CI depends on this path for its
# build directories where CI spends significant time doing I/O, so fail the
# job if no real Dev Drive is available.

function Test-DevDrive {
    param([string]$Drive)

    & fsutil devdrv query $Drive *> $null
    if ($LASTEXITCODE -ne 0) {
        return $false
    }

    # A Dev Drive marker alone is insufficient for the native ReFS refusal test.
    # Enforce the same local-volume contract as configure-windows-test-temp.ps1
    # before reusing D:, or provision a fresh verified ReFS VHD instead.
    $DriveLetter = $Drive.Substring(0, 1)
    $Volume = Get-Volume -DriveLetter $DriveLetter -ErrorAction Stop
    if ($Volume.FileSystem -ne "ReFS" -or $Volume.DriveType -ne "Fixed") {
        Write-Warning "$Drive advertises a Dev Drive but has $($Volume.FileSystem)/$($Volume.DriveType); refusing to reuse it."
        return $false
    }
    return $true
}

function Invoke-BestEffort {
    param([scriptblock]$Script, [string]$Description)

    try {
        & $Script
    } catch {
        Write-Warning "$Description failed: $($_.Exception.Message)"
    }
}

if ((Test-Path "D:\") -and (Test-DevDrive "D:")) {
    Write-Output "Using existing Dev Drive at D:"
    $Drive = "D:"
} else {
    if (Test-Path "D:\") {
        Write-Output "Existing D: volume is not a verified local ReFS Dev Drive; provisioning a new Dev Drive VHD."
    }

    try {
        $VhdPath = Join-Path $env:RUNNER_TEMP "codex-dev-drive.vhdx"
        $SizeBytes = 64GB

        if (Test-Path $VhdPath) {
            Remove-Item -Path $VhdPath -Force
        }

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
