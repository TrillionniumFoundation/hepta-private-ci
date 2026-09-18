//! Durable HeptaBao dynamic-secret lease control-plane.
//!
//! Secret values are never persisted here. Provider operations are admitted by
//! kernel final-use authority, journaled before dispatch, and move to Unknown
//! when the provider may have applied an operation without an acknowledgement.
//! Reusing an operation id with changed semantics is rejected; an Unknown
//! operation is never blindly retried.

use std::collections::BTreeMap;
use std::fmt;
use std::fs::File;
use std::io::{BufRead, BufReader, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use codex_hepta_contracts::{FinalUseAuthority, FinalUseBinding, SignedFinalUseGrant};
use codex_hepta_types::Digest32;
use http::StatusCode;
use http::header::HeaderValue;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use zeroize::{Zeroize, Zeroizing};

use crate::https_consumer::{
    BaoClient, BaoClientError, MAX_RESPONSE_BYTES, component, segmented, transport_error,
};

const LEASE_JOURNAL_SCHEMA: u32 = 1;
const MAX_OPERATION_ID_BYTES: usize = 128;
const MAX_PROVIDER_LEASE_ID_BYTES: usize = 2048;
const MAX_DYNAMIC_PATH_BYTES: usize = 1024;
const MAX_PARAMETER_BYTES: usize = 64 * 1024;
const MAX_LEASE_TTL_SECONDS: u64 = 86_400;
const MAX_JOURNAL_BYTES: u64 = 256 * 1024 * 1024;
const MAX_RECORDS_ON_OPEN: usize = 1_000_000;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseState {
    IssuePending,
    Active,
    RenewPending,
    RevokePending,
    Unknown,
    Revoked,
    Expired,
    NotApplied,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LeaseOperationKind {
    Issue,
    Renew,
    Revoke,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DynamicLeaseMethod {
    Get,
    Post,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretLeaseMetadata {
    pub local_lease_id: String,
    pub provider_lease_id: Option<String>,
    pub operation_id: String,
    pub namespace: String,
    pub provider_path: String,
    pub subject_id: String,
    pub consumer_id: String,
    pub state: LeaseState,
    pub renewable: bool,
    pub expires_at_unix_ms: Option<u64>,
    pub generation: u64,
    pub semantic_sha256: [u8; 32],
    pub secret_data_sha256: Option<[u8; 32]>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoDynamicLeaseRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub namespace: String,
    pub provider_path: String,
    pub method: DynamicLeaseMethod,
    pub operation_id: String,
    pub parameters: Value,
    pub max_ttl_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRenewRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub local_lease_id: String,
    pub increment_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BaoLeaseRevokeRequest {
    pub subject_id: String,
    pub consumer_id: String,
    pub operation_id: String,
    pub local_lease_id: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BaoLeaseOutcome {
    Active(SecretLeaseMetadata),
    Revoked(SecretLeaseMetadata),
    Existing(SecretLeaseMetadata),
    Indeterminate(SecretLeaseMetadata),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum ReconciliationObservation {
    Active {
        provider_lease_id: String,
        renewable: bool,
        expires_at_unix_ms: u64,
    },
    Revoked,
    NotApplied,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct JournalEntry {
    schema: u32,
    record: SecretLeaseMetadata,
}

pub struct LeaseRegistry {
    path: PathBuf,
    journal: File,
    _root: File,
    _lock: File,
    records: BTreeMap<String, SecretLeaseMetadata>,
    operations: BTreeMap<String, SecretLeaseMetadata>,
}

impl fmt::Debug for LeaseRegistry {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LeaseRegistry")
            .field("path", &self.path)
            .field("records", &self.records.len())
            .finish_non_exhaustive()
    }
}

impl LeaseRegistry {
    /// Local durable backend. It is intentionally single-active per directory.
    /// Active-active deployments should implement a strongly consistent shared
    /// owner instead of sharing this local journal over NFS.
    pub fn open(directory: &Path) -> Result<Self, BaoClientError> {
        let root = prepare_private_directory(directory)?;
        let lock = open_private_at(&root, "leases.lock", true)?;
        lock.try_lock().map_err(|_| BaoClientError::LeaseStoreLocked)?;
        let mut journal = open_private_at(&root, "leases.journal", true)?;
        let size = journal
            .metadata()
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?
            .len();
        if size > MAX_JOURNAL_BYTES {
            return Err(BaoClientError::LeaseStoreCapacityExceeded);
        }

        journal
            .seek(SeekFrom::Start(0))
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        let reader_file = journal
            .try_clone()
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        let mut records = BTreeMap::new();
        let mut operations = BTreeMap::new();
        for (index, line) in BufReader::new(reader_file).lines().enumerate() {
            if index >= MAX_RECORDS_ON_OPEN {
                return Err(BaoClientError::LeaseStoreCapacityExceeded);
            }
            let line = line.map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
            if line.is_empty() {
                continue;
            }
            let entry: JournalEntry =
                serde_json::from_str(&line).map_err(|_| BaoClientError::LeaseStoreCorrupt)?;
            if entry.schema != LEASE_JOURNAL_SCHEMA || !valid_metadata(&entry.record) {
                return Err(BaoClientError::LeaseStoreCorrupt);
            }
            if let Some(existing) = operations.get(&entry.record.operation_id)
                && (existing.local_lease_id != entry.record.local_lease_id
                    || existing.semantic_sha256 != entry.record.semantic_sha256)
            {
                return Err(BaoClientError::LeaseStoreCorrupt);
            }
            operations.insert(entry.record.operation_id.clone(), entry.record.clone());
            records.insert(entry.record.local_lease_id.clone(), entry.record);
        }
        journal
            .seek(SeekFrom::End(0))
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;

        Ok(Self {
            path: directory.to_path_buf(),
            journal,
            _root: root,
            _lock: lock,
            records,
            operations,
        })
    }

    pub fn get(&self, local_lease_id: &str) -> Option<&SecretLeaseMetadata> {
        self.records.get(local_lease_id)
    }

    pub fn begin_issue(
        &mut self,
        request: &BaoDynamicLeaseRequest,
        semantic_sha256: [u8; 32],
    ) -> Result<BeginResult, BaoClientError> {
        validate_dynamic_request(request)?;
        if let Some(existing) = self.operations.get(&request.operation_id) {
            if existing.semantic_sha256 != semantic_sha256 {
                return Err(BaoClientError::OperationConflict);
            }
            return Ok(BeginResult::Existing(existing.clone()));
        }
        let local_lease_id = local_lease_id(&request.operation_id, semantic_sha256);
        let record = SecretLeaseMetadata {
            local_lease_id,
            provider_lease_id: None,
            operation_id: request.operation_id.clone(),
            namespace: request.namespace.clone(),
            provider_path: request.provider_path.clone(),
            subject_id: request.subject_id.clone(),
            consumer_id: request.consumer_id.clone(),
            state: LeaseState::IssuePending,
            renewable: false,
            expires_at_unix_ms: None,
            generation: 1,
            semantic_sha256,
            secret_data_sha256: None,
        };
        self.append(record.clone())?;
        Ok(BeginResult::Started(record))
    }

    pub fn begin_existing_operation(
        &mut self,
        local_lease_id: &str,
        operation_id: &str,
        subject_id: &str,
        consumer_id: &str,
        kind: LeaseOperationKind,
        semantic_sha256: [u8; 32],
    ) -> Result<BeginResult, BaoClientError> {
        if !identifier(operation_id)
            || !component(subject_id)
            || !component(consumer_id)
            || semantic_sha256 == [0; 32]
        {
            return Err(BaoClientError::InvalidRequest);
        }
        if let Some(existing) = self.operations.get(operation_id) {
            if existing.semantic_sha256 != semantic_sha256 {
                return Err(BaoClientError::OperationConflict);
            }
            return Ok(BeginResult::Existing(existing.clone()));
        }
        let current = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        if current.subject_id != subject_id || current.consumer_id != consumer_id {
            return Err(BaoClientError::InvalidRequest);
        }
        match kind {
            LeaseOperationKind::Renew if current.state != LeaseState::Active || !current.renewable => {
                return Err(BaoClientError::LeaseNotRenewable);
            }
            LeaseOperationKind::Revoke
                if matches!(current.state, LeaseState::Revoked | LeaseState::Expired) =>
            {
                return Ok(BeginResult::Existing(current));
            }
            LeaseOperationKind::Issue => return Err(BaoClientError::InvalidRequest),
            _ => {}
        }
        let mut next = current;
        next.operation_id = operation_id.to_owned();
        next.semantic_sha256 = semantic_sha256;
        next.generation = next.generation.saturating_add(1);
        next.state = match kind {
            LeaseOperationKind::Renew => LeaseState::RenewPending,
            LeaseOperationKind::Revoke => LeaseState::RevokePending,
            LeaseOperationKind::Issue => unreachable!(),
        };
        self.append(next.clone())?;
        Ok(BeginResult::Started(next))
    }

    pub fn mark_active(
        &mut self,
        local_lease_id: &str,
        provider_lease_id: String,
        renewable: bool,
        expires_at_unix_ms: u64,
        secret_data_sha256: Option<[u8; 32]>,
    ) -> Result<SecretLeaseMetadata, BaoClientError> {
        if !provider_lease_id_valid(&provider_lease_id) || expires_at_unix_ms == 0 {
            return Err(BaoClientError::InvalidResponse);
        }
        let mut next = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        next.provider_lease_id = Some(provider_lease_id);
        next.renewable = renewable;
        next.expires_at_unix_ms = Some(expires_at_unix_ms);
        next.secret_data_sha256 = secret_data_sha256;
        next.state = LeaseState::Active;
        self.append(next.clone())?;
        Ok(next)
    }

    pub fn mark_not_applied(
        &mut self,
        local_lease_id: &str,
    ) -> Result<SecretLeaseMetadata, BaoClientError> {
        let mut next = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        next.state = if next.provider_lease_id.is_some() {
            LeaseState::Active
        } else {
            LeaseState::NotApplied
        };
        self.append(next.clone())?;
        Ok(next)
    }

    pub fn mark_unknown(
        &mut self,
        local_lease_id: &str,
    ) -> Result<SecretLeaseMetadata, BaoClientError> {
        let mut next = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        next.state = LeaseState::Unknown;
        self.append(next.clone())?;
        Ok(next)
    }

    pub fn mark_revoked(
        &mut self,
        local_lease_id: &str,
    ) -> Result<SecretLeaseMetadata, BaoClientError> {
        let mut next = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        next.state = LeaseState::Revoked;
        next.renewable = false;
        next.expires_at_unix_ms = None;
        self.append(next.clone())?;
        Ok(next)
    }

    pub fn reconcile(
        &mut self,
        local_lease_id: &str,
        observation: ReconciliationObservation,
    ) -> Result<Option<SecretLeaseMetadata>, BaoClientError> {
        let current = self
            .records
            .get(local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        if current.state != LeaseState::Unknown {
            return Err(BaoClientError::ReconciliationRequired);
        }
        match observation {
            ReconciliationObservation::Active {
                provider_lease_id,
                renewable,
                expires_at_unix_ms,
            } => self
                .mark_active(
                    local_lease_id,
                    provider_lease_id,
                    renewable,
                    expires_at_unix_ms,
                    current.secret_data_sha256,
                )
                .map(Some),
            ReconciliationObservation::Revoked => self.mark_revoked(local_lease_id).map(Some),
            ReconciliationObservation::NotApplied => self.mark_not_applied(local_lease_id).map(Some),
        }
    }

    fn append(&mut self, record: SecretLeaseMetadata) -> Result<(), BaoClientError> {
        if !valid_metadata(&record) {
            return Err(BaoClientError::InvalidRequest);
        }
        let entry = JournalEntry {
            schema: LEASE_JOURNAL_SCHEMA,
            record: record.clone(),
        };
        let mut bytes =
            serde_json::to_vec(&entry).map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        bytes.push(b'\n');
        let current = self
            .journal
            .metadata()
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?
            .len();
        if current.saturating_add(bytes.len() as u64) > MAX_JOURNAL_BYTES {
            return Err(BaoClientError::LeaseStoreCapacityExceeded);
        }
        self.journal
            .write_all(&bytes)
            .and_then(|_| self.journal.sync_data())
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        self.operations.insert(record.operation_id.clone(), record.clone());
        self.records.insert(record.local_lease_id.clone(), record);
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BeginResult {
    Started(SecretLeaseMetadata),
    Existing(SecretLeaseMetadata),
}

impl BaoClient {
    pub fn lease_binding(
        &self,
        request: &BaoDynamicLeaseRequest,
    ) -> Result<FinalUseBinding, BaoClientError> {
        validate_dynamic_request(request)?;
        let parameters = serde_json::to_vec(&request.parameters)
            .map_err(|_| BaoClientError::InvalidRequest)?;
        if parameters.len() > MAX_PARAMETER_BYTES {
            return Err(BaoClientError::InvalidRequest);
        }
        let parameter_sha = Digest32::of_bytes(&parameters).into_array();
        let request_bytes = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.issue.v1",
            self.origin.as_str(),
            self.ca_sha256,
            &request.namespace,
            &request.provider_path,
            request.method,
            &request.operation_id,
            parameter_sha,
            request.max_ttl_seconds,
            &request.subject_id,
            &request.consumer_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.scope.v1",
            self.origin.as_str(),
            &request.namespace,
            &request.provider_path,
            &request.consumer_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: request.subject_id.clone(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request_bytes).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: parameter_sha,
        })
    }

    pub async fn request_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        registry: &mut LeaseRegistry,
        request: &BaoDynamicLeaseRequest,
        consumer: impl FnOnce(&[u8]) -> Result<(), ()>,
    ) -> Result<BaoLeaseOutcome, BaoClientError> {
        let binding = self.lease_binding(request)?;
        let begin = registry.begin_issue(request, binding.request_sha256)?;
        let record = match begin {
            BeginResult::Existing(existing) => return Ok(existing_outcome(existing)),
            BeginResult::Started(record) => record,
        };
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;

        let mut url = self.origin.clone();
        {
            let mut parts = url.path_segments_mut().map_err(|_| BaoClientError::InvalidRequest)?;
            parts.clear().push("v1");
            for part in request.provider_path.split('/') {
                parts.push(part);
            }
        }
        let token = self.token_header()?;
        let mut network = match request.method {
            DynamicLeaseMethod::Get => self.client.get(url).query(&request.parameters),
            DynamicLeaseMethod::Post => self
                .client
                .post(url)
                .header("Content-Type", "application/json")
                .json(&request.parameters),
        }
        .header("X-Vault-Token", token)
        .header("Accept", "application/json")
        .header("X-Hepta-Operation-Id", &request.operation_id);
        if !request.namespace.is_empty() {
            network = network.header("X-Vault-Namespace", &request.namespace);
        }

        let mut response = match network.send().await {
            Ok(response) => response,
            Err(error) => {
                let mapped = transport_error(error);
                if matches!(mapped, BaoClientError::TimedOut | BaoClientError::TransportUnavailable) {
                    return registry
                        .mark_unknown(&record.local_lease_id)
                        .map(BaoLeaseOutcome::Indeterminate);
                }
                return Err(mapped);
            }
        };
        match response.status() {
            StatusCode::OK => {}
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN => {
                registry.mark_not_applied(&record.local_lease_id)?;
                return Err(BaoClientError::ProviderDenied);
            }
            StatusCode::NOT_FOUND => {
                registry.mark_not_applied(&record.local_lease_id)?;
                return Err(BaoClientError::NotFound);
            }
            _ => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        }
        let mut body = match read_bounded_body(&mut response).await {
            Ok(body) => body,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        let decoded: DynamicLeaseResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        if !provider_lease_id_valid(&decoded.lease_id)
            || decoded.lease_duration == 0
            || decoded.lease_duration > request.max_ttl_seconds
        {
            return registry
                .mark_unknown(&record.local_lease_id)
                .map(BaoLeaseOutcome::Indeterminate);
        }
        let mut secret_json = Zeroizing::new(
            serde_json::to_vec(&decoded.data).map_err(|_| BaoClientError::InvalidResponse)?,
        );
        let secret_digest = Digest32::of_bytes(&secret_json).into_array();
        let expires = unix_ms_now()?
            .checked_add(decoded.lease_duration.saturating_mul(1000))
            .ok_or(BaoClientError::InvalidResponse)?;
        let active = registry.mark_active(
            &record.local_lease_id,
            decoded.lease_id,
            decoded.renewable,
            expires,
            Some(secret_digest),
        )?;
        authority
            .with_verified_use(verified, &binding, || consumer(&secret_json))
            .map_err(BaoClientError::Authority)?
            .map_err(|()| BaoClientError::ConsumerIndeterminate)?;
        secret_json.zeroize();
        body.zeroize();
        Ok(BaoLeaseOutcome::Active(active))
    }

    pub async fn renew_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        registry: &mut LeaseRegistry,
        request: &BaoLeaseRenewRequest,
    ) -> Result<BaoLeaseOutcome, BaoClientError> {
        if request.increment_seconds == 0 || request.increment_seconds > MAX_LEASE_TTL_SECONDS {
            return Err(BaoClientError::InvalidRequest);
        }
        let current = registry
            .get(&request.local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        let provider_lease_id = current
            .provider_lease_id
            .clone()
            .ok_or(BaoClientError::ReconciliationRequired)?;
        let binding = self.lifecycle_binding(
            "renew",
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.local_lease_id,
            Some(request.increment_seconds),
            &provider_lease_id,
        )?;
        let begin = registry.begin_existing_operation(
            &request.local_lease_id,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
            LeaseOperationKind::Renew,
            binding.request_sha256,
        )?;
        let record = match begin {
            BeginResult::Existing(existing) => return Ok(existing_outcome(existing)),
            BeginResult::Started(record) => record,
        };
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        let mut url = self.origin.clone();
        url.set_path("/v1/sys/leases/renew");
        let mut network = self
            .client
            .post(url)
            .header("X-Vault-Token", self.token_header()?)
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .header("X-Hepta-Operation-Id", &request.operation_id)
            .json(&serde_json::json!({
                "lease_id": provider_lease_id,
                "increment": request.increment_seconds,
            }));
        if !record.namespace.is_empty() {
            network = network.header("X-Vault-Namespace", &record.namespace);
        }
        let mut response = match network.send().await {
            Ok(response) => response,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        if response.status() != StatusCode::OK {
            if matches!(response.status(), StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
                return Err(BaoClientError::ProviderDenied);
            }
            return registry
                .mark_unknown(&record.local_lease_id)
                .map(BaoLeaseOutcome::Indeterminate);
        }
        let body = match read_bounded_body(&mut response).await {
            Ok(body) => body,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        let decoded: LeaseRenewResponse = match serde_json::from_slice(&body) {
            Ok(decoded) => decoded,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        if decoded.lease_duration == 0 || decoded.lease_duration > MAX_LEASE_TTL_SECONDS {
            return registry
                .mark_unknown(&record.local_lease_id)
                .map(BaoLeaseOutcome::Indeterminate);
        }
        let expires = unix_ms_now()?
            .checked_add(decoded.lease_duration.saturating_mul(1000))
            .ok_or(BaoClientError::InvalidResponse)?;
        drop(verified);
        let active = registry.mark_active(
            &record.local_lease_id,
            decoded.lease_id.unwrap_or(provider_lease_id),
            decoded.renewable,
            expires,
            record.secret_data_sha256,
        )?;
        Ok(BaoLeaseOutcome::Active(active))
    }

    pub async fn revoke_secret_lease(
        &self,
        authority: &FinalUseAuthority,
        grant: &SignedFinalUseGrant,
        registry: &mut LeaseRegistry,
        request: &BaoLeaseRevokeRequest,
    ) -> Result<BaoLeaseOutcome, BaoClientError> {
        let current = registry
            .get(&request.local_lease_id)
            .cloned()
            .ok_or(BaoClientError::LeaseNotFound)?;
        if current.state == LeaseState::Revoked {
            return Ok(BaoLeaseOutcome::Existing(current));
        }
        let provider_lease_id = current
            .provider_lease_id
            .clone()
            .ok_or(BaoClientError::ReconciliationRequired)?;
        let binding = self.lifecycle_binding(
            "revoke",
            &request.subject_id,
            &request.consumer_id,
            &request.operation_id,
            &request.local_lease_id,
            None,
            &provider_lease_id,
        )?;
        let begin = registry.begin_existing_operation(
            &request.local_lease_id,
            &request.operation_id,
            &request.subject_id,
            &request.consumer_id,
            LeaseOperationKind::Revoke,
            binding.request_sha256,
        )?;
        let record = match begin {
            BeginResult::Existing(existing) => return Ok(existing_outcome(existing)),
            BeginResult::Started(record) => record,
        };
        let verified = authority
            .claim(grant, &binding)
            .map_err(BaoClientError::Authority)?;
        let mut url = self.origin.clone();
        url.set_path("/v1/sys/leases/revoke");
        let mut network = self
            .client
            .post(url)
            .header("X-Vault-Token", self.token_header()?)
            .header("Content-Type", "application/json")
            .header("X-Hepta-Operation-Id", &request.operation_id)
            .json(&serde_json::json!({"lease_id": provider_lease_id, "sync": true}));
        if !record.namespace.is_empty() {
            network = network.header("X-Vault-Namespace", &record.namespace);
        }
        let response = match network.send().await {
            Ok(response) => response,
            Err(_) => {
                return registry
                    .mark_unknown(&record.local_lease_id)
                    .map(BaoLeaseOutcome::Indeterminate);
            }
        };
        if !matches!(response.status(), StatusCode::OK | StatusCode::NO_CONTENT) {
            if matches!(response.status(), StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN) {
                return Err(BaoClientError::ProviderDenied);
            }
            return registry
                .mark_unknown(&record.local_lease_id)
                .map(BaoLeaseOutcome::Indeterminate);
        }
        drop(verified);
        registry
            .mark_revoked(&record.local_lease_id)
            .map(BaoLeaseOutcome::Revoked)
    }

    fn lifecycle_binding(
        &self,
        verb: &str,
        subject_id: &str,
        consumer_id: &str,
        operation_id: &str,
        local_lease_id: &str,
        increment_seconds: Option<u64>,
        provider_lease_id: &str,
    ) -> Result<FinalUseBinding, BaoClientError> {
        if !component(subject_id)
            || !component(consumer_id)
            || !identifier(operation_id)
            || !identifier(local_lease_id)
            || !provider_lease_id_valid(provider_lease_id)
        {
            return Err(BaoClientError::InvalidRequest);
        }
        let payload = serde_json::to_vec(&(
            verb,
            operation_id,
            local_lease_id,
            provider_lease_id,
            increment_seconds,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let request = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.lifecycle.v1",
            self.origin.as_str(),
            self.ca_sha256,
            subject_id,
            consumer_id,
            &payload,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        let scope = serde_json::to_vec(&(
            "hepta.bao.dynamic-lease.lifecycle-scope.v1",
            self.origin.as_str(),
            consumer_id,
            provider_lease_id,
        ))
        .map_err(|_| BaoClientError::InvalidRequest)?;
        Ok(FinalUseBinding {
            subject_id: subject_id.to_owned(),
            destination_id: "provider:heptabao".to_owned(),
            request_sha256: Digest32::of_bytes(&request).into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: Digest32::of_bytes(&payload).into_array(),
        })
    }

    fn token_header(&self) -> Result<HeaderValue, BaoClientError> {
        let mut token = HeaderValue::from_str(&self.token.0)
            .map_err(|_| BaoClientError::InvalidConfiguration)?;
        token.set_sensitive(true);
        Ok(token)
    }
}

#[derive(Deserialize)]
struct DynamicLeaseResponse {
    lease_id: String,
    renewable: bool,
    lease_duration: u64,
    data: BTreeMap<String, Zeroizing<String>>,
}

#[derive(Deserialize)]
struct LeaseRenewResponse {
    lease_id: Option<String>,
    renewable: bool,
    lease_duration: u64,
}

async fn read_bounded_body(
    response: &mut codex_http_client::HttpResponse,
) -> Result<Zeroizing<Vec<u8>>, BaoClientError> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_RESPONSE_BYTES as u64)
    {
        return Err(BaoClientError::ResponseTooLarge);
    }
    let mut body = Zeroizing::new(Vec::new());
    while let Some(chunk) = response.chunk().await.map_err(transport_error)? {
        if chunk.len() > MAX_RESPONSE_BYTES - body.len() {
            return Err(BaoClientError::ResponseTooLarge);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn validate_dynamic_request(request: &BaoDynamicLeaseRequest) -> Result<(), BaoClientError> {
    if !component(&request.subject_id)
        || !component(&request.consumer_id)
        || (!request.namespace.is_empty() && !segmented(&request.namespace))
        || !segmented(&request.provider_path)
        || request.provider_path.len() > MAX_DYNAMIC_PATH_BYTES
        || !identifier(&request.operation_id)
        || request.max_ttl_seconds == 0
        || request.max_ttl_seconds > MAX_LEASE_TTL_SECONDS
    {
        return Err(BaoClientError::InvalidRequest);
    }
    let parameters =
        serde_json::to_vec(&request.parameters).map_err(|_| BaoClientError::InvalidRequest)?;
    if parameters.len() > MAX_PARAMETER_BYTES {
        return Err(BaoClientError::InvalidRequest);
    }
    Ok(())
}

fn valid_metadata(record: &SecretLeaseMetadata) -> bool {
    identifier(&record.local_lease_id)
        && identifier(&record.operation_id)
        && (record.namespace.is_empty() || segmented(&record.namespace))
        && segmented(&record.provider_path)
        && component(&record.subject_id)
        && component(&record.consumer_id)
        && record.generation > 0
        && record.semantic_sha256 != [0; 32]
        && record
            .provider_lease_id
            .as_ref()
            .is_none_or(|value| provider_lease_id_valid(value))
}

fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_OPERATION_ID_BYTES
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

fn provider_lease_id_valid(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_PROVIDER_LEASE_ID_BYTES
        && !value.bytes().any(|b| b.is_ascii_control())
}

fn local_lease_id(operation_id: &str, semantic_sha256: [u8; 32]) -> String {
    let digest = Digest32::of_bytes(
        &[operation_id.as_bytes(), semantic_sha256.as_slice()].concat(),
    )
    .to_string();
    format!("lease:{}", &digest[..32])
}

fn existing_outcome(record: SecretLeaseMetadata) -> BaoLeaseOutcome {
    match record.state {
        LeaseState::Active => BaoLeaseOutcome::Existing(record),
        LeaseState::Revoked => BaoLeaseOutcome::Revoked(record),
        LeaseState::Unknown | LeaseState::IssuePending | LeaseState::RenewPending | LeaseState::RevokePending => {
            BaoLeaseOutcome::Indeterminate(record)
        }
        LeaseState::Expired | LeaseState::NotApplied => BaoLeaseOutcome::Existing(record),
    }
}

fn unix_ms_now() -> Result<u64, BaoClientError> {
    use std::time::{SystemTime, UNIX_EPOCH};
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| BaoClientError::ProviderUnavailable)?
        .as_millis();
    u64::try_from(millis).map_err(|_| BaoClientError::ProviderUnavailable)
}

fn prepare_private_directory(path: &Path) -> Result<File, BaoClientError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::{DirBuilderExt, MetadataExt};
        if let Err(error) = std::fs::DirBuilder::new().mode(0o700).create(path)
            && error.kind() != std::io::ErrorKind::AlreadyExists
        {
            return Err(BaoClientError::LeaseStoreUnavailable);
        }
        let directory: File = rustix::fs::open(
            path,
            rustix::fs::OFlags::RDONLY
                | rustix::fs::OFlags::DIRECTORY
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::empty(),
        )
        .map_err(|_| BaoClientError::InvalidConfiguration)?
        .into();
        let metadata = directory
            .metadata()
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        if !metadata.is_dir()
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(BaoClientError::InvalidConfiguration);
        }
        Ok(directory)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        Err(BaoClientError::InvalidConfiguration)
    }
}

fn open_private_at(
    directory: &File,
    name: &str,
    create: bool,
) -> Result<File, BaoClientError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let flags = if create {
            rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE
        } else {
            rustix::fs::OFlags::RDWR
        } | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::CLOEXEC;
        let file: File = rustix::fs::openat(
            directory,
            name,
            flags,
            rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        )
        .map_err(|_| BaoClientError::LeaseStoreUnavailable)?
        .into();
        let metadata = file
            .metadata()
            .map_err(|_| BaoClientError::LeaseStoreUnavailable)?;
        if !metadata.is_file()
            || metadata.mode() & 0o077 != 0
            || metadata.nlink() != 1
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(BaoClientError::InvalidConfiguration);
        }
        Ok(file)
    }
    #[cfg(not(unix))]
    {
        let _ = (directory, name, create);
        Err(BaoClientError::InvalidConfiguration)
    }
}

#[cfg(test)]
#[path = "lease_control_tests.rs"]
mod tests;
