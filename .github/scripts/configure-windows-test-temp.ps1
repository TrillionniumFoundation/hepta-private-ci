# Test state needs the directory-flush durability contract of local NTFS.
# MS-FSA section 2.1.5.7, product behavior note <80>, explicitly says other
# file systems can acknowledge a directory flush without persisting anything:
# https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/4e3695bd-7574-4f24-a223-b4679c065b63
# Keep build outputs on the Dev Drive; run filesystem tests on a verified volume.
$ErrorActionPreference = "Stop"

$SystemDriveRoot = [System.IO.Path]::GetPathRoot($env:SystemRoot)
if ($SystemDriveRoot -notmatch '^[A-Za-z]:\\$') {
    throw "SystemRoot must identify a local drive for durable-state tests."
}
$SystemVolume = Get-Volume -DriveLetter $SystemDriveRoot.Substring(0, 1) -ErrorAction Stop
if ($SystemVolume.FileSystem -ne "NTFS" -or $SystemVolume.DriveType -ne "Fixed") {
    throw "Durable-state tests require a local fixed NTFS volume; SystemRoot uses $($SystemVolume.FileSystem)/$($SystemVolume.DriveType)."
}

# AF_UNIX sockets append the fleet and agent identity below this directory.
# Keep the random component compact; run/job identity belongs in the log, not
# in every test path. Exclusive creation still rejects a nonce collision.
$TestDirectoryName = [Guid]::NewGuid().ToString("N").Substring(0, 24)
$TestParent = Join-Path $SystemDriveRoot "ct"
New-Item -ItemType Directory -Path $TestParent -Force -ErrorAction Stop | Out-Null
$TestTemp = Join-Path $TestParent $TestDirectoryName
New-Item -ItemType Directory -Path $TestTemp -ErrorAction Stop | Out-Null
$TestVolume = Get-Volume -FilePath $TestTemp -ErrorAction Stop
if ($TestVolume.FileSystem -ne "NTFS" -or $TestVolume.DriveType -ne "Fixed") {
    throw "Created test directory did not resolve to local NTFS."
}

"TEMP=$TestTemp" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"TMP=$TestTemp" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
Write-Output "Test temporary files: $TestTemp (local $($SystemVolume.FileSystem)); run $env:GITHUB_RUN_ID attempt $env:GITHUB_RUN_ATTEMPT job $env:GITHUB_JOB; build outputs remain at $env:CI_BUILD_ROOT."

# Exercise refusal on the real ReFS Dev Drive in addition to NTFS success cases.
$BuildDriveRoot = [System.IO.Path]::GetPathRoot("$env:CI_BUILD_ROOT\")
if ($BuildDriveRoot -notmatch '^[A-Za-z]:\\$') {
    throw "CI_BUILD_ROOT must identify the configured local Dev Drive."
}
$BuildVolume = Get-Volume -DriveLetter $BuildDriveRoot.Substring(0, 1) -ErrorAction Stop
if ($BuildVolume.FileSystem -ne "ReFS" -or $BuildVolume.DriveType -ne "Fixed") {
    throw "The configured Dev Drive must be local ReFS for the unsupported-volume regression; $BuildDriveRoot is $($BuildVolume.FileSystem)/$($BuildVolume.DriveType)."
}
"CODEX_TEST_REFS_VOLUME=$BuildDriveRoot" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
