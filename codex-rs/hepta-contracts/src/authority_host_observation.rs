//! Immutable observations in the existing Root administration directory.
//! These records carry no authority frontier, grant, writer terminal, next
//! generation counter or Current token. The caller must authenticate the
//! original observation before storing its complete bounded canonical bytes.

use super::*;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ObservationRecord {
    schema_version: u32,
    observation_id: String,
    payload: Vec<u8>,
}

/// An exact stored observation after actual file and directory durability.
/// The retained inode and full bytes allow the Root composition to recheck
/// the same record immediately before acknowledging its external source.
/// This value is not usable as any authority, D/K outcome or Current witness.
pub struct RootStoredObservation {
    root: Arc<RootAuthorityDirectory>,
    observation_id: String,
    name: String,
    record: DurableRecord,
    payload: Vec<u8>,
}

impl RootAuthorityDirectory {
    /// Save one authenticated observation exactly once. Identity should bind
    /// the complete boot and external transaction identity; no untrusted path
    /// is accepted. An existing unequal record is a conflict, never replaced.
    /// A visible equal record is fsynced again, including its directory, so a
    /// retry after an interrupted rename cannot mistake visibility for durable
    /// acknowledgement. Each encoded record has the original 16 KiB bound.
    pub fn save_observation(
        self: &Arc<Self>,
        observation_id: &str,
        payload: &[u8],
    ) -> Result<RootStoredObservation, AuthorityTrustError> {
        let name = observation_name(observation_id)?;
        if payload.is_empty() || payload.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let bytes = serde_json::to_vec(&ObservationRecord {
            schema_version: 1,
            observation_id: observation_id.to_string(),
            payload: payload.to_vec(),
        })
        .map_err(|_| AuthorityTrustError::Invalid)?;
        if bytes.len() as u64 > MAX_RECORD_BYTES {
            return Err(AuthorityTrustError::Invalid);
        }
        let _lock = self.lock(&format!("{name}.lock"))?;
        if self.exists(&name)? {
            let (saved, _) = read_record(self, &name, observation_id)?;
            if saved != payload {
                return Err(AuthorityTrustError::Conflict);
            }
        } else {
            // This is the original protected replacement primitive, including
            // stale temporary inode validation and file→rename→directory sync.
            self.replace(&format!("{name}.next"), &name, &bytes)?;
        }
        let (saved, record) = read_record(self, &name, observation_id)?;
        if saved != payload || record.bytes != bytes {
            return Err(AuthorityTrustError::Unavailable);
        }
        record.file.sync_all().map_err(unavailable)?;
        self.sync_directory()?;
        Ok(RootStoredObservation {
            root: self.clone(),
            observation_id: observation_id.to_string(),
            name,
            record,
            payload: saved,
        })
    }
}

impl RootStoredObservation {
    pub fn observation_id(&self) -> &str {
        &self.observation_id
    }
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    /// Revalidate the exact held inode and full original bytes, then perform
    /// the actual durability operations again. Failure must prevent the Root
    /// caller from acknowledging the external kernel retirement receipt.
    pub fn verify_durable(&self) -> Result<(), AuthorityTrustError> {
        let _lock = self.root.lock(&format!("{}.lock", self.name))?;
        let (payload, record) = read_record(&self.root, &self.name, &self.observation_id)?;
        if payload != self.payload || !self.record.matches(&record)? {
            return Err(AuthorityTrustError::Unavailable);
        }
        record.file.sync_all().map_err(unavailable)?;
        self.root.sync_directory()
    }
}

fn observation_name(observation_id: &str) -> Result<String, AuthorityTrustError> {
    if observation_id.is_empty()
        || observation_id.len() > 128
        || !observation_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:".contains(&byte))
    {
        return Err(AuthorityTrustError::Invalid);
    }
    let digest = Sha256::digest(observation_id.as_bytes());
    let suffix: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    Ok(format!("observation-v1-{suffix}.json"))
}

fn read_record(
    root: &RootAuthorityDirectory,
    name: &str,
    observation_id: &str,
) -> Result<(Vec<u8>, DurableRecord), AuthorityTrustError> {
    let file = root.open_private(name, OFlags::RDONLY)?;
    if file.metadata().map_err(unavailable)?.len() > MAX_RECORD_BYTES {
        return Err(AuthorityTrustError::Invalid);
    }
    let mut bytes = Vec::new();
    (&file)
        .take(MAX_RECORD_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() as u64 > MAX_RECORD_BYTES {
        return Err(AuthorityTrustError::Invalid);
    }
    let record: ObservationRecord =
        serde_json::from_slice(&bytes).map_err(|_| AuthorityTrustError::Invalid)?;
    if record.schema_version != 1
        || record.observation_id != observation_id
        || record.payload.is_empty()
    {
        return Err(AuthorityTrustError::Invalid);
    }
    Ok((record.payload, DurableRecord { file, bytes }))
}
