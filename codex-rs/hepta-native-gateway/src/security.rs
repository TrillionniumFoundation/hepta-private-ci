use std::fs::File;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;

use super::platform_adapter::NativePlatform;
use super::shell_runtime::GrantVerifier;
use super::shell_runtime::PlatformAction;
use super::shell_runtime::PlatformRequest;
use super::shell_runtime::SessionKey;
use super::shell_runtime::VerifiedPlatformGrant;

const GRANT_VERSION: &str = "native-grant-v1";
const MAX_GRANT_LIFETIME: Duration = Duration::from_secs(5 * 60);
const CLOCK_SKEW: Duration = Duration::from_secs(30);
const MAX_GRANT_BYTES: usize = 16 * 1024;

/// Verifies a detached signature over the exact canonical grant bytes.
/// Implementations receive only public verification material and must never
/// accept a signature merely because its payload fields are syntactically valid.
pub(crate) trait DetachedSignatureVerifier: Send + Sync {
    fn verify(&self, message: &[u8], signature: &[u8]) -> Result<bool>;
}

#[derive(Clone, Debug)]
pub(crate) struct SystemDetachedSignatureVerifier {
    platform: NativePlatform,
    public_key: PathBuf,
}

impl SystemDetachedSignatureVerifier {
    pub(crate) fn new(platform: NativePlatform, public_key: PathBuf) -> Result<Self> {
        if !public_key.is_absolute() {
            bail!("native grant public key path must be absolute");
        }
        validate_public_key(&public_key)?;
        Ok(Self {
            platform,
            public_key,
        })
    }
}

impl DetachedSignatureVerifier for SystemDetachedSignatureVerifier {
    fn verify(&self, message: &[u8], signature: &[u8]) -> Result<bool> {
        let directory = std::env::temp_dir().join(format!(
            "hepta-native-signature-{}-{}",
            std::process::id(),
            now_millis()?
        ));
        std::fs::create_dir(&directory).context("create native signature verification directory")?;
        let message_path = directory.join("grant.bin");
        let signature_path = directory.join("grant.sig");
        write_private_file(&message_path, message)?;
        write_private_file(&signature_path, signature)?;
        let result = match self.platform {
            NativePlatform::Windows => verify_windows(
                &self.public_key,
                &message_path,
                &signature_path,
            ),
            NativePlatform::Macos | NativePlatform::Linux => verify_openssl(
                &self.public_key,
                &message_path,
                &signature_path,
            ),
            NativePlatform::Unsupported => Ok(false),
        };
        let _ = std::fs::remove_file(&message_path);
        let _ = std::fs::remove_file(&signature_path);
        let _ = std::fs::remove_dir(&directory);
        result
    }
}

pub(crate) struct SignedGrantVerifier<V> {
    signatures: V,
}

impl<V> SignedGrantVerifier<V>
where
    V: DetachedSignatureVerifier,
{
    pub(crate) fn new(signatures: V) -> Self {
        Self { signatures }
    }
}

impl<V> GrantVerifier for SignedGrantVerifier<V>
where
    V: DetachedSignatureVerifier,
{
    fn verify(
        &self,
        session: &SessionKey,
        request: &PlatformRequest,
    ) -> Result<VerifiedPlatformGrant> {
        if request.grant.len() > MAX_GRANT_BYTES {
            bail!("native platform grant exceeds {MAX_GRANT_BYTES} bytes");
        }
        let fields = request.grant.split('|').collect::<Vec<_>>();
        let [version, session_id, generation, operation_id, action, payload_digest, not_before, expires, issuer, signature_hex] =
            fields.as_slice()
        else {
            bail!("native platform grant field count is invalid");
        };
        if *version != GRANT_VERSION {
            bail!("native platform grant version is not supported");
        }
        validate_id(session_id, "grant session")?;
        validate_id(operation_id, "grant operation")?;
        validate_id(issuer, "grant issuer")?;
        validate_digest(payload_digest)?;
        let generation = generation
            .parse::<u64>()
            .context("parse native grant generation")?;
        let action = parse_action(action)?;
        let not_before = millis_to_duration(not_before, "grant not-before")?;
        let expires = millis_to_duration(expires, "grant expiry")?;
        if expires <= not_before || expires - not_before > MAX_GRANT_LIFETIME {
            bail!("native platform grant lifetime is invalid");
        }
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .context("system clock precedes unix epoch")?;
        if now + CLOCK_SKEW < not_before || now > expires + CLOCK_SKEW {
            bail!("native platform grant is not currently valid");
        }
        if *session_id != session.session_id
            || generation != session.generation
            || *operation_id != request.operation_id
            || action != request.action
            || *payload_digest != request.payload_digest
        {
            bail!("native platform grant does not bind the final operation");
        }

        let signature = decode_hex(signature_hex)?;
        let signed_message = fields[..9].join("|");
        if !self
            .signatures
            .verify(signed_message.as_bytes(), &signature)?
        {
            bail!("native platform grant signature is invalid");
        }
        Ok(VerifiedPlatformGrant {
            session: session.clone(),
            operation_id: request.operation_id.clone(),
            action: request.action,
            payload_digest: request.payload_digest.clone(),
        })
    }
}

