//! Rebuildable read projection for the operator sensor-core domain.
//!
//! Sensor cores are immutable learning artifacts. The authoritative physical
//! write therefore remains the ordinary `ArtifactRegistry` append path with
//! `ArtifactKind::SensorCore`; this module exposes the separately registered
//! read domain without creating a second durable writer or journal.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::ArtifactRegistry;

const PROJECTION_DOMAIN: &[u8] = b"hepta.learning-artifacts.operator-sensor-core-projection.v1";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorSensorCoreEntryV1 {
    pub manifest: ArtifactManifest,
    pub eligible: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorSensorCoreRegistryV1 {
    entries: Vec<OperatorSensorCoreEntryV1>,
    pub source_registry_head_digest: Digest32,
    pub projection_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl OperatorSensorCoreRegistryV1 {
    #[must_use]
    pub fn entries(&self) -> &[OperatorSensorCoreEntryV1] {
        &self.entries
    }
}

/// Rebuild the registered sensor-core domain from the authoritative immutable
/// artifact registry. Ordering is canonical by sensor-core identity.
///
/// This function grants no selection or activation authority. A revoked or
/// quarantined sensor core remains visible for lineage/audit but is marked
/// ineligible.
#[must_use]
pub fn project_operator_sensor_core_registry_v1(
    registry: &ArtifactRegistry,
) -> OperatorSensorCoreRegistryV1 {
    let mut entries = registry
        .records()
        .iter()
        .filter_map(|record| match &record.event {
            ArtifactEvent::Register { manifest, .. }
                if manifest.kind == ArtifactKind::SensorCore =>
            {
                Some(OperatorSensorCoreEntryV1 {
                    manifest: manifest.clone(),
                    eligible: registry.is_eligible(&manifest.artifact_id),
                })
            }
            ArtifactEvent::Register { .. }
            | ArtifactEvent::Quarantine(_)
            | ArtifactEvent::Revoke(_) => None,
        })
        .collect::<Vec<_>>();
    entries.sort_by(|left, right| left.manifest.artifact_id.cmp(&right.manifest.artifact_id));

    let source_registry_head_digest = registry.snapshot().head_digest;
    let projection_digest = digest_projection(source_registry_head_digest, &entries);
    OperatorSensorCoreRegistryV1 {
        entries,
        source_registry_head_digest,
        projection_digest,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn digest_projection(
    source_registry_head_digest: Digest32,
    entries: &[OperatorSensorCoreEntryV1],
) -> Digest32 {
    let mut bytes = PROJECTION_DOMAIN.to_vec();
    bytes.extend_from_slice(source_registry_head_digest.as_array());
    for entry in entries {
        bytes.extend_from_slice(entry.manifest.artifact_id.as_str().as_bytes());
        bytes.push(0);
        bytes.extend_from_slice(entry.manifest.content_digest.as_array());
        bytes.extend_from_slice(&entry.manifest.generation.get().to_be_bytes());
        bytes.push(u8::from(entry.eligible));
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use crate::ArtifactEvent;
    use crate::ArtifactState;
    use crate::StateChange;

    fn id(value: &str) -> StableId {
        match StableId::new(value.to_owned()) {
            Ok(value) => value,
            Err(error) => panic!("invalid test id {value}: {error}"),
        }
    }

    fn generation(value: u64) -> Generation {
        match Generation::new(value) {
            Ok(value) => value,
            Err(error) => panic!("invalid generation {value}: {error}"),
        }
    }

    fn manifest(name: &str, kind: ArtifactKind) -> ArtifactManifest {
        ArtifactManifest {
            artifact_id: id(name),
            kind,
            generation: generation(1),
            predecessor_id: None,
            content_digest: Digest32::of_bytes(format!("bytes-{name}").as_bytes()),
            objective_digest: Digest32::of_bytes(b"objective"),
            support_digest: Digest32::of_bytes(b"support"),
            producer_id: id("operator"),
            compatibility_digest: Digest32::of_bytes(b"compatibility"),
            encoded_size_bytes: 16,
        }
    }

    fn append(registry: &mut ArtifactRegistry, event: ArtifactEvent) {
        if let Err(error) = registry.append(event) {
            panic!("sensor-core projection fixture failed: {error}");
        }
    }

    #[test]
    fn operator_sensor_core_projection_has_one_physical_owner() {
        let mut registry = ArtifactRegistry::new();
        append(
            &mut registry,
            ArtifactEvent::Register {
                event_id: id("sensor-event"),
                manifest: manifest("sensor-core", ArtifactKind::SensorCore),
            },
        );
        append(
            &mut registry,
            ArtifactEvent::Register {
                event_id: id("policy-event"),
                manifest: manifest("policy", ArtifactKind::Policy),
            },
        );

        let projection = project_operator_sensor_core_registry_v1(&registry);
        assert_eq!(projection.entries().len(), 1);
        assert_eq!(
            projection.entries()[0].manifest.artifact_id,
            id("sensor-core")
        );
        assert!(projection.entries()[0].eligible);
        assert_eq!(
            projection.source_registry_head_digest,
            registry.snapshot().head_digest
        );
        assert!(!projection.projection_digest.is_zero());
        assert_eq!(projection.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn operator_sensor_core_projection_tracks_revocation_without_second_write() {
        let mut registry = ArtifactRegistry::new();
        append(
            &mut registry,
            ArtifactEvent::Register {
                event_id: id("sensor-event"),
                manifest: manifest("sensor-core", ArtifactKind::SensorCore),
            },
        );
        append(
            &mut registry,
            ArtifactEvent::Revoke(StateChange {
                event_id: id("revoke-event"),
                artifact_id: id("sensor-core"),
                evaluator_id: id("independent-evaluator"),
                reason_digest: Digest32::of_bytes(b"revoked"),
            }),
        );
        assert_eq!(
            registry.state(&id("sensor-core")),
            Some(ArtifactState::Revoked)
        );

        let first = project_operator_sensor_core_registry_v1(&registry);
        let second = project_operator_sensor_core_registry_v1(&registry);
        assert_eq!(first, second);
        assert_eq!(first.entries().len(), 1);
        assert!(!first.entries()[0].eligible);
    }
}
