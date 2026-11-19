//! One fresh desktop role per native launch; never reconstructed from wire data.
use crate::token::LocalSid;
use anyhow::Context;
use anyhow::Result;
use rand::RngCore;
use rand::rngs::OsRng;

/// Separates a private desktop's authority from filesystem and route roles.
/// Creation declares an identity, and does not qualify a token or a launch.
pub struct DesktopCapability {
    sid: LocalSid,
}

impl DesktopCapability {
    /// Generates an independent 128-bit session identity from the OS CSPRNG.
    pub fn create() -> Result<Self> {
        let mut bytes = [0u8; 16];
        OsRng
            .try_fill_bytes(&mut bytes)
            .context("generate private desktop capability")?;
        let words: Vec<_> = bytes
            .chunks_exact(4)
            .map(|chunk| u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
            .collect();
        let sid = LocalSid::from_string(&format!(
            "S-1-5-21-{}-{}-{}-{}",
            words[0], words[1], words[2], words[3]
        ))?;
        Ok(Self { sid })
    }

    /// Supplies only the desktop identity to the role-aware token constructor.
    pub fn as_sid(&self) -> &LocalSid {
        &self.sid
    }
}
