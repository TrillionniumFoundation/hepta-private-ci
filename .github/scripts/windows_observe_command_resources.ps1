param([Parameter(Mandatory = $true)][string]$OutputDirectory)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$records = [System.Collections.Generic.List[object]]::new()
$programFiles = [Environment]::GetFolderPath("ProgramFiles")
$commands = @(
  @{ name = "cmd"; image = "$env:SystemRoot\System32\cmd.exe"; arguments = '/d /q /c "echo HEPTA_RESOURCE_READY& set /p HEPTA_RESOURCE_WAIT=& exit /b 0"' },
  @{ name = "pwsh"; image = "$programFiles\PowerShell\7\pwsh.exe"; arguments = '-NoLogo -NoProfile -Command "Write-Output HEPTA_RESOURCE_READY; [Console]::ReadLine() | Out-Null"' }
)
foreach ($command in $commands) {
  if (-not (Test-Path -LiteralPath $command.image -PathType Leaf)) {
    throw "Required native resource-probe executable is missing: $($command.image)"
  }
  $start = [System.Diagnostics.ProcessStartInfo]::new()
  $start.FileName = $command.image
  $start.Arguments = $command.arguments
  $start.UseShellExecute = $false
  $start.CreateNoWindow = $true
  $start.RedirectStandardInput = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $process = [System.Diagnostics.Process]::new()
  $process.StartInfo = $start
  $started = $false
  try {
    $started = $process.Start()
    if (-not $started) { throw "Native resource probe failed to start" }
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ([DateTime]::UtcNow -lt $deadline) {
      $read = $process.StandardOutput.ReadLineAsync()
      $remaining = [Math]::Max(1, [int]($deadline - [DateTime]::UtcNow).TotalMilliseconds)
      if (-not $read.Wait($remaining)) { throw "Native probe readiness deadline expired" }
      $line = $read.Result
      if ($null -eq $line) { throw "Native probe exited before readiness" }
      if ($line -eq "HEPTA_RESOURCE_READY") { $ready = $true; break }
    }
    if (-not $ready) { throw "Native probe never reported readiness" }
    $process.Refresh()
    $modules = @($process.Modules | ForEach-Object {
      $path = $_.FileName
      $acl = Get-Acl -LiteralPath $path
      [ordered]@{
        path = $path
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $path).Length
        owner = $acl.Owner
        sddl = $acl.Sddl
      }
    })
    $records.Add([ordered]@{
      command = $command.name
      image = $command.image
      arguments = $command.arguments
      process_id = $process.Id
      loaded_pe_modules = $modules
    })
    $process.StandardInput.WriteLine("complete")
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(10000)) { throw "Native probe did not exit after input" }
    if ($process.ExitCode -ne 0) { throw "Native probe exit was $($process.ExitCode)" }
  } finally {
    if ($started -and -not $process.HasExited) {
      $process.Kill($true)
      $process.WaitForExit()
    }
    $process.Dispose()
  }
}
$record = [ordered]@{
  scope = "Observed loaded PE resources for the recorded unsandboxed commands; not a complete arbitrary-script dependency closure or sandbox qualification"
  system_root = $env:SystemRoot
  program_files_environment = $env:ProgramFiles
  program_files_known_folder = $programFiles
  observations = $records
}
$record | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 (Join-Path $OutputDirectory "native-resources.json")
$records | ForEach-Object { Write-Host "$($_.command): $($_.loaded_pe_modules.Count) observed PE modules" }
