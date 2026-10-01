#![cfg(windows)]

use std::path::PathBuf;
use std::process::Command;

#[test]
fn packaged_identity_registrar_has_native_layout_and_round_trips_owned_shortcut() {
    let script =
        include_str!("../packaging/windows/Register-HeptaNativeIdentity.ps1").replace("\r\n", "\n");
    let source = script
        .split_once("Add-Type -TypeDefinition @'\n")
        .unwrap()
        .1
        .split_once("\n'@")
        .unwrap()
        .0;
    let executable = PathBuf::from(std::env::var_os("SystemRoot").unwrap())
        .join("System32/WindowsPowerShell/v1.0/powershell.exe");
    let fixture = tempfile::tempdir().unwrap();
    let shortcut = fixture.path().join("identity.lnk");
    let output = Command::new(executable)
        .env("HEPTA_REGISTRAR_SOURCE", source)
        .env("HEPTA_REGISTRAR_SHORTCUT", &shortcut)
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            r#"
$ErrorActionPreference = 'Stop'
$probe = @'
namespace Hepta.Native.WindowsIdentity {
    public static class RegistrarRoundTripProbe {
        [DllImport("ole32.dll", ExactSpelling = true)]
        static extern int PropVariantClear(ref PropVariant value);

        public static int SizeOfPropVariant() {
            return Marshal.SizeOf(typeof(PropVariant));
        }

        public static string ReadAppUserModelId(string path) {
            object link = new ShellLink();
            var value = new PropVariant();
            IntPtr buffer = IntPtr.Zero;
            try {
                var persist = (IPersistFile)link;
                persist.Load(path, 0);
                var store = (IPropertyStore)link;
                var key = new PropertyKey(
                    new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
                store.GetValue(ref key, out value);
                buffer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(PropVariant)));
                Marshal.StructureToPtr(value, buffer, false);
                if (Marshal.ReadInt16(buffer) != 31) {
                    throw new InvalidOperationException("shortcut identity is not VT_LPWSTR");
                }
                return Marshal.PtrToStringUni(Marshal.ReadIntPtr(buffer, 8));
            } finally {
                if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
                PropVariantClear(ref value);
                Marshal.FinalReleaseComObject(link);
            }
        }
    }
}
'@
Add-Type -TypeDefinition ($env:HEPTA_REGISTRAR_SOURCE + "`n" + $probe)
$variantType = [Hepta.Native.WindowsIdentity.PropVariant]
$expectedSize = if ([IntPtr]::Size -eq 8) { 24 } else { 16 }
if ([Hepta.Native.WindowsIdentity.RegistrarRoundTripProbe]::SizeOfPropVariant() -ne $expectedSize) {
    throw 'PROPVARIANT size differs from the native SDK layout'
}
if ([System.Runtime.InteropServices.Marshal]::OffsetOf($variantType, 'valueType').ToInt32() -ne 0 -or
    [System.Runtime.InteropServices.Marshal]::OffsetOf($variantType, 'pointerValue').ToInt32() -ne 8 -or
    [System.Runtime.InteropServices.Marshal]::OffsetOf($variantType, 'CountedValue').ToInt32() -ne 8) {
    throw 'PROPVARIANT fields differ from the native SDK offsets'
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($env:HEPTA_REGISTRAR_SHORTCUT)
try {
    $shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
    $shortcut.Save()
} finally {
    [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
    [System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
}
$identity = 'Trillionnium.Hepta.Native.Fixture'
[Hepta.Native.WindowsIdentity.Registrar]::SetAppUserModelId(
    $env:HEPTA_REGISTRAR_SHORTCUT, $identity)
$observed = [Hepta.Native.WindowsIdentity.RegistrarRoundTripProbe]::ReadAppUserModelId(
    $env:HEPTA_REGISTRAR_SHORTCUT)
if ($observed -ne $identity) {
    throw 'owned shortcut AppUserModelID did not round-trip'
}
"#,
        ])
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
}
