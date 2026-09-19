use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;

use super::platform_adapter::NativePlatform;

const MAX_SESSION_REFERENCE_BYTES: usize = 1024;

/// Stores only opaque native-session references in the operating system's
/// credential facility. It must not become an authority or general secret store.
pub(crate) trait OpaqueSessionStore: Send + Sync {
    fn load(&self) -> Result<Option<String>>;
    fn save(&self, value: &str) -> Result<()>;
    fn delete(&self) -> Result<bool>;
}

#[derive(Clone, Debug)]
pub(crate) struct SystemSessionStore {
    platform: NativePlatform,
    service: String,
    account: String,
    windows_dpapi_path: PathBuf,
}

impl SystemSessionStore {
    pub(crate) fn new(
        platform: NativePlatform,
        service: String,
        account: String,
        windows_dpapi_path: PathBuf,
    ) -> Result<Self> {
        validate_id(&service, "session store service")?;
        validate_id(&account, "session store account")?;
        if !windows_dpapi_path.is_absolute() {
            bail!("Windows DPAPI session path must be absolute");
        }
        Ok(Self {
            platform,
            service,
            account,
            windows_dpapi_path,
        })
    }
}

impl OpaqueSessionStore for SystemSessionStore {
    fn load(&self) -> Result<Option<String>> {
        let value = match self.platform {
            NativePlatform::Macos => macos_load(&self.service, &self.account)?,
            NativePlatform::Linux => linux_load(&self.service, &self.account)?,
            NativePlatform::Windows => windows_load(&self.windows_dpapi_path)?,
            NativePlatform::Unsupported => {
                bail!("secure native session storage is unsupported on this OS")
            }
        };
        if let Some(value) = &value {
            validate_reference(value)?;
        }
        Ok(value)
    }

    fn save(&self, value: &str) -> Result<()> {
        validate_reference(value)?;
        match self.platform {
            NativePlatform::Macos => macos_save(&self.service, &self.account, value),
            NativePlatform::Linux => linux_save(&self.service, &self.account, value),
            NativePlatform::Windows => windows_save(&self.windows_dpapi_path, value),
            NativePlatform::Unsupported => {
                bail!("secure native session storage is unsupported on this OS")
            }
        }
    }

    fn delete(&self) -> Result<bool> {
        match self.platform {
            NativePlatform::Macos => macos_delete(&self.service, &self.account),
            NativePlatform::Linux => linux_delete(&self.service, &self.account),
            NativePlatform::Windows => windows_delete(&self.windows_dpapi_path),
            NativePlatform::Unsupported => {
                bail!("secure native session storage is unsupported on this OS")
            }
        }
    }
}

fn macos_load(service: &str, account: &str) -> Result<Option<String>> {
    let output = Command::new("security")
        .args(["find-generic-password", "-s", service, "-a", account, "-w"])
        .stdin(Stdio::null())
        .output()
        .context("read macOS Keychain native session reference")?;
    if output.status.success() {
        return Ok(Some(trim_secret_output(output.stdout)?));
    }
    if output.status.code() == Some(44) {
        return Ok(None);
    }
    bail!("macOS Keychain rejected native session lookup")
}

