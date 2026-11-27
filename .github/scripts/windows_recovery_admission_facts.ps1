param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][string]$ExpectedHead
)
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'These observations require native Windows.' }
if ((git rev-parse HEAD).Trim() -ne $ExpectedHead) { throw 'Source head differs.' }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) { throw 'Tracked source changed.' }
$base = 'ab59a8288a3240cff8a23f82551e09764ebde79d'
$pinned = @{
    'codex-rs/state' = '7c6a420647468f7a94e346538b70f1baf4ebc2d6'
    'codex-rs/hepta-memory' = '0b32d659631c424e7f4c8b797d0f0281bad8cf38'
    'codex-rs/Cargo.lock' = 'd5478a5a59d147aaca0914ee698c0acbebcf1174'
}
foreach ($path in $pinned.Keys) {
    if ((git rev-parse "HEAD:$path").Trim() -ne $pinned[$path]) { throw "Measured source differs: $path" }
}
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
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(string text,uint revision,out IntPtr descriptor,out uint size);
 [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr pointer);
 [DllImport("kernel32.dll",SetLastError=true)] static extern bool FlushFileBuffers(SafeFileHandle file);
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool MoveFileExW(string source,string target,uint flags);
 public static SafeFileHandle CreatePrivateDirectory(string path,string currentUser) {
  IntPtr sd,buffer=IntPtr.Zero,text=IntPtr.Zero;uint size;
  if(!ConvertStringSecurityDescriptorToSecurityDescriptorW("O:"+currentUser+"D:P(A;OICI;FA;;;"+currentUser+")",1,out sd,out size)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
  try {
   string nt=@"\??\"+System.IO.Path.GetFullPath(path);
   buffer=Marshal.StringToHGlobalUni(nt);Unicode u=new Unicode{Length=checked((ushort)(nt.Length*2)),MaximumLength=checked((ushort)(nt.Length*2)),Buffer=buffer};
   text=Marshal.AllocHGlobal(Marshal.SizeOf<Unicode>());Marshal.StructureToPtr(u,text,false);
   Attributes a=new Attributes{Length=(uint)Marshal.SizeOf<Attributes>(),Root=IntPtr.Zero,Name=text,Flags=0x1040,Security=sd};IoStatus io;IntPtr file;
   int status=NtCreateFile(out file,0x12019f,ref a,out io,IntPtr.Zero,0x80,3,3,0x200021,IntPtr.Zero,0);
   if(status<0 || file==IntPtr.Zero || file==new IntPtr(-1)) throw new Exception("Private leaf NtCreateFile status "+status.ToString("X8"));
   return new SafeFileHandle(file,true);
  } finally {if(text!=IntPtr.Zero)Marshal.FreeHGlobal(text);if(buffer!=IntPtr.Zero)Marshal.FreeHGlobal(buffer);LocalFree(sd);}
 }
 public static object ObservePrivateCopyIo(string path) {
  string moved=path+"-renamed";object flushFacts;
  using(SafeFileHandle flush=CreateFileW(path,0xc0000000,7,IntPtr.Zero,3,0x2200000,IntPtr.Zero)) {
   int openError=flush.IsInvalid?Marshal.GetLastWin32Error():0;bool flushed=false;int flushError=0;
   if(!flush.IsInvalid){flushed=FlushFileBuffers(flush);if(!flushed)flushError=Marshal.GetLastWin32Error();}
   flushFacts=new {DesiredAccess="GENERIC_READ|GENERIC_WRITE",Flags="BACKUP_SEMANTICS|OPEN_REPARSE_POINT",OpenOk=!flush.IsInvalid,OpenError=openError,FlushAttempted=!flush.IsInvalid,FlushOk=flushed,FlushError=flushError};
  }
  var attempts=new System.Collections.Generic.List<object>();
  using(SafeFileHandle directory=CreateFileW(path,0x1200a0,7,IntPtr.Zero,3,0x2200000,IntPtr.Zero)) {
   if(directory.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
   int status;SafeFileHandle database=Relative(directory,"original.sqlite3",false,out status);
   if(database==null)throw new Exception("Retained database NtCreateFile status "+status.ToString("X8"));
   bool renamed;
   try {
    renamed=MoveFileExW(path,moved,1);int error=renamed?0:Marshal.GetLastWin32Error();
    attempts.Add(new {HeldDirectory=true,HeldDatabase=true,Ok=renamed,Error=error});
   } finally {database.Dispose();}
   if(!renamed){renamed=MoveFileExW(path,moved,1);int error=renamed?0:Marshal.GetLastWin32Error();attempts.Add(new {HeldDirectory=true,HeldDatabase=false,Ok=renamed,Error=error});}
   if(renamed)return new {Flush=flushFacts,RenameAttempts=attempts,FinalHomePath=moved};
  }
  bool last=MoveFileExW(path,moved,1);int finalError=last?0:Marshal.GetLastWin32Error();attempts.Add(new {HeldDirectory=false,HeldDatabase=false,Ok=last,Error=finalError});
  return new {Flush=flushFacts,RenameAttempts=attempts,FinalHomePath=last?moved:path};
 }
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool DefineDosDeviceW(uint flags,string name,string target);
 [DllImport("kernel32.dll",SetLastError=true)] static extern uint GetLogicalDrives();
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern uint QueryDosDeviceW(string name,char[] buffer,uint length);
 static string Identity(SafeFileHandle h) {Id id;if(!GetId(h,18,out id,(uint)Marshal.SizeOf<Id>()))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());return id.Volume.ToString("X16")+":"+id.Low.ToString("X16")+":"+id.High.ToString("X16");}
 public static object ObserveNamespaceSwap(string first,string second) {
  string drive=null;uint used=GetLogicalDrives();char[] query=new char[4096];
  for(char c='Z';c>='F';c--){if((used&(1u<<(c-'A')))!=0)continue;string name=c+":";uint size=QueryDosDeviceW(name,query,(uint)query.Length);int error=size==0?Marshal.GetLastWin32Error():0;if(size==0 && error==2){drive=name;break;}}
  if(drive==null)throw new Exception("No unused local DOS drive for bounded namespace observation");
  string a=@"\??\"+System.IO.Path.GetFullPath(first),b=@"\??\"+System.IO.Path.GetFullPath(second);bool definedA=false,definedB=false;
  try {
   if(!DefineDosDeviceW(9,drive,a))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());definedA=true;
   using(SafeFileHandle old=CreateFileW(@"\\?\"+drive+@"\",0x1200a0,7,IntPtr.Zero,3,0x2200000,IntPtr.Zero)) {
    if(old.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());int status;
    using(SafeFileHandle home=Relative(old,"same-private-home",true,out status)) {
     if(home==null)throw new Exception("Alias home NtCreateFile status "+status.ToString("X8"));
     using(SafeFileHandle db=Relative(home,"original.sqlite3",false,out status)) {
      if(db==null)throw new Exception("Alias database NtCreateFile status "+status.ToString("X8"));string before=Identity(old),heldDb=Identity(db);uint type=GetDriveTypeW(drive+@"\");
      if(!DefineDosDeviceW(15,drive,a))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());definedA=false;
      if(!DefineDosDeviceW(9,drive,b))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());definedB=true;
      using(SafeFileHandle next=CreateFileW(@"\\?\"+drive+@"\",0x1200a0,7,IntPtr.Zero,3,0x2200000,IntPtr.Zero)) {
       if(next.IsInvalid)throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
       return new {Drive=drive,DriveType=type,HeldDatabaseUnchanged=Identity(db)==heldDb,OldRootIdentity=before,NewRootIdentity=Identity(next),RootIdentityChanged=Identity(next)!=before};
      }
     }
    }
   }
  } finally {
   int error=0;if(definedB && !DefineDosDeviceW(15,drive,b))error=Marshal.GetLastWin32Error();if(definedA && !DefineDosDeviceW(15,drive,a))error=Marshal.GetLastWin32Error();if(error!=0)throw new System.ComponentModel.Win32Exception(error);
  }
 }
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
$privateRoot = Join-Path $OutputRoot 'atomic-private-home'
$created = [NativeRecoveryFacts]::CreatePrivateDirectory($privateRoot, $identity.User.Value)
$privateCreatedSnapshot = [NativeRecoveryFacts]::Snapshot($created)
$created.Dispose()
[System.IO.File]::WriteAllBytes((Join-Path $privateRoot 'original.sqlite3'), [System.Text.Encoding]::UTF8.GetBytes('original database bytes'))
$privateSecurityBefore = SecurityFacts $privateRoot
$privateIo = [NativeRecoveryFacts]::ObservePrivateCopyIo($privateRoot)
$privateSecurityAfter = SecurityFacts $privateIo.FinalHomePath
$aliasRoots = @((Join-Path $OutputRoot 'namespace-original'), (Join-Path $OutputRoot 'namespace-replacement'))
foreach ($aliasRoot in $aliasRoots) {
    New-Item -ItemType Directory -Path $aliasRoot | Out-Null
    $aliasHome = Join-Path $aliasRoot 'same-private-home'
    $directory = [NativeRecoveryFacts]::CreatePrivateDirectory($aliasHome, $identity.User.Value)
    $directory.Dispose()
    [System.IO.File]::WriteAllBytes((Join-Path $aliasHome 'original.sqlite3'), [System.Text.Encoding]::UTF8.GetBytes('same original bytes'))
}
$namespaceSwap = [NativeRecoveryFacts]::ObserveNamespaceSwap($aliasRoots[0], $aliasRoots[1])
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
        components=$components; database=$db; privateCreatedSnapshot=$privateCreatedSnapshot; privateSecurityBefore=$privateSecurityBefore; privateIo=$privateIo; privateSecurityAfter=$privateSecurityAfter; namespaceSwap=$namespaceSwap; measuredTrees=$pinned; authorityGranted=$false; nativeBackendQualification=$false; finalProductQualification=$false
    }
    $receipt | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $OutputRoot 'facts.json')
    $receipt | ConvertTo-Json -Depth 12
} finally { foreach ($handle in $held) { $handle.Dispose() } }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) { throw 'Tracked source changed during observation.' }
