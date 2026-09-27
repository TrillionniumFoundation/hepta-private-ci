//! Monotonic host generations allocated in the existing owner transaction.
use super::*;

const MAX_RETIRED_BOOT_IDENTITIES: usize = 4_096;
const MAX_INCARNATION_HOSTS: usize = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FleetHostIncarnationV1 {
    pub boot_identity: String,
    pub host_generation: u64,
    pub failure_domain_id: String,
    pub retired_boot_identities: BTreeSet<String>,
}

impl DurableFleetOwner {
    /// Only the product owner supplies the independently observed boot identity.
    /// Overrides must obey the same monotonic protocol, never bypass it.
    pub fn resolve_host_incarnation(
        &mut self,
        host_id: &str,
        failure_domain_id: &str,
        boot_identity: &str,
        requested_generation: Option<u64>,
    ) -> Result<FleetHostIncarnationV1, DurableFleetError> {
        if !valid_identity(host_id)
            || !valid_identity(failure_domain_id)
            || !valid_digest(boot_identity)
        {
            return Err(DurableFleetError::InvalidHostIncarnation);
        }
        let _guard = OwnerLock::acquire(&self.root.join(DURABLE_FLEET_LOCK))?;
        self.reload()?;
        let previous = self.state.fleet_host_incarnations.get(host_id);
        if let Some(previous) = previous {
            if previous.boot_identity == boot_identity {
                if previous.failure_domain_id != failure_domain_id
                    || requested_generation.is_some_and(|value| value != previous.host_generation)
                {
                    return Err(DurableFleetError::InvalidHostIncarnation);
                }
                return Ok(previous.clone());
            }
            if previous.retired_boot_identities.contains(boot_identity)
                || previous.retired_boot_identities.len() >= MAX_RETIRED_BOOT_IDENTITIES
            {
                return Err(DurableFleetError::InvalidHostIncarnation);
            }
        } else if self.state.fleet_host_incarnations.len() >= MAX_INCARNATION_HOSTS {
            return Err(DurableFleetError::InvalidHostIncarnation);
        }
        // Migration also fences the legacy hash-derived generation. It is not
        // reset to one, even when the legacy value is numerically very large.
        let floor = previous.map_or(0, |value| value.host_generation).max(
            self.state
                .fleet_hosts
                .get(host_id)
                .map_or(0, |value| value.generation),
        );
        let next = floor
            .checked_add(1)
            .ok_or(DurableFleetError::ArithmeticOverflow)?;
        let host_generation = requested_generation.unwrap_or(next);
        if host_generation < next {
            return Err(DurableFleetError::InvalidHostIncarnation);
        }
        let mut retired_boot_identities =
            previous.map_or_else(BTreeSet::new, |value| value.retired_boot_identities.clone());
        if let Some(previous) = previous {
            retired_boot_identities.insert(previous.boot_identity.clone());
        }
        let incarnation = FleetHostIncarnationV1 {
            boot_identity: boot_identity.to_string(),
            host_generation,
            failure_domain_id: failure_domain_id.to_string(),
            retired_boot_identities,
        };
        let digest = operation_digest(b"host-incarnation", &(host_id, &incarnation))?;
        let operation = FleetOperationReceiptV1 {
            operation_id: format!("host-incarnation-{digest}"),
            operation_kind: FleetOperationKindV1::HostIncarnation,
            operation_digest: digest,
            committed_generation: next_generation(self.state.generation)?,
            committed_at_ms: self.clock.now_unix_ms()?,
            lease_receipt: None,
            authority_witness: None,
        };
        let mut candidate = self.state.clone();
        candidate
            .fleet_host_incarnations
            .insert(host_id.to_string(), incarnation.clone());
        append_operation(&mut candidate, operation.clone())?;
        self.commit(candidate, operation)?;
        Ok(incarnation)
    }
}

pub(super) fn validate_incarnations(state: &DurableFleetStateV1) -> Result<(), DurableFleetError> {
    if state.fleet_host_incarnations.len() > MAX_INCARNATION_HOSTS {
        return Err(DurableFleetError::CorruptState);
    }
    for (host_id, identity) in &state.fleet_host_incarnations {
        if !valid_identity(host_id)
            || !valid_identity(&identity.failure_domain_id)
            || !valid_digest(&identity.boot_identity)
            || identity.host_generation == 0
            || identity.retired_boot_identities.len() > MAX_RETIRED_BOOT_IDENTITIES
            || identity
                .retired_boot_identities
                .contains(&identity.boot_identity)
            || identity
                .retired_boot_identities
                .iter()
                .any(|value| !valid_digest(value))
            || state
                .fleet_hosts
                .get(host_id)
                .is_some_and(|host| host.generation > identity.host_generation)
        {
            return Err(DurableFleetError::CorruptState);
        }
    }
    Ok(())
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::SystemFleetClock;

    #[test]
    fn smaller_boot_identity_advances_once_and_old_boot_replay_is_denied() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().join("state");
        std::fs::create_dir(&root).expect("state");
        let mut owner =
            crate::DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("owner");
        let first = owner
            .resolve_host_incarnation("host", "domain", &"f".repeat(64), None)
            .expect("boot one");
        assert_eq!(first.host_generation, 1);
        let committed = owner.state().generation;
        drop(owner);
        let mut owner =
            crate::DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("process restart");
        assert_eq!(
            owner
                .resolve_host_incarnation("host", "domain", &"f".repeat(64), None)
                .expect("same boot"),
            first
        );
        assert_eq!(owner.state().generation, committed);
        let second = owner
            .resolve_host_incarnation("host", "domain", &"1".repeat(64), None)
            .expect("smaller identity");
        assert_eq!(second.host_generation, 2);
        assert!(
            owner
                .resolve_host_incarnation("host", "domain", &"f".repeat(64), None)
                .is_err()
        );
        assert!(
            owner
                .resolve_host_incarnation("host", "domain", &"1".repeat(64), Some(1))
                .is_err()
        );
        assert!(
            owner
                .resolve_host_incarnation("host", "other-domain", &"1".repeat(64), None)
                .is_err()
        );
    }

    #[test]
    fn configured_large_generation_is_fenced_and_overflow_does_not_reset() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().join("state");
        std::fs::create_dir(&root).expect("state");
        let mut owner =
            crate::DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock))
                .expect("owner");
        let first = owner
            .resolve_host_incarnation("host", "domain", &"1".repeat(64), Some(u64::MAX - 1))
            .expect("explicit high generation");
        assert_eq!(first.host_generation, u64::MAX - 1);
        let second = owner
            .resolve_host_incarnation("host", "domain", &"2".repeat(64), None)
            .expect("last generation");
        assert_eq!(second.host_generation, u64::MAX);
        let before = owner.state().content_sha256.clone();
        assert!(matches!(
            owner.resolve_host_incarnation("host", "domain", &"3".repeat(64), None),
            Err(DurableFleetError::ArithmeticOverflow)
        ));
        assert_eq!(before, owner.state().content_sha256);
    }
}