fn macos_save(service: &str, account: &str, value: &str) -> Result<()> {
    // `security` has no stdin password mode for this command. The stored value is
    // an opaque session reference, never a credential or authority token.
    let status = Command::new("security")
        .args([
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
            value,
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .context("write macOS Keychain native session reference")?;
    if !status.success() {
        bail!("macOS Keychain rejected native session save");
    }
    Ok(())
}

fn macos_delete(service: &str, account: &str) -> Result<bool> {
    let status = Command::new("security")
        .args(["delete-generic-password", "-s", service, "-a", account])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .context("delete macOS Keychain native session reference")?;
    match status.code() {
        Some(0) => Ok(true),
        Some(44) => Ok(false),
        _ => bail!("macOS Keychain rejected native session deletion"),
    }
}

fn linux_load(service: &str, account: &str) -> Result<Option<String>> {
    let output = Command::new("secret-tool")
        .args(["lookup", "service", service, "account", account])
        .stdin(Stdio::null())
        .output();
    let output = match output {
        Ok(output) => output,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            bail!("secret-tool is required for Linux native session storage")
        }
        Err(error) => return Err(error).context("read Linux secret service session reference"),
    };
    if output.status.success() {
        let value = trim_secret_output(output.stdout)?;
        return Ok((!value.is_empty()).then_some(value));
    }
    Ok(None)
}

fn linux_save(service: &str, account: &str, value: &str) -> Result<()> {
    let mut child = Command::new("secret-tool")
        .args([
            "store",
            "--label=Hepta native session",
            "service",
            service,
            "account",
            account,
        ])
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .context("start Linux secret service session save")?;
    let mut stdin = child.stdin.take().context("open secret-tool stdin")?;
    stdin
        .write_all(value.as_bytes())
        .context("write Linux secret service session reference")?;
    drop(stdin);
    if !child.wait()?.success() {
        bail!("Linux secret service rejected native session save");
    }
    Ok(())
}

fn linux_delete(service: &str, account: &str) -> Result<bool> {
    let status = Command::new("secret-tool")
        .args(["clear", "service", service, "account", account])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .context("delete Linux secret service session reference")?;
    Ok(status.success())
}

fn windows_load(path: &Path) -> Result<Option<String>> {
    if !path.exists() {
        return Ok(None);
    }
    const SCRIPT: &str = r#"
$ErrorActionPreference='Stop'
$bytes=[IO.File]::ReadAllBytes($args[0])
$plain=[Security.Cryptography.ProtectedData]::Unprotect($bytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
[Console]::Out.Write([Text.Encoding]::UTF8.GetString($plain))
"#;
    let output = powershell_with_path(SCRIPT, path).output()?;
    if !output.status.success() {
        bail!("Windows DPAPI rejected native session load");
    }
    Ok(Some(trim_secret_output(output.stdout)?))
}

fn windows_save(path: &Path, value: &str) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).context("create Windows DPAPI session parent")?;
    }
    const SCRIPT: &str = r#"
$ErrorActionPreference='Stop'
$value=[Console]::In.ReadToEnd()
$plain=[Text.Encoding]::UTF8.GetBytes($value)
$protected=[Security.Cryptography.ProtectedData]::Protect($plain,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
[IO.File]::WriteAllBytes($args[0],$protected)
"#;
    let mut child = powershell_with_path(SCRIPT, path)
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    child
        .stdin
        .take()
        .context("open PowerShell DPAPI stdin")?
        .write_all(value.as_bytes())?;
    if !child.wait()?.success() {
        bail!("Windows DPAPI rejected native session save");
    }
    Ok(())
}

fn windows_delete(path: &Path) -> Result<bool> {
    if !path.exists() {
        return Ok(false);
    }
    std::fs::remove_file(path).context("delete Windows DPAPI native session reference")?;
    Ok(true)
}

fn powershell_with_path(script: &str, path: &Path) -> Command {
    let mut command = Command::new("powershell.exe");
    command
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            "--",
        ])
        .arg(path)
        .stdin(Stdio::null());
    command
}

fn trim_secret_output(bytes: Vec<u8>) -> Result<String> {
    let value = String::from_utf8(bytes).context("native session reference is not UTF-8")?;
    Ok(value.trim_end_matches(&['\r', '\n'][..]).to_string())
}

fn validate_reference(value: &str) -> Result<()> {
    if value.is_empty() || value.len() > MAX_SESSION_REFERENCE_BYTES || value.contains('\0') {
        bail!("opaque native session reference is invalid");
    }
    Ok(())
}

fn validate_id(value: &str, name: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        bail!("{name} is not a bounded stable identifier");
    }
    Ok(())
}
