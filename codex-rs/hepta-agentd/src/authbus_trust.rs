//! One explicitly installed owner key and bounded thread allowlist.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use codex_hepta_authbus::IssuerRegistration;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;

use crate::AgentdError;
use crate::AgentdIdentity;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TextTrust {
    schema_version: u32,
    agent_id: String,
    issuer_id: String,
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    #[serde(default)]
    not_before_ms: Option<u64>,
    #[serde(default)]
    not_after_ms: Option<u64>,
    #[serde(default)]
    previous_epochs: Vec<TrustEpoch>,
    thread_ids: Vec<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustEpoch {
    key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    #[serde(default)]
    not_before_ms: Option<u64>,
    #[serde(default)]
    not_after_ms: Option<u64>,
}

impl TextTrust {
    /// Reload the owner-controlled file for each admission and dispatch stage.
    /// Updating the public key does not synthesize a signature or a grant.
    pub fn load(path: &Path, identity: &AgentdIdentity) -> Result<Self, AgentdError> {
        let bytes = read_owner_file(path, identity)?;
        let trust: Self = serde_json::from_slice(&bytes)?;
        if trust.schema_version != 1
            || trust.agent_id != identity.agent_id.as_str()
            || trust.thread_ids.len() > 16
            || trust.previous_epochs.len() > 4
            || trust
                .thread_ids
                .iter()
                .any(|id| id.is_empty() || id.len() > 128)
        {
            return Err(invalid(
                "trust registry owner, schema or thread bound is invalid",
            ));
        }
        trust.validate_epochs()?;
        Ok(trust)
    }

    pub fn issuer(&self) -> Result<IssuerRegistration, AgentdError> {
        self.registration(
            self.key_epoch,
            &self.public_key_hex,
            self.revoked,
            self.not_before_ms,
            self.not_after_ms,
            None,
        )
    }

    pub fn issuer_for(
        &self,
        key_epoch: u64,
        now_ms: u64,
    ) -> Result<IssuerRegistration, AgentdError> {
        if key_epoch == self.key_epoch {
            return self.registration(
                self.key_epoch,
                &self.public_key_hex,
                self.revoked,
                self.not_before_ms,
                self.not_after_ms,
                Some(now_ms),
            );
        }
        let epoch = self
            .previous_epochs
            .iter()
            .find(|epoch| epoch.key_epoch == key_epoch)
            .ok_or_else(|| invalid("key epoch is not enrolled"))?;
        self.registration(
            epoch.key_epoch,
            &epoch.public_key_hex,
            epoch.revoked,
            epoch.not_before_ms,
            epoch.not_after_ms,
            Some(now_ms),
        )
    }

    pub fn registrations(&self, now_ms: u64) -> Result<Vec<IssuerRegistration>, AgentdError> {
        let mut registrations = Vec::with_capacity(1 + self.previous_epochs.len());
        if !outside_window(self.not_before_ms, self.not_after_ms, now_ms) {
            registrations.push(self.issuer_for(self.key_epoch, now_ms)?);
        }
        for epoch in &self.previous_epochs {
            if outside_window(epoch.not_before_ms, epoch.not_after_ms, now_ms) {
                continue;
            }
            registrations.push(self.issuer_for(epoch.key_epoch, now_ms)?);
        }
        Ok(registrations)
    }

    fn validate_epochs(&self) -> Result<(), AgentdError> {
        let mut epochs = std::collections::BTreeSet::new();
        if !epochs.insert(self.key_epoch) {
            return Err(invalid("duplicate key epoch"));
        }
        let _ = self.issuer()?;
        for epoch in &self.previous_epochs {
            if !epochs.insert(epoch.key_epoch) {
                return Err(invalid("duplicate key epoch"));
            }
            let _ = self.registration(
                epoch.key_epoch,
                &epoch.public_key_hex,
                epoch.revoked,
                epoch.not_before_ms,
                epoch.not_after_ms,
                None,
            )?;
        }
        Ok(())
    }

    fn registration(
        &self,
        key_epoch: u64,
        public_key_hex: &str,
        revoked: bool,
        not_before_ms: Option<u64>,
        not_after_ms: Option<u64>,
        now_ms: Option<u64>,
    ) -> Result<IssuerRegistration, AgentdError> {
        if not_before_ms
            .zip(not_after_ms)
            .is_some_and(|(start, end)| start >= end)
        {
            return Err(invalid("invalid key validity window"));
        }
        if let Some(now) = now_ms
            && (not_before_ms.is_some_and(|start| now < start)
                || not_after_ms.is_some_and(|end| now >= end))
        {
            return Err(invalid("key epoch is outside its validity window"));
        }
        Ok(IssuerRegistration {
            issuer_id: StableId::new(&self.issuer_id)
                .map_err(|error| invalid(&error.to_string()))?,
            key_epoch: Generation::new(key_epoch).map_err(|error| invalid(&error.to_string()))?,
            verifying_key: VerifyingKey::from_bytes(&hex_bytes(public_key_hex)?)
                .map_err(|_| invalid("invalid registered Ed25519 public key"))?,
            revoked,
        })
    }

    pub fn permits(&self, thread_id: &str) -> bool {
        self.thread_ids.iter().any(|id| id == thread_id)
    }
}

fn outside_window(not_before_ms: Option<u64>, not_after_ms: Option<u64>, now_ms: u64) -> bool {
    not_before_ms.is_some_and(|start| now_ms < start)
        || not_after_ms.is_some_and(|end| now_ms >= end)
}

pub(crate) fn hex_bytes<const N: usize>(value: &str) -> Result<[u8; N], AgentdError> {
    if value.len() != N * 2 || !value.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(invalid("invalid fixed-width hexadecimal value"));
    }
    let mut bytes = [0; N];
    for (index, byte) in bytes.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| invalid("invalid hexadecimal value"))?;
    }
    Ok(bytes)
}

