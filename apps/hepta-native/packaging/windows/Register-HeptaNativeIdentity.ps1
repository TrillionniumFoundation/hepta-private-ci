[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateScript({ Test-Path -LiteralPath $_ -PathType Leaf })]
    [string]$Executable,

    [string]$AppUserModelId = 'Trillionnium.Hepta.Native'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Executable = (Resolve-Path -LiteralPath $Executable).Path
$startMenu = [Environment]::GetFolderPath('Programs')
if ([string]::IsNullOrWhiteSpace($startMenu)) { throw 'per-user Start Menu directory is unavailable' }
$shortcutPath = Join-Path $startMenu 'Hepta Native.lnk'

# Create the link through the supported Windows Script Host owner, then set the
# explicit AppUserModelID through IPropertyStore. The marker is written only
# after both durable objects have been committed successfully.
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $Executable
$shortcut.WorkingDirectory = Split-Path -Parent $Executable
$shortcut.Description = 'Hepta Native'
$shortcut.IconLocation = "$Executable,0"
$shortcut.Save()

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

namespace Hepta.Native.WindowsIdentity {
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct PropertyKey {
        public Guid FormatId;
        public uint PropertyId;
        public PropertyKey(Guid formatId, uint propertyId) {
            FormatId = formatId;
            PropertyId = propertyId;
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct CountedArray {
        public uint ElementCount;
        public IntPtr Elements;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct PropVariant : IDisposable {
        [FieldOffset(0)] private ushort valueType;
        [FieldOffset(8)] private IntPtr pointerValue;
        // The SDK union includes counted arrays: its size is 16 on x64 and
        // 8 on x86. Keep that native extent even for the string-only writer.
        [FieldOffset(8)] public CountedArray CountedValue;

        public static PropVariant FromString(string value) {
            var variant = new PropVariant();
            variant.valueType = 31; // VT_LPWSTR
            variant.pointerValue = Marshal.StringToCoTaskMemUni(value);
            return variant;
        }

        public void Dispose() {
            if (pointerValue != IntPtr.Zero) {
                Marshal.FreeCoTaskMem(pointerValue);
                pointerValue = IntPtr.Zero;
            }
        }
    }

    [ComImport]
    [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IPropertyStore {
        uint GetCount();
        void GetAt(uint propertyIndex, out PropertyKey key);
        void GetValue(ref PropertyKey key, out PropVariant value);
        void SetValue(ref PropertyKey key, ref PropVariant value);
        void Commit();
    }

    [ComImport]
    [Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink { }

    public static class Registrar {
        static readonly PropertyKey AppUserModelId = new PropertyKey(
            new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);

        public static void SetAppUserModelId(string shortcutPath, string appUserModelId) {
            object link = new ShellLink();
            var persist = (IPersistFile)link;
            persist.Load(shortcutPath, 2); // STGM_READWRITE
            var store = (IPropertyStore)link;
            var value = PropVariant.FromString(appUserModelId);
            try {
                var key = AppUserModelId;
                store.SetValue(ref key, ref value);
                store.Commit();
                persist.Save(shortcutPath, true);
            } finally {
                value.Dispose();
                Marshal.FinalReleaseComObject(store);
                Marshal.FinalReleaseComObject(persist);
            }
        }
    }
}
'@

[Hepta.Native.WindowsIdentity.Registrar]::SetAppUserModelId($shortcutPath, $AppUserModelId)
$identityDirectory = Join-Path $env:LOCALAPPDATA 'Hepta\identity'
New-Item -ItemType Directory -Force -Path $identityDirectory | Out-Null
$marker = Join-Path $identityDirectory 'aumid.txt'
$temp = "$marker.tmp-$PID"
[IO.File]::WriteAllText($temp, "$AppUserModelId`n", [Text.UTF8Encoding]::new($false))
Move-Item -LiteralPath $temp -Destination $marker -Force
Write-Output "Registered $AppUserModelId at $shortcutPath"
