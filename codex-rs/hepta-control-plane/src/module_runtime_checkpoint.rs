use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::MAX_PENDING_RUNTIME_MODULES;
use super::MAX_RUNTIME_MODULE_IDENTITIES;
use super::MAX_RUNTIME_MODULES;
use super::RuntimeModuleLifecycleV1;
use super::RuntimeModuleRecordV1;
use super::RuntimeModuleRegistryError;
use super::RuntimeModuleRegistryV1;
use super::RuntimeModuleStateClassV1;

const CHECKPOINT_DOMAIN: &[u8] = b"hepta.runtime-module-registry-checkpoint.v1\0";
const MAX_RETAINED_RUNTIME_RECORDS: usize = (MAX_RUNTIME_MODULES + MAX_PENDING_RUNTIME_MODULES) * 2;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleActiveReservationV1 {
    pub module_id: StableId,
    pub generation: Generation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleGenerationFenceV1 {
    pub module_id: StableId,
    pub first_generation: Generation,
    pub greatest_generation: Generation,
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleRegistryCheckpointV1 {
    pub records: Vec<RuntimeModuleRecordV1>,
    pub active_reservations: Vec<RuntimeModuleActiveReservationV1>,
    pub generation_fences: Vec<RuntimeModuleGenerationFenceV1>,
    pub checkpoint_digest: Digest32,
}

impl RuntimeModuleRegistryV1 {
    pub fn checkpoint(&self) -> RuntimeModuleRegistryCheckpointV1 {
        let mut checkpoint = RuntimeModuleRegistryCheckpointV1 {
            records: self.records.values().cloned().collect(),
            active_reservations: self
                .active
                .iter()
                .map(|(module_id, generation)| RuntimeModuleActiveReservationV1 {
                    module_id: module_id.clone(),
                    generation: *generation,
                })
                .collect(),
            generation_fences: self
                .generation_fences
                .iter()
                .map(|(module_id, (first_generation, greatest_generation))| {
                    RuntimeModuleGenerationFenceV1 {
                        module_id: module_id.clone(),
                        first_generation: *first_generation,
                        greatest_generation: *greatest_generation,
                    }
                })
                .collect(),
            checkpoint_digest: Digest32::ZERO,
        };
        checkpoint.checkpoint_digest = checkpoint_digest(&checkpoint);
        checkpoint
    }
    pub fn restore_checkpoint(
        checkpoint: RuntimeModuleRegistryCheckpointV1,
    ) -> Result<Self, RuntimeModuleRegistryError> {
        if checkpoint.records.len() > MAX_RETAINED_RUNTIME_RECORDS
            || checkpoint.active_reservations.len() > MAX_RUNTIME_MODULES
            || checkpoint.generation_fences.len() > MAX_RUNTIME_MODULE_IDENTITIES
        {
            return Err(RuntimeModuleRegistryError::Bounds);
        }
        if checkpoint.checkpoint_digest != checkpoint_digest(&checkpoint) {
            return Err(RuntimeModuleRegistryError::CheckpointDigestMismatch);
        }

        let mut records = BTreeMap::new();
        for record in checkpoint.records {
            record.abi.validate()?;
            let key = (record.abi.module_id.clone(), record.abi.generation);
            if records.insert(key, record).is_some() {
                return Err(RuntimeModuleRegistryError::CheckpointDuplicate);
            }
        }
        let mut active = BTreeMap::new();
        for reservation in checkpoint.active_reservations {
            if active
                .insert(reservation.module_id, reservation.generation)
                .is_some()
            {
                return Err(RuntimeModuleRegistryError::CheckpointDuplicate);
            }
        }
        let mut generation_fences = BTreeMap::new();
        for fence in checkpoint.generation_fences {
            if fence.first_generation > fence.greatest_generation
                || generation_fences
                    .insert(
                        fence.module_id,
                        (fence.first_generation, fence.greatest_generation),
                    )
                    .is_some()
            {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            }
        }
        for ((module_id, generation), record) in &records {
            let Some((first, greatest)) = generation_fences.get(module_id) else {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            };
            if generation < first
                || generation > greatest
                || record.abi.module_id != *module_id
                || record.abi.generation != *generation
            {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            }
        }
        for (module_id, (first, greatest)) in &generation_fences {
            let generations = records
                .keys()
                .filter(|(candidate, _)| candidate == module_id)
                .map(|(_, generation)| *generation)
                .collect::<Vec<_>>();
            // Terminal payloads may be compacted completely while the
            // generation fence remains as the anti-resurrection fact. Any
            // retained payload must still lie inside the admitted interval;
            // the greatest generation itself need not retain a payload.
            if generations
                .iter()
                .any(|value| value < first || value > greatest)
            {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            }
        }

        for (module_id, generation) in &active {
            let Some(record) = records.get(&(module_id.clone(), *generation)) else {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            };
            if !matches!(
                record.lifecycle,
                RuntimeModuleLifecycleV1::Active
                    | RuntimeModuleLifecycleV1::Quiescing
                    | RuntimeModuleLifecycleV1::Quarantined
            ) {
                return Err(RuntimeModuleRegistryError::CheckpointInvalid);
            }
        }
        let pending = records
            .values()
            .filter(|record| {
                matches!(
                    record.lifecycle,
                    RuntimeModuleLifecycleV1::Registered
                        | RuntimeModuleLifecycleV1::Shadow
                        | RuntimeModuleLifecycleV1::Canary
                )
            })
            .count();
        if pending > MAX_PENDING_RUNTIME_MODULES {
            return Err(RuntimeModuleRegistryError::Bounds);
        }
        let selected = active
            .iter()
            .map(|(module_id, generation)| {
                records
                    .get(&(module_id.clone(), *generation))
                    .ok_or(RuntimeModuleRegistryError::CheckpointInvalid)
            })
            .collect::<Result<Vec<_>, _>>()?;
        for (index, left) in selected.iter().enumerate() {
            for right in selected.iter().skip(index + 1) {
                if let Some(domain) = left
                    .abi
                    .authoritative_domains
                    .intersection(&right.abi.authoritative_domains)
                    .next()
                {
                    return Err(RuntimeModuleRegistryError::AuthoritativeWriterConflict(
                        domain.clone(),
                    ));
                }
            }
        }
        Ok(Self {
            records,
            active,
            generation_fences,
        })
    }

    pub fn greatest_admitted_generation(&self, module_id: &StableId) -> Option<Generation> {
        self.generation_fences
            .get(module_id)
            .map(|(_, greatest)| *greatest)
    }
}
fn checkpoint_digest(checkpoint: &RuntimeModuleRegistryCheckpointV1) -> Digest32 {
    let mut records = checkpoint.records.clone();
    records.sort_by(|left, right| {
        left.abi
            .module_id
            .cmp(&right.abi.module_id)
            .then_with(|| left.abi.generation.cmp(&right.abi.generation))
    });
    let mut active = checkpoint.active_reservations.clone();
    active.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then_with(|| left.generation.cmp(&right.generation))
    });
    let mut fences = checkpoint.generation_fences.clone();
    fences.sort_by(|left, right| left.module_id.cmp(&right.module_id));

    let mut bytes = CHECKPOINT_DOMAIN.to_vec();
    push_len(&mut bytes, records.len());
    for record in &records {
        push_record(&mut bytes, record);
    }
    push_len(&mut bytes, active.len());
    for reservation in &active {
        push_id(&mut bytes, &reservation.module_id);
        push_generation(&mut bytes, reservation.generation);
    }
    push_len(&mut bytes, fences.len());
    for fence in &fences {
        push_id(&mut bytes, &fence.module_id);
        push_generation(&mut bytes, fence.first_generation);
        push_generation(&mut bytes, fence.greatest_generation);
    }
    Digest32::of_bytes(&bytes)
}
fn push_record(bytes: &mut Vec<u8>, record: &RuntimeModuleRecordV1) {
    push_abi(bytes, &record.abi);
    bytes.push(match record.lifecycle {
        RuntimeModuleLifecycleV1::Registered => 0,
        RuntimeModuleLifecycleV1::Shadow => 1,
        RuntimeModuleLifecycleV1::Canary => 2,
        RuntimeModuleLifecycleV1::Active => 3,
        RuntimeModuleLifecycleV1::Quiescing => 4,
        RuntimeModuleLifecycleV1::Retired => 5,
        RuntimeModuleLifecycleV1::Quarantined => 6,
    });
    push_optional_digest(bytes, record.selection_digest);
    push_optional_digest(bytes, record.canary_digest);
    push_optional_digest(bytes, record.handoff_digest);
}