// This profile uses the already-private owner home. Refuse links, foreign
// ownership, writable-by-others files, oversized files and replacement/drift
// during the read. Do not create a file, key or registration on this path.
#[cfg(unix)]
fn read_owner_file(path: &Path, identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute()
        || path.parent() != Some(identity.home_root.as_path())
        || identity.home_root.canonicalize()? != identity.home_root
    {
        return Err(invalid(
            "trust file must be a direct child of the canonical Agent home",
        ));
    }
    let home = std::fs::metadata(&identity.home_root)?;
    let before = std::fs::symlink_metadata(path)?;
    if !home.is_dir()
        || home.mode() & 0o077 != 0
        || !before.is_file()
        || before.nlink() != 1
        || before.uid() != home.uid()
        || before.mode() & 0o077 != 0
        || before.len() > 16_384
    {
        return Err(invalid(
            "trust file must be a private owner-controlled regular file",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity = |m: &std::fs::Metadata| {
        (
            m.dev(),
            m.ino(),
            m.len(),
            m.mtime(),
            m.mtime_nsec(),
            m.ctime(),
            m.ctime_nsec(),
        )
    };
    if identity(&opened) != identity(&before) {
        return Err(invalid("trust file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(16_385).read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if bytes.len() > 16_384
        || !after.is_file()
        || identity(&after) != identity(&before)
        || identity(&file.metadata()?) != identity(&before)
    {
        return Err(invalid("trust file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_owner_file(_path: &Path, _identity: &AgentdIdentity) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the signed text trust-file profile currently requires Unix ownership checks",
    ))
}

pub(crate) fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("AuthBus text: {message}"))
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::SigningKey;

    use super::*;

    fn public_key_hex(seed: u8) -> String {
        SigningKey::from_bytes(&[seed; 32])
            .verifying_key()
            .to_bytes()
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }

    fn rotating_trust() -> TextTrust {
        TextTrust {
            schema_version: 1,
            agent_id: "agent:test".to_string(),
            issuer_id: "issuer:test".to_string(),
            key_epoch: 2,
            public_key_hex: public_key_hex(2),
            revoked: true,
            not_before_ms: None,
            not_after_ms: None,
            previous_epochs: vec![TrustEpoch {
                key_epoch: 1,
                public_key_hex: public_key_hex(1),
                revoked: false,
                not_before_ms: None,
                not_after_ms: None,
            }],
            restore_checkpoint_generation: None,
            restore_checkpoint_digest_hex: None,
            thread_ids: vec!["thread:allowed".to_string()],
        }
    }

    #[test]
    fn thread_allowlist_does_not_inherit_current_epoch_revocation() {
        let trust = rotating_trust();
        assert!(trust.permits("thread:allowed"));
        assert!(trust.issuer_for(2, 100).unwrap().revoked);
        assert!(!trust.issuer_for(1, 100).unwrap().revoked);
        let registrations = trust.registrations(100).unwrap();
        assert_eq!(registrations.len(), 2);
        assert!(
            registrations
                .iter()
                .any(|issuer| issuer.key_epoch.get() == 1 && !issuer.revoked)
        );
    }

    #[test]
    fn future_current_epoch_does_not_hide_valid_previous_epoch() {
        let mut trust = rotating_trust();
        trust.revoked = false;
        trust.not_before_ms = Some(200);
        let registrations = trust.registrations(100).unwrap();
        assert_eq!(registrations.len(), 1);
        assert_eq!(registrations[0].key_epoch.get(), 1);
        assert!(!registrations[0].revoked);
    }
}
