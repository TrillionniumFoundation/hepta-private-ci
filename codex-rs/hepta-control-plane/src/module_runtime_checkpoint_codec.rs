//! Fixed V1 schema, bounded counts before allocation, no extension fields.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::super::MAX_MODULE_DEPENDENCIES;
use super::super::MAX_MODULE_DOMAINS;
use super::super::MAX_MODULE_EFFECTS;
use super::super::MAX_MODULE_PORTS;
use super::super::MAX_RUNTIME_MODULE_IDENTITIES;
use super::super::MAX_RUNTIME_MODULES;
use super::super::RuntimeModuleAbiV1;
use super::super::RuntimeModuleLifecycleV1;
use super::super::RuntimeModuleRecordV1;
use super::super::RuntimeModuleRegistryError as Error;
use super::super::RuntimeModuleStateClassV1;
use super::MAX_RETAINED_RUNTIME_RECORDS;
use super::MAX_RUNTIME_MODULE_CHECKPOINT_BYTES;
use super::RuntimeModuleActiveReservationV1;
use super::RuntimeModuleGenerationFenceV1;
use super::RuntimeModuleRegistryCheckpointV1;

const CHECKPOINT_DOMAIN: &[u8] = b"hepta.runtime-module-registry-checkpoint.v1\0";

