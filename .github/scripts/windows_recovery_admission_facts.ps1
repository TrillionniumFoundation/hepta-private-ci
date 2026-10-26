param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ExpectedHead
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'These observations require native Windows.' }
if ((git rev-parse HEAD).Trim() -ne $ExpectedHead) { throw 'Source head differs.' }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) { throw 'Tracked source changed.' }
$base = '9a1f1f9b74391cf69e70e98f340cec0cb2fec03b'
if (@(git diff $base -- codex-rs/state codex-rs/Cargo.lock).Count -ne 0) { throw 'The measured state source differs from 9a.' }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class NativeRecoveryFacts {
 [StructLayout(LayoutKind.Sequential)] public struct Basic {public long Creation,Access,Write,Change; public uint Attributes;}
 [StructLayout(LayoutKind.Sequential)] public struct Standard {public long Allocated,Length; public uint Links; public byte DeletePending,Directory;}
 [StructLayout(LayoutKind.Sequential)] public struct Id {public ulong Volume,Low,High;}
 [StructLayout(LayoutKind.Sequential)] public struct Tag {public uint Attributes,ReparseTag;}
 [StructLayout(LayoutKind.Sequential)] struct Unicode {public ushort Length,MaximumLength;public IntPtr Buffer;}
 [StructLayout(LayoutKind.Sequential)] struct Attributes {public uint Length;public IntPtr Root,Name;public uint Flags;public IntPtr Security,Qos;}
 [StructLayout(LayoutKind.Sequential)] struct IoStatus {public IntPtr Status;public UIntPtr Information;}
 [DllImport("kernel32.dll", CharSet=CharSet.Unicode,SetLastError=true)] public static extern SafeFileHandle CreateFileW(string path,uint access,uint share,IntPtr security,uint disposition,uint flags,IntPtr template);
 [DllImport("kernel32.dll",SetLastError=true)] public static extern uint GetFileType(SafeFileHandle handle);
 [DllImport("kernel32.dll",SetLastError=true,EntryPoint="GetFileInformationByHandleEx")] static extern bool GetBasic(SafeFileHandle h,int kind,out Basic data,uint length);
 [DllImport("kernel32.dll",SetLastError=true,EntryPoint="GetFileInformationByHandleEx")] static extern bool GetStandard(SafeFileHandle h,int kind,out Standard data,uint length);
 [DllImport("kernel32.dll",SetLastError=true,EntryPoint="GetFileInformationByHandleEx")] static extern bool GetId(SafeFileHandle h,int kind,out Id data,uint length);
 [DllImport("kernel32.dll",SetLastError=true,EntryPoint="GetFileInformationByHandleEx")] static extern bool GetTag(SafeFileHandle h,int kind,out Tag data,uint length);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern uint GetDriveTypeW(string root);
 [DllImport("ntdll.dll")] static extern int NtCreateFile(out IntPtr file,uint access,ref Attributes attributes,out IoStatus status,IntPtr allocation,uint flags,uint share,uint disposition,uint options,IntPtr ea,uint eaLength);
 public static object Snapshot(SafeFileHandle h) {
  Basic basic; Standard standard; Id id; Tag tag;
  bool b=GetBasic(h,0,out basic,(uint)Marshal.SizeOf<Basic>());int be=Marshal.GetLastWin32Error();
  bool s=GetStandard(h,1,out standard,(uint)Marshal.SizeOf<Standard>());int se=Marshal.GetLastWin32Error();
  bool i=GetId(h,18,out id,(uint)Marshal.SizeOf<Id>());int ie=Marshal.GetLastWin32Error();
  bool t=GetTag(h,9,out tag,(uint)Marshal.SizeOf<Tag>());int te=Marshal.GetLastWin32Error();
  return new {Type=GetFileType(h),BasicOk=b,BasicError=be,Basic=basic,StandardOk=s,StandardError=se,Standard=standard,IdOk=i,IdError=ie,Id=new {Volume=id.Volume.ToString("X16"),Low=id.Low.ToString("X16"),High=id.High.ToString("X16")},TagOk=t,TagError=te,Tag=tag};
 }
 public static SafeFileHandle Relative(SafeFileHandle parent,string name,bool directory,out int status) {
  IntPtr buffer=Marshal.StringToHGlobalUni(name), text=IntPtr.Zero;
  try {Unicode u=new Unicode{Length=checked((ushort)(name.Length*2)),MaximumLength=checked((ushort)(name.Length*2)),Buffer=buffer};
   text=Marshal.AllocHGlobal(Marshal.SizeOf<Unicode>());Marshal.StructureToPtr(u,text,false);
   Attributes a=new Attributes{Length=(uint)Marshal.SizeOf<Attributes>(),Root=parent.DangerousGetHandle(),Name=text,Flags=0x40};IoStatus io;IntPtr result;
   status=NtCreateFile(out result,(directory?0x20u:1u)|0x80u|0x20000u|0x100000u,ref a,out io,IntPtr.Zero,0,7,1,0x200000u|0x20u|(directory?1u:0x40u),IntPtr.Zero,0);
   if(status<0 || result==IntPtr.Zero || result==new IntPtr(-1)) return null;
   return new SafeFileHandle(result,true);
  } finally {if(text!=IntPtr.Zero)Marshal.FreeHGlobal(text);Marshal.FreeHGlobal(buffer);}
 }
}
'@
function SecurityFacts([string]$Path) {
    $acl = Get-Acl -LiteralPath $Path
    $rules = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) | ForEach-Object {
        [ordered]@{ sid=$_.IdentityReference.Value; type=$_.AccessControlType.ToString(); rights=$_.FileSystemRights.ToString(); mask=[int]$_.FileSystemRights; inherited=$_.IsInherited; inheritance=$_.InheritanceFlags.ToString(); propagation=$_.PropagationFlags.ToString() }
    })
    return [ordered]@{ owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value; protected=$acl.AreAccessRulesProtected; rules=$rules }
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$caseRoot = Join-Path $OutputRoot 'default-private-home'
New-Item -ItemType Directory -Path $caseRoot | Out-Null
[System.IO.File]::WriteAllBytes((Join-Path $caseRoot 'original.sqlite3'), [System.Text.Encoding]::UTF8.GetBytes('original database bytes'))
$caseRoot = (Resolve-Path -LiteralPath $caseRoot).Path
$drive = [System.IO.Path]::GetPathRoot($caseRoot)
$rootHandle = [NativeRecoveryFacts]::CreateFileW(('\\?\' + $drive), 0x1000a0, 7, [IntPtr]::Zero, 3, 0x2200000, [IntPtr]::Zero)
if ($rootHandle.IsInvalid) { throw "Drive root open: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())" }
$held = [System.Collections.Generic.List[Microsoft.Win32.SafeHandles.SafeFileHandle]]::new()
$held.Add($rootHandle)
$components = @()
$current = $rootHandle
$prefix = $drive
try {
    foreach ($name in $caseRoot.Substring($drive.Length).Split('\', [StringSplitOptions]::RemoveEmptyEntries)) {
        $status = 0
        $next = [NativeRecoveryFacts]::Relative($current, $name, $true, [ref]$status)
        $prefix = Join-Path $prefix $name
        $row = [ordered]@{name=$name; ntstatus=$status; path=$prefix}
        if ($null -ne $next) { $held.Add($next); $row.snapshot=[NativeRecoveryFacts]::Snapshot($next); $current=$next } else { $components += $row; break }
        if ($prefix -eq $caseRoot) { $row.security=SecurityFacts $prefix }
        $components += $row
    }
    $status = 0
    $database = [NativeRecoveryFacts]::Relative($current, 'original.sqlite3', $false, [ref]$status)
    $db = [ordered]@{ntstatus=$status}
    if ($null -ne $database) { $held.Add($database); $db.snapshot=[NativeRecoveryFacts]::Snapshot($database); $db.security=SecurityFacts (Join-Path $caseRoot 'original.sqlite3') }
    $receipt = [ordered]@{
        schema='hepta.windows-recovery-admission-facts.v1'; sourceHead=$ExpectedHead; measuredStateBase=$base;
        status='OBSERVATION_ONLY'; currentUserSid=$identity.User.Value; currentOwnerSid=$identity.Owner.Value;
        platform=[Environment]::OSVersion.ToString(); drive=$drive; driveType=[NativeRecoveryFacts]::GetDriveTypeW($drive);
        components=$components; database=$db; authorityGranted=$false; nativeBackendQualification=$false; finalProductQualification=$false
    }
    $receipt | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $OutputRoot 'facts.json')
    $receipt | ConvertTo-Json -Depth 12
} finally { foreach ($handle in $held) { $handle.Dispose() } }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) { throw 'Tracked source changed during observation.' }
