$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:SystemDrive -notmatch '^[A-Za-z]:$') {
    throw 'SystemDrive must name a local drive'
}
$driveRoot = $env:SystemDrive + '\'
if (([System.IO.DriveInfo]::new($driveRoot)).DriveFormat -ne 'NTFS') {
    throw 'Private Windows CI state requires an NTFS system volume'
}
$userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$path = Join-Path $driveRoot ('hepta-ci-' + [Guid]::NewGuid().ToString('N').Substring(0, 16))

# Publish a new directory with its protected DACL in the CreateDirectory call.
# Never repair an existing shared temporary root after making it visible.
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class HeptaCiPrivateTemp
{
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Length;
        public IntPtr Descriptor;
        [MarshalAs(UnmanagedType.Bool)]
        public bool InheritHandle;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
        string descriptor, uint revision, out IntPtr result, out uint size);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateDirectoryW(string path, ref SecurityAttributes attributes);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr value);

    public static void Create(string path, string userSid)
    {
        IntPtr descriptor;
        uint size;
        string sddl = "O:" + userSid
            + "D:P(A;OICI;FA;;;" + userSid + ")(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)";
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, out descriptor, out size))
            throw new Win32Exception(Marshal.GetLastWin32Error());
        try
        {
            var attributes = new SecurityAttributes
            {
                Length = Marshal.SizeOf(typeof(SecurityAttributes)),
                Descriptor = descriptor,
                InheritHandle = false
            };
            if (!CreateDirectoryW(path, ref attributes))
                throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        finally
        {
            LocalFree(descriptor);
        }
    }
}
'@

[HeptaCiPrivateTemp]::Create($path, $userSid)
$acl = Get-Acl -LiteralPath $path
if (-not $acl.AreAccessRulesProtected -or
    $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -ne $userSid) {
    throw 'The newly created CI directory has an unexpected owner or DACL'
}
$expected = @($userSid, 'S-1-5-18', 'S-1-5-32-544') | Sort-Object -Unique
$observed = @()
foreach ($rule in $acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier])) {
    if ($rule.IsInherited -or
        $rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
        $rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl -or
        $rule.InheritanceFlags -ne (
            [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
        ) -or
        $rule.PropagationFlags -ne [System.Security.AccessControl.PropagationFlags]::None -or
        $rule.IdentityReference.Value -notin $expected) {
        throw 'The new CI directory contains an unexpected access grant'
    }
    $observed += $rule.IdentityReference.Value
}
if (Compare-Object $expected ($observed | Sort-Object -Unique)) {
    throw 'The new CI directory is missing a required owner/system/administrator grant'
}

$portablePath = $path.Replace('\', '/')
"HEPTA_CI_PRIVATE_TEMP_ROOT=$portablePath" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"TEMP=$portablePath" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
"TMP=$portablePath" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
@{
    path = $portablePath
    filesystem = 'NTFS'
    protected_dacl = $acl.AreAccessRulesProtected
    owner = $userSid
    allowed_principals = $expected
    purpose = 'Private native CI fixtures; original state-directory validators remain authoritative'
} | ConvertTo-Json -Compress | Write-Output
