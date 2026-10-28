param(
    [Parameter(Mandatory = $true)][string]$RepositoryRoot,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) { throw 'This diagnostic requires Windows.' }
$repo = [IO.Path]::GetFullPath($RepositoryRoot)
$temp = [IO.Path]::GetFullPath($env:RUNNER_TEMP)
$evidence = [IO.Path]::GetFullPath($EvidenceDirectory)
$prefix = $temp.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $evidence.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Evidence must be a new directory under RUNNER_TEMP.'
}
if (Test-Path -LiteralPath $evidence) { throw 'Evidence directory already exists.' }
New-Item -ItemType Directory -Path $evidence | Out-Null
$probe = Join-Path $temp ('hepta-token-probe-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $probe 'src') | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
try {
    $bindings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-bindings.json') -Raw | ConvertFrom-Json
    $verified = @()
    foreach ($entry in $bindings.files) {
        $source = Join-Path $repo $entry.path
        $actual = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $entry.sha256) { throw "Source binding mismatch: $($entry.path): $actual" }
        $verified += [ordered]@{path=$entry.path; sha256=$actual; git_blob=$entry.git_blob}
        if ([IO.Path]::GetFileName($source) -ne 'winutil.rs') {
            Copy-Item -LiteralPath $source -Destination (Join-Path (Join-Path $probe 'src') ([IO.Path]::GetFileName($source)))
        }
    }
    $winutil = [IO.File]::ReadAllText((Join-Path $repo 'codex-rs/windows-sandbox-rs/src/winutil.rs'))
    $wide = [regex]::Matches($winutil, '(?ms)^pub fn to_wide<S: AsRef<OsStr>>\(s: S\) -> Vec<u16> \{.*?^\}')
    if ($wide.Count -ne 1) { throw 'Exact to_wide function could not be extracted.' }
    $shim = "use std::ffi::OsStr;`nuse std::os::windows::ffi::OsStrExt;`n`n" + $wide[0].Value + "`n"
    [IO.File]::WriteAllText((Join-Path $probe 'src/winutil.rs'), $shim, $utf8)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Cargo.toml') -Destination (Join-Path $probe 'Cargo.toml')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'src/main.rs') -Destination (Join-Path $probe 'src/main.rs')
    $head = & git -C $repo rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Cannot bind diagnostic checkout HEAD.' }
    $identity = [ordered]@{
        diagnostic_checkout_head=$head
        bound_repository_source_head=$bindings.source_head
        source_files=$verified
        generated_to_wide_sha256=(Get-FileHash -LiteralPath (Join-Path $probe 'src/winutil.rs') -Algorithm SHA256).Hash.ToLowerInvariant()
        diagnostic_main_sha256=(Get-FileHash -LiteralPath (Join-Path $probe 'src/main.rs') -Algorithm SHA256).Hash.ToLowerInvariant()
        constructor_configuration=$bindings.actual_configuration
        limitations=$bindings.limits
    }
    $identityJson = $identity | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText((Join-Path $probe 'src/source-identity.json'), $identityJson, $utf8)
    [IO.File]::WriteAllText((Join-Path $evidence 'source-identity.json'), $identityJson, $utf8)
    & rustc +1.95.0 --version --verbose *> (Join-Path $evidence 'rustc-version.log')
    if ($LASTEXITCODE -ne 0) { throw 'Rust 1.95.0 is unavailable.' }
    & cargo +1.95.0 generate-lockfile --manifest-path (Join-Path $probe 'Cargo.toml') *> (Join-Path $evidence 'resolve.log')
    if ($LASTEXITCODE -ne 0) { throw 'Probe dependency resolution failed.' }
    Copy-Item -LiteralPath (Join-Path $probe 'Cargo.lock') -Destination (Join-Path $evidence 'Cargo.lock')
    Copy-Item -LiteralPath (Join-Path $probe 'src') -Destination (Join-Path $evidence 'compiled-source') -Recurse
    & cargo +1.95.0 run --locked --manifest-path (Join-Path $probe 'Cargo.toml') -- (Join-Path $evidence 'native-probe.json') *> (Join-Path $evidence 'native-probe.log')
    if ($LASTEXITCODE -ne 0) { throw 'Native probe failed; raw log and any partial JSON have been retained.' }
    $report = Get-Content -LiteralPath (Join-Path $evidence 'native-probe.json') -Raw | ConvertFrom-Json
    Write-Host ('evidence_complete=' + $report.evidence_complete)
    Write-Host 'This job measures a known failure and candidate counterexamples; successful execution is not a security qualification.'
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $evidence 'entry-error.log')
    throw
} finally {
    # Only the fresh build directory created above is removed. The executable
    # creates and owns its own TempDir; no production root is accepted as input.
    if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Recurse -Force }
    Get-ChildItem -LiteralPath $evidence -File -Recurse | ForEach-Object {
        [ordered]@{path=$_.FullName.Substring($evidence.Length + 1); sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); bytes=$_.Length}
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidence 'artifact-hashes.json')
}