pub(super) fn encode(checkpoint: &RuntimeModuleRegistryCheckpointV1) -> Vec<u8> {
    let mut records = checkpoint.records.iter().collect::<Vec<_>>();
    records.sort_by(|left, right| {
        left.abi
            .module_id
            .cmp(&right.abi.module_id)
            .then_with(|| left.abi.generation.cmp(&right.abi.generation))
    });
    let mut active = checkpoint.active_reservations.iter().collect::<Vec<_>>();
    active.sort_by(|left, right| {
        left.module_id
            .cmp(&right.module_id)
            .then_with(|| left.generation.cmp(&right.generation))
    });
    let mut fences = checkpoint.generation_fences.iter().collect::<Vec<_>>();
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
    bytes
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

fn push_abi(bytes: &mut Vec<u8>, abi: &super::super::RuntimeModuleAbiV1) {
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

pub(super) fn decode(bytes: &[u8]) -> Result<RuntimeModuleRegistryCheckpointV1, Error> {
    if bytes.len() > MAX_RUNTIME_MODULE_CHECKPOINT_BYTES {
        return Err(Error::Bounds);
    }
    let mut r = Reader(bytes);
    if r.take(CHECKPOINT_DOMAIN.len())? != CHECKPOINT_DOMAIN {
        return Err(Error::CheckpointEncoding);
    }
    let checkpoint = RuntimeModuleRegistryCheckpointV1 {
        records: r.list(MAX_RETAINED_RUNTIME_RECORDS, |r| {
            let abi = RuntimeModuleAbiV1 {
                module_id: r.id()?,
                owner_id: r.id()?,
                generation: r.generation()?,
                implementation_digest: r.digest()?,
                candidate_artifact_digest: r.digest()?,
                predecessor_generation: r.optional(Reader::generation)?,
                rollback_predecessor_digest: r.digest()?,
                state_class: match r.byte()? {
                    0 => RuntimeModuleStateClassV1::Stateless,
                    1 => RuntimeModuleStateClassV1::Stateful,
                    2 => RuntimeModuleStateClassV1::ExternalStateful,
                    _ => return Err(Error::CheckpointEncoding),
                },
                dependencies: r.list(MAX_MODULE_DEPENDENCIES, Reader::id)?,
                input_ports: r.list(MAX_MODULE_PORTS, Reader::id)?,
                output_ports: r.list(MAX_MODULE_PORTS, Reader::id)?,
                authoritative_domains: r.set(MAX_MODULE_DOMAINS)?,
                effect_scope: r.set(MAX_MODULE_EFFECTS)?,
            };
            let lifecycle = match r.byte()? {
                0 => RuntimeModuleLifecycleV1::Registered,
                1 => RuntimeModuleLifecycleV1::Shadow,
                2 => RuntimeModuleLifecycleV1::Canary,
                3 => RuntimeModuleLifecycleV1::Active,
                4 => RuntimeModuleLifecycleV1::Quiescing,
                5 => RuntimeModuleLifecycleV1::Retired,
                6 => RuntimeModuleLifecycleV1::Quarantined,
                _ => return Err(Error::CheckpointEncoding),
            };
            Ok(RuntimeModuleRecordV1 {
                abi,
                lifecycle,
                selection_digest: r.optional(Reader::digest)?,
                canary_digest: r.optional(Reader::digest)?,
                handoff_digest: r.optional(Reader::digest)?,
            })
        })?,
        active_reservations: r.list(MAX_RUNTIME_MODULES, |r| {
            Ok(RuntimeModuleActiveReservationV1 {
                module_id: r.id()?,
                generation: r.generation()?,
            })
        })?,
        generation_fences: r.list(MAX_RUNTIME_MODULE_IDENTITIES, |r| {
            Ok(RuntimeModuleGenerationFenceV1 {
                module_id: r.id()?,
                first_generation: r.generation()?,
                greatest_generation: r.generation()?,
            })
        })?,
        checkpoint_digest: r.digest()?,
    };
    if !r.0.is_empty() || encode(&checkpoint) != bytes[..bytes.len() - 32] {
        return Err(Error::CheckpointEncoding);
    }
    Ok(checkpoint)
}

struct Reader<'a>(&'a [u8]);
impl<'a> Reader<'a> {
    fn take(&mut self, count: usize) -> Result<&'a [u8], Error> {
        let (value, rest) = self
            .0
            .split_at_checked(count)
            .ok_or(Error::CheckpointEncoding)?;
        self.0 = rest;
        Ok(value)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        self.take(N)?
            .try_into()
            .map_err(|_| Error::CheckpointEncoding)
    }
    fn byte(&mut self) -> Result<u8, Error> {
        Ok(self.array::<1>()?[0])
    }
    fn generation(&mut self) -> Result<Generation, Error> {
        Generation::new(u64::from_be_bytes(self.array()?)).map_err(|_| Error::CheckpointEncoding)
    }
    fn digest(&mut self) -> Result<Digest32, Error> {
        Ok(Digest32::from_array(self.array()?))
    }
    fn count(&mut self, limit: usize) -> Result<usize, Error> {
        let count =
            usize::try_from(u64::from_be_bytes(self.array()?)).map_err(|_| Error::Bounds)?;
        if count > limit || count > self.0.len() {
            return Err(Error::Bounds);
        }
        Ok(count)
    }
    fn id(&mut self) -> Result<StableId, Error> {
        let count = self.count(/*limit*/ 128)?;
        let text = std::str::from_utf8(self.take(count)?).map_err(|_| Error::CheckpointEncoding)?;
        StableId::new(text).map_err(|_| Error::CheckpointEncoding)
    }
    fn optional<T>(
        &mut self,
        read: impl FnOnce(&mut Self) -> Result<T, Error>,
    ) -> Result<Option<T>, Error> {
        match self.byte()? {
            0 => Ok(None),
            1 => read(self).map(Some),
            _ => Err(Error::CheckpointEncoding),
        }
    }
    fn list<T>(
        &mut self,
        limit: usize,
        read: impl Fn(&mut Self) -> Result<T, Error>,
    ) -> Result<Vec<T>, Error> {
        let count = self.count(limit)?;
        (0..count).map(|_| read(self)).collect()
    }
    fn set(&mut self, limit: usize) -> Result<std::collections::BTreeSet<StableId>, Error> {
        let values = self.list(limit, Reader::id)?;
        if values.windows(/*size*/ 2).any(|pair| pair[0] >= pair[1]) {
            return Err(Error::CheckpointEncoding);
        }
        Ok(values.into_iter().collect())
    }
}
