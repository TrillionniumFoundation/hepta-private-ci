#![cfg(windows)]

use std::path::PathBuf;
use std::process::Command;

#[test]
fn packaged_identity_registrar_csharp_compiles_in_system_powershell() {
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
    let output = Command::new(executable)
        .env("HEPTA_REGISTRAR_SOURCE", source)
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$ErrorActionPreference = 'Stop'; Add-Type -TypeDefinition $env:HEPTA_REGISTRAR_SOURCE; [Hepta.Native.WindowsIdentity.Registrar] | Out-Null",
        ])
        .output()
        .unwrap();
    assert!(output.status.success(), "{output:?}");
}
