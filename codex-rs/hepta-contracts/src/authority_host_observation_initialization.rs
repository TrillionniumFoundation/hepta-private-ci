//! Explicit completion of original immutable Root administrative inputs.
//! Ordinary observation reads never invoke these initialization operations.

use super::*;

impl RootAuthorityDirectory {
    /// Complete only a full original candidate for this exact observation ID.
    /// A missing, incomplete or conflicting candidate is never reconstructed.
    /// An existing canonical record is read normally and never replaced.
    pub fn resume_observation(
        self: &Arc<Self>,
        observation_id: &str,
    ) -> Result<RootStoredObservation, AuthorityTrustError> {
        let name = observation_name(observation_id)?;
        let lock = self.lock(&format!("{name}.lock"))?;
        let expected = if self.exists(&name)? {
            None
        } else {
            let temporary = format!("{name}.next");
            let (payload, record) = read_record(self, &temporary, observation_id)?;
            record.file.sync_all().map_err(unavailable)?;
            self.sync_directory()?;
            rustix::fs::renameat_with(
                &self.directory,
                &temporary,
                &self.directory,
                &name,
                rustix::fs::RenameFlags::NOREPLACE,
            )
            .map_err(|error| {
                if error == rustix::io::Errno::EXIST {
                    AuthorityTrustError::Conflict
                } else {
                    AuthorityTrustError::Unavailable
                }
            })?;
            self.sync_directory()?;
            Some((payload, record))
        };
        drop(lock);
        let restored = self.open_observation(observation_id)?;
        if let Some((payload, record)) = expected
            && (payload != restored.payload || !record.matches(&restored.record)?)
        {
            return Err(AuthorityTrustError::Unavailable);
        }
        Ok(restored)
    }
}

impl RootStoredObservation {
    /// Publish an immutable administrative configuration in its original raw
    /// format from these already retained, complete bytes. The original Root
    /// publication primitives validate the unpublished inode before writing.
    /// Publication uses NOREPLACE: existing different/corrupt canonical data
    /// is a conflict. This cannot overwrite a frontier or observation record.
    pub fn publish_initial_alias(&self, name: &str) -> Result<(), AuthorityTrustError> {
        if name.is_empty()
            || name.len() > 96
            || name.starts_with('.')
            || name.starts_with("frontier-")
            || name.starts_with("observation-")
            || name.starts_with("initial-config-")
            || name.ends_with(".next")
            || name.ends_with(".lock")
            || !name
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"_.-".contains(&byte))
        {
            return Err(AuthorityTrustError::Invalid);
        }
        self.verify_durable()?;
        let digest = Sha256::digest(name.as_bytes());
        let suffix: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
        let _lock = self.root.lock(&format!("initial-config-{suffix}.lock"))?;
        if !self.root.exists(name)? {
            let temporary = format!("initial-config-{suffix}.next");
            let mut prepared = self.root.prepare_replace(&temporary, name)?;
            // The full original observation is the source of these bytes.
            // Truncating a validated unpublished alias does not lose evidence.
            prepared
                .file
                .write_all(&self.payload)
                .map_err(unavailable)?;
            prepared.file.sync_all().map_err(unavailable)?;
            self.root.sync_directory()?;
            rustix::fs::renameat_with(
                &self.root.directory,
                &temporary,
                &self.root.directory,
                name,
                rustix::fs::RenameFlags::NOREPLACE,
            )
            .map_err(|error| {
                if error == rustix::io::Errno::EXIST {
                    AuthorityTrustError::Conflict
                } else {
                    AuthorityTrustError::Unavailable
                }
            })?;
            self.root.sync_directory()?;
        }
        let file = self
            .root
            .open_private(name, OFlags::RDONLY | OFlags::NONBLOCK)?;
        let mut bytes = Vec::new();
        (&file)
            .take(MAX_RECORD_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(unavailable)?;
        if bytes != self.payload {
            return Err(AuthorityTrustError::Conflict);
        }
        file.sync_all().map_err(unavailable)?;
        self.root.sync_directory()?;
        self.verify_durable()
    }
}

#[cfg(test)]
#[path = "authority_host_observation_initialization_tests.rs"]
mod tests;