fn push_abi(bytes: &mut Vec<u8>, abi: &super::RuntimeModuleAbiV1) {
    push_id(bytes, &abi.module_id);
    push_id(bytes, &abi.owner_id);
    push_generation(bytes, abi.generation);
    bytes.extend_from_slice(abi.implementation_digest.as_array());
    bytes.extend_from_slice(abi.candidate_artifact_digest.as_array());
    match abi.predecessor_generation {
        Some(generation) => {
            bytes.push(1);
            push_generation(bytes, generation);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(abi.rollback_predecessor_digest.as_array());
    bytes.push(match abi.state_class {
        RuntimeModuleStateClassV1::Stateless => 0,
        RuntimeModuleStateClassV1::Stateful => 1,
        RuntimeModuleStateClassV1::ExternalStateful => 2,
    });
    push_ids(bytes, &abi.dependencies);
    push_ids(bytes, &abi.input_ports);
    push_ids(bytes, &abi.output_ports);
    push_ids(
        bytes,
        &abi.authoritative_domains
            .iter()
            .cloned()
            .collect::<Vec<_>>(),
    );
    push_ids(bytes, &abi.effect_scope.iter().cloned().collect::<Vec<_>>());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_len(bytes, value.as_str().len());
    bytes.extend_from_slice(value.as_str().as_bytes());
}
fn push_generation(bytes: &mut Vec<u8>, value: Generation) {
    bytes.extend_from_slice(&value.get().to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&(value as u64).to_be_bytes());
}
#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::RuntimeModuleAbiV1;
    use crate::RuntimeModulePromotionWitnessV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn generation(value: u64) -> Generation {
        Generation::new(value).expect("generation")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn abi(value: u64, predecessor: Option<u64>) -> RuntimeModuleAbiV1 {
        RuntimeModuleAbiV1 {
            module_id: id("feature.persisted"),
            owner_id: id("owner.persisted"),
            generation: generation(value),
            implementation_digest: digest(&format!("implementation:{value}")),
            candidate_artifact_digest: digest(&format!("candidate:{value}")),
            predecessor_generation: predecessor.map(generation),
            rollback_predecessor_digest: predecessor
                .map(|previous| digest(&format!("implementation:{previous}")))
                .unwrap_or(Digest32::ZERO),
            state_class: RuntimeModuleStateClassV1::Stateful,
            dependencies: Vec::new(),
            input_ports: Vec::new(),
            output_ports: Vec::new(),
            authoritative_domains: BTreeSet::from([id("domain.persisted")]),
            effect_scope: BTreeSet::new(),
        }
    }

    fn witness(value: &str) -> RuntimeModulePromotionWitnessV1 {
        RuntimeModulePromotionWitnessV1 {
            selection_digest: digest(&format!("selection:{value}")),
            canary_digest: digest(&format!("canary:{value}")),
            handoff_digest: digest(&format!("handoff:{value}")),
        }
    }

    #[test]
    fn active_generation_and_fence_survive_checkpoint_restore() {
        let module = id("feature.persisted");
        let mut registry = RuntimeModuleRegistryV1::new();
        registry
            .register_candidate(abi(1, None))
            .expect("register g1");
        registry
            .activate_bootstrap(&module, generation(1))
            .expect("activate g1");
        registry
            .register_candidate(abi(2, Some(1)))
            .expect("register g2");
        registry
            .enter_shadow(&module, generation(2))
            .expect("shadow");
        registry
            .enter_canary(&module, generation(2))
            .expect("canary");
        registry
            .promote_after_handoff(&module, generation(2), witness("g2"))
            .expect("promote g2");
        let before = registry.snapshot();
        let checkpoint = registry.checkpoint();
        let mut restored =
            RuntimeModuleRegistryV1::restore_checkpoint(checkpoint).expect("restore checkpoint");
        assert_eq!(restored.snapshot(), before);
        assert_eq!(restored.active_generation(&module), Some(generation(2)));
        assert_eq!(
            restored.greatest_admitted_generation(&module),
            Some(generation(2))
        );
        assert_eq!(
            restored.register_candidate(abi(2, Some(1))),
            Err(RuntimeModuleRegistryError::InvalidGeneration)
        );
    }

    #[test]
    fn compacted_retired_identity_restores_its_generation_fence() {
        let retired = id("feature.retired");
        let survivor = id("feature.survivor");
        let mut retired_abi = abi(1, None);
        retired_abi.module_id = retired.clone();
        retired_abi.authoritative_domains = BTreeSet::from([id("domain.retired")]);
        let mut survivor_abi = abi(1, None);
        survivor_abi.module_id = survivor.clone();
        survivor_abi.authoritative_domains = BTreeSet::from([id("domain.survivor")]);

        let mut registry = RuntimeModuleRegistryV1::new();
        registry
            .register_candidate(retired_abi.clone())
            .expect("register retired module");
        registry
            .activate_bootstrap(&retired, generation(1))
            .expect("activate retired module");
        registry
            .begin_retire(&retired, generation(1))
            .expect("begin retirement");
        registry
            .finish_retire(&retired, generation(1))
            .expect("finish retirement");

        // Registering another module compacts the unselected terminal payload
        // while retaining the retired identity's anti-resurrection fence.
        registry
            .register_candidate(survivor_abi)
            .expect("register survivor");
        registry
            .activate_bootstrap(&survivor, generation(1))
            .expect("activate survivor");
        assert!(registry.record(&retired, generation(1)).is_none());
        assert_eq!(
            registry.greatest_admitted_generation(&retired),
            Some(generation(1))
        );

        let mut restored = RuntimeModuleRegistryV1::restore_checkpoint(registry.checkpoint())
            .expect("restore compacted anti-resurrection fence");
        assert_eq!(
            restored.greatest_admitted_generation(&retired),
            Some(generation(1))
        );
        assert_eq!(
            restored.register_candidate(retired_abi),
            Err(RuntimeModuleRegistryError::InvalidGeneration)
        );
    }

    #[test]
    fn checkpoint_digest_rejects_mutation() {
        let module = id("feature.persisted");
        let mut registry = RuntimeModuleRegistryV1::new();
        registry.register_candidate(abi(1, None)).expect("register");
        registry
            .activate_bootstrap(&module, generation(1))
            .expect("activate");
        let mut checkpoint = registry.checkpoint();
        checkpoint.active_reservations.clear();
        assert!(matches!(
            RuntimeModuleRegistryV1::restore_checkpoint(checkpoint),
            Err(RuntimeModuleRegistryError::CheckpointDigestMismatch)
        ));
    }
}
