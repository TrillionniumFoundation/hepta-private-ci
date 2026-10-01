//! Fresh operational evidence extends the original store. Historical profiles
//! and the external ACK floor convey ancestry only, never current eligibility.
use super::*;
use std::os::unix::fs::MetadataExt;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Renewal {
    original_profile: Source,
    retained_profile: Source,
    retained_head: Source,
}
pub(super) struct VerifiedRenewal {
    pub(super) original_profile: Source,
    retained_profile: Source,
    retained_head: Source,
    retained_context: Profile,
    pub(super) historical_start: u64,
    pub(super) retained: SignedCurrentArtifactHeadV1,
    pub(super) lease_generation: u64,
}
impl Renewal {
    pub(super) fn verify(
        self,
        current: &Profile,
        current_source: &Source,
    ) -> HostResult<VerifiedRenewal> {
        let original: Profile = serde_json::from_slice(&self.original_profile.read(64 * 1024)?)?;
        let retained: Profile = serde_json::from_slice(&self.retained_profile.read(64 * 1024)?)?;
        original.validate_identity()?;
        retained.validate_identity()?;
        validate_unchanged_profile(&original, &retained)?;
        validate_unchanged_profile(&original, current)?;
        if current_source.digest == self.original_profile.digest
            || current_source.digest == self.retained_profile.digest
            || current.frozen_at_ms <= retained.frozen_at_ms
            || current.expires_at_ms <= retained.expires_at_ms
            || current.original_owner_state == retained.original_owner_state
            || current
                .original_owner_state
                .starts_with(&original.original_owner_state)
            || original
                .original_owner_state
                .starts_with(&current.original_owner_state)
            || current
                .original_owner_state
                .starts_with(&retained.original_owner_state)
            || retained
                .original_owner_state
                .starts_with(&current.original_owner_state)
            || current
                .artifact_ids
                .iter()
                .any(|id| original.artifact_ids.contains(id) || retained.artifact_ids.contains(id))
        {
            return Err(
                "renewal must retain the original history and use a new frozen scope".into(),
            );
        }
        let record: state::OriginalHead =
            serde_json::from_slice(&self.retained_head.read(16 * 1024)?)?;
        let binding = Digest32::of_bytes(
            format!(
                "hepta.cpu-neuron.initial-owner.storage.v1:{}:{}",
                current.registry_id, self.original_profile.digest
            )
            .as_bytes(),
        );
        let signed = record.historical(&self.retained_profile, &retained, binding)?;
        let lease_generation = signed
            .witness
            .generation
            .get()
            .checked_add(1)
            .ok_or("lease generation")?;
        let verified = VerifiedRenewal {
            original_profile: self.original_profile,
            retained_profile: self.retained_profile,
            retained_head: self.retained_head,
            historical_start: original.frozen_at_ms,
            retained_context: retained,
            retained: signed,
            lease_generation,
        };
        verified.revalidate()?;
        Ok(verified)
    }
}
impl VerifiedRenewal {
    pub(super) fn revalidate(&self) -> HostResult<()> {
        self.original_profile.read(64 * 1024)?;
        self.retained_profile.read(64 * 1024)?;
        self.retained_head.read(16 * 1024)?;
        Ok(())
    }
    pub(super) fn validate_original_root_floor(&self) -> HostResult<()> {
        state::directory_for_profile(&self.retained_context)?;
        let retained = self
            .retained_context
            .original_owner_state
            .join("head-2.json");
        let done = self.retained_context.original_owner_state.join("done-2");
        for path in [&retained, &done] {
            let metadata = std::fs::symlink_metadata(path)?;
            if metadata.uid() != 0 || metadata.mode() & 0o077 != 0 || metadata.nlink() != 1 {
                return Err("original private acknowledged Root floor boundary".into());
            }
        }
        if read_root_review_input(&retained, 16 * 1024)? != self.retained_head.read(16 * 1024)?
            || serde_json::from_slice::<String>(&read_root_review_input(&done, 16 * 1024)?)?
                != Digest32::of_bytes(&self.retained.signing_bytes()).to_string()
        {
            return Err("original Root ACK floor is missing or changed".into());
        }
        self.revalidate()
    }
}

fn validate_unchanged_profile(original: &Profile, current: &Profile) -> HostResult<()> {
    let stable = |profile: &Profile| -> HostResult<Value> {
        let mut value = serde_json::to_value(profile)?;
        let object = value.as_object_mut().ok_or("profile object")?;
        for field in [
            "frozen_at_ms",
            "expires_at_ms",
            "program",
            "original_owner_state",
            "artifact_ids",
        ] {
            object.remove(field);
        }
        Ok(value)
    };
    if stable(original)? != stable(current)? {
        return Err("operational renewal cannot change the original full baseline profile".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "initial_cpu_renewal_tests.rs"]
mod tests;
