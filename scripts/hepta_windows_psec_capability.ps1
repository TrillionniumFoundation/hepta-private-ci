# Read-only PSEC API diagnostics; never a sandbox qualification result.
# ABI: Microsoft processmodel.h and microsoft/mxc 46cd65c262fa41d260060bd77d2fbf676610ab58.
# Create/Close exports are observed but never invoked. No policy or child is created.
#requires -Version 7.0
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$module = [IntPtr]::Zero
$exitCode = 0
$names = @(
    'CreateProcessSecurityEnvironment',
    'CloseProcessSecurityEnvironment',
    'QueryProcessSecurityEnvironmentSupport',
    'IsProcessSecurityEnvironmentVersionSupported'
)
$report = [ordered]@{
    schema = 'hepta-windows-psec-read-only-capability-v1'
    powershell_version = $PSVersionTable.PSVersion.ToString()
    os_arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    process_arch = [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString()
    product_name = $null
    build = $null
    ubr = $null
    loaded_path = $null
    load_error = $null
    exports = [ordered]@{}
    query_support = $null
    query_version_1 = $null
    exception = $null
    release_error = $null
    diagnostic_status = 'NOT_COMPLETED'
    diagnostic_complete = $false
    process_environment_created = $false
    child_created = $false
    policy_enforcement_tested = $false
    counts_as_original20_pass = $false
    production_sandbox_admitted = $false
    whole_unit_qualified = $false
    power_loss_qualified = $false
}
foreach ($name in $names) {
    $report.exports[$name] = [ordered]@{ present = $null; win32_error = $null }
}

try {
    if (-not $IsWindows) { throw 'This diagnostic requires native Windows PowerShell 7.' }
    $osKey = Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $report.product_name = [string]$osKey.ProductName
    $report.build = [string]$osKey.CurrentBuildNumber
    $report.ubr = [uint32]$osKey.UBR
    if ($report.os_arch -notin @('X64', 'Arm64') -or $report.process_arch -ne $report.os_arch) {
        throw 'Use a native x64 or ARM64 process; emulation is not this probe scope.'
    }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

namespace HeptaWindowsPsecReadOnlyV1 {
    public static class Native {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        public static extern IntPtr LoadLibraryExW(string name, IntPtr file, uint flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
        public static extern IntPtr GetProcAddress(IntPtr module, string name);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        public static extern uint GetModuleFileNameW(IntPtr module, StringBuilder path, uint size);
        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool FreeLibrary(IntPtr module);

        [UnmanagedFunctionPointer(CallingConvention.Winapi)]
        public delegate int QuerySupport(out ulong flags);
        [UnmanagedFunctionPointer(CallingConvention.Winapi)]
        public delegate int QueryVersion(uint major, out byte available, out uint minor);
    }
}
'@
    $expectedPath = Join-Path ([Environment]::SystemDirectory) 'processmodel.dll'
    # LOAD_LIBRARY_SEARCH_SYSTEM32; no caller-supplied DLL, path or fallback.
    $module = [HeptaWindowsPsecReadOnlyV1.Native]::LoadLibraryExW(
        'processmodel.dll', [IntPtr]::Zero, 0x00000800)
    if ($module -eq [IntPtr]::Zero) {
        $report.load_error = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        $report.diagnostic_status = 'DLL_UNAVAILABLE'
    }
    else {
        $modulePath = [Text.StringBuilder]::new(32768)
        $length = [HeptaWindowsPsecReadOnlyV1.Native]::GetModuleFileNameW(
            $module, $modulePath, [uint32]$modulePath.Capacity)
        if ($length -eq 0 -or $length -ge $modulePath.Capacity) {
            throw 'Cannot obtain complete loaded module identity.'
        }
        if (-not [StringComparer]::OrdinalIgnoreCase.Equals($expectedPath, $modulePath.ToString())) {
            throw 'Loaded module is not the expected native System32 processmodel.dll.'
        }
        $report.loaded_path = $modulePath.ToString()
        $addresses = @{}
        foreach ($name in $names) {
            $address = [HeptaWindowsPsecReadOnlyV1.Native]::GetProcAddress($module, $name)
            $lastError = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            $addresses[$name] = $address
            $report.exports[$name].present = ($address -ne [IntPtr]::Zero)
            if ($address -eq [IntPtr]::Zero) { $report.exports[$name].win32_error = $lastError }
        }
        if ($report.exports.QueryProcessSecurityEnvironmentSupport.present) {
            $query = [Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer(
                $addresses.QueryProcessSecurityEnvironmentSupport,
                [HeptaWindowsPsecReadOnlyV1.Native+QuerySupport])
            [uint64]$flags = 0
            [int32]$hresult = $query.Invoke([ref]$flags)
            $report.query_support = [ordered]@{
                hresult = $hresult
                hresult_hex = ('0x{0:X8}' -f $hresult)
                flags_raw = $flags
                flags_hex = ('0x{0:X16}' -f $flags)
                response_valid = ($hresult -ge 0)
            }
        }
        if ($report.exports.IsProcessSecurityEnvironmentVersionSupported.present) {
            $version = [Runtime.InteropServices.Marshal]::GetDelegateForFunctionPointer(
                $addresses.IsProcessSecurityEnvironmentVersionSupported,
                [HeptaWindowsPsecReadOnlyV1.Native+QueryVersion])
            [byte]$available = 0
            [uint32]$minor = 0
            [int32]$hresult = $version.Invoke(1, [ref]$available, [ref]$minor)
            $report.query_version_1 = [ordered]@{
                requested_major = 1
                hresult = $hresult
                hresult_hex = ('0x{0:X8}' -f $hresult)
                available_raw = $available
                minor_raw = $minor
                response_valid = ($hresult -ge 0 -and $available -in @(0, 1))
            }
        }
        # Missing exports and failing HRESULTs stay explicit raw observations.
        # No version/support fallback, capability conclusion or test PASS is inferred.
        $report.diagnostic_status = 'EXPORTS_AND_QUERY_RESPONSES_RECORDED'
    }
    $report.diagnostic_complete = $true
}
catch {
    $report.exception = $_.ToString()
    $report.diagnostic_status = 'DIAGNOSTIC_ERROR'
    $exitCode = 1
    [Console]::Error.WriteLine($_.ToString())
}
finally {
    if ($module -ne [IntPtr]::Zero) {
        if (-not [HeptaWindowsPsecReadOnlyV1.Native]::FreeLibrary($module)) {
            $report.release_error = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            $exitCode = 1
        }
    }
}
$report | ConvertTo-Json -Depth 8
exit $exitCode