fn verify_openssl(public_key: &Path, message: &Path, signature: &Path) -> Result<bool> {
    let status = Command::new("openssl")
        .args(["dgst", "-sha256", "-verify"])
        .arg(public_key)
        .arg("-signature")
        .arg(signature)
        .arg(message)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    match status {
        Ok(status) => Ok(status.success()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            bail!("openssl is required for native grant verification")
        }
        Err(error) => Err(error).context("execute openssl grant verification"),
    }
}

fn verify_windows(public_key: &Path, message: &Path, signature: &Path) -> Result<bool> {
    const SCRIPT: &str = r#"
$ErrorActionPreference = 'Stop'
$pem = [IO.File]::ReadAllText($args[0])
$data = [IO.File]::ReadAllBytes($args[1])
$sig = [IO.File]::ReadAllBytes($args[2])
$rsa = [Security.Cryptography.RSA]::Create()
try {
  $rsa.ImportFromPem($pem)
  if ($rsa.VerifyData($data, $sig, [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)) { exit 0 }
  exit 3
} finally { $rsa.Dispose() }
"#;
    let status = Command::new("powershell.exe")
        .args(["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", SCRIPT, "--"])
        .arg(public_key)
        .arg(message)
        .arg(signature)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .context("execute PowerShell grant verification")?;
    match status.code() {
        Some(0) => Ok(true),
        Some(3) => Ok(false),
        _ => bail!("PowerShell native grant verifier failed"),
    }
}

fn validate_public_key(path: &Path) -> Result<()> {
    let metadata = path.metadata().context("inspect native grant public key")?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > 64 * 1024 {
        bail!("native grant public key must be a non-empty bounded file");
    }
    Ok(())
}

fn write_private_file(path: &Path, bytes: &[u8]) -> Result<()> {
    let mut options = std::fs::OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).context("create signature verification input")?;
    file.write_all(bytes).context("write signature verification input")?;
    file.sync_all().context("sync signature verification input")
}

fn now_millis() -> Result<u128> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .context("system clock precedes unix epoch")?
        .as_millis())
}

fn millis_to_duration(value: &str, name: &str) -> Result<Duration> {
    let millis = value.parse::<u64>().with_context(|| format!("parse {name}"))?;
    Ok(Duration::from_millis(millis))
}

fn parse_action(value: &str) -> Result<PlatformAction> {
    match value {
        "open_path" => Ok(PlatformAction::OpenPath),
        "reveal_path" => Ok(PlatformAction::RevealPath),
        "copy_text" => Ok(PlatformAction::CopyText),
        "notify" => Ok(PlatformAction::Notify),
        _ => bail!("native platform grant action is not registered"),
    }
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

fn validate_digest(value: &str) -> Result<()> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value.bytes().all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    {
        bail!("native platform grant payload digest is invalid");
    }
    Ok(())
}

fn decode_hex(value: &str) -> Result<Vec<u8>> {
    if value.is_empty() || value.len() > 16 * 1024 || !value.len().is_multiple_of(2) {
        bail!("native platform grant signature encoding is invalid");
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|pair| {
            let high = hex_nibble(pair[0])?;
            let low = hex_nibble(pair[1])?;
            Ok((high << 4) | low)
        })
        .collect()
}

fn hex_nibble(value: u8) -> Result<u8> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => bail!("native platform grant signature must use lowercase hexadecimal"),
    }
}
