//! control.engineering-owned self-iteration coordinator for topology proposals.
//!
//! The coordinator binds one immutable `IterationEnvelopeV1` and its canonical
//! mutation-grammar digest to the exact topology generation/admission payloads,
//! authenticates an independent Observer over that frozen context, submits only
//! through the state-held Agentd named producer, and records one create-only
//! terminal receipt. It owns no proposal writer, topology executor, selector,
//! activation, promotion or release authority.

use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;

use codex_hepta_intelligence::TopologyPlasticityProductReceiptV1;
use codex_hepta_intelligence::TopologyPlasticityProductRequestV1;
use codex_hepta_intelligence::topology_admission_signing_payload_v1;
use codex_hepta_intelligence::topology_evaluation_signing_payload_v1;
use codex_hepta_intelligence::topology_generation_signing_payload_v1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::iteration_envelope_digest_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Mutex;

use crate::AgentdState;
use crate::PlasticityRuntimeCallErrorV1;
use crate::create_new_plasticity_file_v1;
use crate::fsync_parent_directory_v1;
use crate::open_existing_plasticity_file_v1;

const TOPOLOGY_RECEIPT_MAGIC: &[u8; 8] = b"HCPTIR01";
const TOPOLOGY_RECEIPT_VERSION: u16 = 1;
const MAX_TOPOLOGY_RECEIPT_BYTES: u64 = 8 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlEngineeringTopologyIterationRequestV1 {
    pub envelope: IterationEnvelopeV1,
    /// Exact semantic digest of the canonical control.engineering-owned
    /// MutationGrammarManifestV1 admitted for this topology iteration.
    pub topology_grammar_digest: Digest32,
    /// Independent Observer signature over
    /// `topology_iteration_observer_payload_v1`.
    pub grammar_observer_attestation: SignedLearningEvidenceV1,
    pub product_request: TopologyPlasticityProductRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlEngineeringTopologyIterationReceiptV1 {
    pub iteration_key_digest: Digest32,
    pub request_digest: Digest32,
    pub envelope_digest: Digest32,
    pub topology_grammar_digest: Digest32,
    pub candidate_generation: u64,
    pub proposal_id: StableId,
    pub proposal_digest: Digest32,
    pub admission_digest: Digest32,
    pub registry_frame_digest: Digest32,
    pub product_composition_digest: Digest32,
    pub grammar_observer_authentication_digest: Digest32,
    pub recorded_at_unix_seconds: u64,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlEngineeringTopologyStoreErrorV1 {
    InvalidRoot,
    InvalidScope,
    Corrupt,
    Conflict,
    Busy,
    Arithmetic,
    Io(std::io::ErrorKind),
}

impl fmt::Display for ControlEngineeringTopologyStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ControlEngineeringTopologyStoreErrorV1 {}
impl From<std::io::Error> for ControlEngineeringTopologyStoreErrorV1 {
    fn from(value: std::io::Error) -> Self {
        Self::Io(value.kind())
    }
}

pub struct ControlEngineeringTopologyReceiptDirectoryV1 {
    root: PathBuf,
    scope_digest: Digest32,
}

impl ControlEngineeringTopologyReceiptDirectoryV1 {
    pub fn open(
        root: PathBuf,
        scope_digest: Digest32,
    ) -> Result<Self, ControlEngineeringTopologyStoreErrorV1> {
        if scope_digest.is_zero() {
            return Err(ControlEngineeringTopologyStoreErrorV1::InvalidScope);
        }
        if !root.is_absolute() {
            return Err(ControlEngineeringTopologyStoreErrorV1::InvalidRoot);
        }
        let metadata = std::fs::symlink_metadata(&root)?;
        if metadata.file_type().is_symlink() || !metadata.is_dir() || root.canonicalize()? != root {
            return Err(ControlEngineeringTopologyStoreErrorV1::InvalidRoot);
        }
        Ok(Self { root, scope_digest })
    }

    pub fn load(
        &self,
        iteration_key_digest: Digest32,
    ) -> Result<
        Option<ControlEngineeringTopologyIterationReceiptV1>,
        ControlEngineeringTopologyStoreErrorV1,
    > {
        let path = self.receipt_path(iteration_key_digest);
        let metadata = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if metadata.file_type().is_symlink()
            || !metadata.is_file()
            || metadata.len() == 0
            || metadata.len() > MAX_TOPOLOGY_RECEIPT_BYTES
        {
            return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
        }
        let mut file = open_existing_plasticity_file_v1(&path, false)
            .map_err(storage_error)?
            .into_file();
        let capacity = usize::try_from(metadata.len())
            .map_err(|_| ControlEngineeringTopologyStoreErrorV1::Arithmetic)?;
        let mut bytes = Vec::with_capacity(capacity);
        file.read_to_end(&mut bytes)?;
        if bytes.len() as u64 != metadata.len() {
            return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
        }
        let receipt = decode_receipt(&bytes, self.scope_digest)?;
        if receipt.iteration_key_digest != iteration_key_digest {
            return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
        }
        Ok(Some(receipt))
    }

    pub fn commit(
        &self,
        receipt: &ControlEngineeringTopologyIterationReceiptV1,
    ) -> Result<
        ControlEngineeringTopologyIterationReceiptV1,
        ControlEngineeringTopologyStoreErrorV1,
    > {
        verify_topology_iteration_receipt(receipt)?;
        if let Some(existing) = self.load(receipt.iteration_key_digest)? {
            return if existing == *receipt {
                Ok(existing)
            } else {
                Err(ControlEngineeringTopologyStoreErrorV1::Conflict)
            };
        }
        let final_path = self.receipt_path(receipt.iteration_key_digest);
        let pending_path = self.root.join(format!(
            ".topology-{}.{}.pending",
            receipt.iteration_key_digest,
            std::process::id()
        ));
        let encoded = encode_receipt(receipt, self.scope_digest)?;
        let mut pending = match create_new_plasticity_file_v1(&pending_path) {
            Ok(file) => file.into_file(),
            Err(crate::PlasticityStorageSecurityErrorV1::Io(
                std::io::ErrorKind::AlreadyExists,
            )) => return Err(ControlEngineeringTopologyStoreErrorV1::Busy),
            Err(error) => return Err(storage_error(error)),
        };
        if let Err(error) = pending.write_all(&encoded).and_then(|_| pending.sync_all()) {
            let _ = std::fs::remove_file(&pending_path);
            return Err(error.into());
        }
        drop(pending);
        match std::fs::hard_link(&pending_path, &final_path) {
            Ok(()) => {
                fsync_parent_directory_v1(&final_path).map_err(storage_error)?;
                std::fs::remove_file(&pending_path)?;
                fsync_parent_directory_v1(&final_path).map_err(storage_error)?;
                Ok(receipt.clone())
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {
                let _ = std::fs::remove_file(&pending_path);
                let existing = self
                    .load(receipt.iteration_key_digest)?
                    .ok_or(ControlEngineeringTopologyStoreErrorV1::Corrupt)?;
                if existing == *receipt {
                    Ok(existing)
                } else {
                    Err(ControlEngineeringTopologyStoreErrorV1::Conflict)
                }
            }
            Err(error) => {
                let _ = std::fs::remove_file(&pending_path);
                Err(error.into())
            }
        }
    }

    fn receipt_path(&self, key: Digest32) -> PathBuf {
        self.root.join(format!("topology-{key}.receipt"))
    }
}

pub trait ControlEngineeringTopologySubmissionV1: Send + Sync {
    fn submit_topology<'a>(
        &'a self,
        request: TopologyPlasticityProductRequestV1,
        now_unix_seconds: u64,
    ) -> Pin<
        Box<
            dyn Future<
                    Output = Result<
                        TopologyPlasticityProductReceiptV1,
                        PlasticityRuntimeCallErrorV1,
                    >,
                > + Send
                + 'a,
        >,
    >;
}

struct AgentdStateTopologySubmissionV1 {
    state: Arc<AgentdState>,
}

impl ControlEngineeringTopologySubmissionV1 for AgentdStateTopologySubmissionV1 {
    fn submit_topology<'a>(
        &'a self,
        request: TopologyPlasticityProductRequestV1,
        now_unix_seconds: u64,
    ) -> Pin<
        Box<
            dyn Future<
                    Output = Result<
                        TopologyPlasticityProductReceiptV1,
                        PlasticityRuntimeCallErrorV1,
                    >,
                > + Send
                + 'a,
        >,
    > {
        Box::pin(async move {
            self.state
                .submit_topology_plasticity_v1(request, now_unix_seconds)
                .await
        })
    }
}

#[derive(Debug)]
pub enum ControlEngineeringTopologyIterationErrorV1 {
    Envelope(String),
    Binding(&'static str),
    Evidence(SignedEvidenceError),
    Product(codex_hepta_intelligence::TopologyPlasticityProductErrorV1),
    Runtime(PlasticityRuntimeCallErrorV1),
    Store(ControlEngineeringTopologyStoreErrorV1),
    Arithmetic,
}

impl fmt::Display for ControlEngineeringTopologyIterationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ControlEngineeringTopologyIterationErrorV1 {}
impl From<SignedEvidenceError> for ControlEngineeringTopologyIterationErrorV1 {
    fn from(value: SignedEvidenceError) -> Self {
        Self::Evidence(value)
    }
}
impl From<codex_hepta_intelligence::TopologyPlasticityProductErrorV1>
    for ControlEngineeringTopologyIterationErrorV1
{
    fn from(value: codex_hepta_intelligence::TopologyPlasticityProductErrorV1) -> Self {
        Self::Product(value)
    }
}
impl From<PlasticityRuntimeCallErrorV1> for ControlEngineeringTopologyIterationErrorV1 {
    fn from(value: PlasticityRuntimeCallErrorV1) -> Self {
        Self::Runtime(value)
    }
}
impl From<ControlEngineeringTopologyStoreErrorV1>
    for ControlEngineeringTopologyIterationErrorV1
{
    fn from(value: ControlEngineeringTopologyStoreErrorV1) -> Self {
        Self::Store(value)
    }
}

pub struct ControlEngineeringTopologyCoordinatorV1 {
    submission: Arc<dyn ControlEngineeringTopologySubmissionV1>,
    verifier: LearningEvidenceVerifierV1,
    receipts: Mutex<ControlEngineeringTopologyReceiptDirectoryV1>,
}

impl ControlEngineeringTopologyCoordinatorV1 {
    pub fn new(
        submission: Arc<dyn ControlEngineeringTopologySubmissionV1>,
        verifier: LearningEvidenceVerifierV1,
        receipts: ControlEngineeringTopologyReceiptDirectoryV1,
    ) -> Self {
        Self {
            submission,
            verifier,
            receipts: Mutex::new(receipts),
        }
    }

    pub async fn submit_topology_iteration(
        &self,
        request: ControlEngineeringTopologyIterationRequestV1,
        now_unix_seconds: u64,
    ) -> Result<
        ControlEngineeringTopologyIterationReceiptV1,
        ControlEngineeringTopologyIterationErrorV1,
    > {
        request
            .envelope
            .validate_at(now_unix_seconds)
            .map_err(ControlEngineeringTopologyIterationErrorV1::Envelope)?;
        let product = &request.product_request;
        validate_frozen_binding(&request)?;
        let envelope_digest = iteration_envelope_digest_v1(&request.envelope)
            .map_err(ControlEngineeringTopologyIterationErrorV1::Envelope)?;
        let observer_payload = topology_iteration_observer_payload_v1(
            envelope_digest,
            request.topology_grammar_digest,
            product,
        )?;
        let product_observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &product.observer_attestation,
            &topology_admission_signing_payload_v1(&product.admission),
            now_unix_seconds,
        )?;
        let grammar_observer = self.verifier.verify(
            LearningEvidenceRoleV1::Observer,
            &request.grammar_observer_attestation,
            &observer_payload,
            now_unix_seconds,
        )?;
        if product_observer.principal() != grammar_observer.principal()
            || product_observer.controller_id() != grammar_observer.controller_id()
        {
            return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
                "topology grammar observer identity",
            ));
        }

        let candidate_generation = product.candidate_generation.get();
        let iteration_key_digest = iteration_key_digest(
            envelope_digest,
            candidate_generation,
            &product.proposal_id,
        )?;
        let request_digest = topology_iteration_request_digest(
            envelope_digest,
            request.topology_grammar_digest,
            &request,
        )?;
        let grammar_observer_authentication_digest = attestation_authentication_digest(
            self.verifier.trust_digest(),
            &request.grammar_observer_attestation,
        );

        let receipts = self.receipts.lock().await;
        if let Some(existing) = receipts.load(iteration_key_digest)? {
            if existing.request_digest != request_digest {
                return Err(ControlEngineeringTopologyIterationErrorV1::Store(
                    ControlEngineeringTopologyStoreErrorV1::Conflict,
                ));
            }
            return Ok(existing);
        }

        let product_receipt = self
            .submission
            .submit_topology(request.product_request, now_unix_seconds)
            .await?;
        let mut receipt = ControlEngineeringTopologyIterationReceiptV1 {
            iteration_key_digest,
            request_digest,
            envelope_digest,
            topology_grammar_digest: request.topology_grammar_digest,
            candidate_generation,
            proposal_id: product_receipt.governed.proposal.proposal_id.clone(),
            proposal_digest: product_receipt.governed.proposal.proposal_digest,
            admission_digest: product_receipt.governed.admission_digest,
            registry_frame_digest: product_receipt.durable.frame_digest,
            product_composition_digest: product_receipt.composition_digest,
            grammar_observer_authentication_digest,
            recorded_at_unix_seconds: now_unix_seconds,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = digest_receipt(&receipt)?;
        verify_topology_iteration_receipt(&receipt)?;
        receipts.commit(&receipt).map_err(Into::into)
    }
}

pub(crate) fn compose_agentd_control_engineering_topology_coordinator_v1(
    state: Arc<AgentdState>,
    verifier: LearningEvidenceVerifierV1,
    receipts: ControlEngineeringTopologyReceiptDirectoryV1,
) -> ControlEngineeringTopologyCoordinatorV1 {
    ControlEngineeringTopologyCoordinatorV1::new(
        Arc::new(AgentdStateTopologySubmissionV1 { state }),
        verifier,
        receipts,
    )
}

pub fn topology_iteration_observer_payload_v1(
    envelope_digest: Digest32,
    topology_grammar_digest: Digest32,
    product: &TopologyPlasticityProductRequestV1,
) -> Result<Vec<u8>, ControlEngineeringTopologyIterationErrorV1> {
    if envelope_digest.is_zero() || topology_grammar_digest.is_zero() {
        return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
            "topology iteration observer context",
        ));
    }
    let generation = topology_generation_signing_payload_v1(product)?;
    let admission = topology_admission_signing_payload_v1(&product.admission);
    let evaluation = topology_evaluation_signing_payload_v1(&product.admission);
    let mut bytes = b"hepta.control-engineering.topology-iteration-observer.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(topology_grammar_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&generation).as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&admission).as_array());
    bytes.extend_from_slice(Digest32::of_bytes(&evaluation).as_array());
    Ok(bytes)
}

fn validate_frozen_binding(
    request: &ControlEngineeringTopologyIterationRequestV1,
) -> Result<(), ControlEngineeringTopologyIterationErrorV1> {
    let envelope = &request.envelope;
    let product = &request.product_request;
    let admission = &product.admission;
    if request.topology_grammar_digest.is_zero()
        || envelope.grammar_digest != request.topology_grammar_digest
    {
        return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
            "topology grammar",
        ));
    }
    if envelope.objective_digest != admission.objective_digest {
        return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
            "topology objective",
        ));
    }
    if product.selected_artifact_digest != admission.selected_artifact_digest
        || product.window != admission.window
        || product.baseline_generation != admission.baseline_generation
        || product.candidate_generation != admission.candidate_generation
        || product.rollback_predecessor_digest != product.selected_artifact_digest
    {
        return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
            "topology frozen context",
        ));
    }
    if product.changes.len() > usize::from(envelope.maximum_candidates) {
        return Err(ControlEngineeringTopologyIterationErrorV1::Binding(
            "topology candidate budget",
        ));
    }
    Ok(())
}

fn iteration_key_digest(
    envelope_digest: Digest32,
    candidate_generation: u64,
    proposal_id: &StableId,
) -> Result<Digest32, ControlEngineeringTopologyIterationErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-iteration-key.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(&candidate_generation.to_be_bytes());
    push_id(&mut bytes, proposal_id)?;
    Ok(Digest32::of_bytes(&bytes))
}

fn topology_iteration_request_digest(
    envelope_digest: Digest32,
    topology_grammar_digest: Digest32,
    request: &ControlEngineeringTopologyIterationRequestV1,
) -> Result<Digest32, ControlEngineeringTopologyIterationErrorV1> {
    let product = &request.product_request;
    let mut bytes = b"hepta.control-engineering.topology-iteration-request.v1\0".to_vec();
    bytes.extend_from_slice(envelope_digest.as_array());
    bytes.extend_from_slice(topology_grammar_digest.as_array());
    push_id(&mut bytes, &product.proposal_id)?;
    bytes.extend_from_slice(product.expected_registry_predecessor.as_array());
    for payload in [
        topology_generation_signing_payload_v1(product)?,
        topology_admission_signing_payload_v1(&product.admission),
        topology_evaluation_signing_payload_v1(&product.admission),
    ] {
        bytes.extend_from_slice(Digest32::of_bytes(&payload).as_array());
    }
    for attestation in [
        &product.generator_attestation,
        &product.observer_attestation,
        &product.evaluator_attestation,
        &request.grammar_observer_attestation,
    ] {
        push_attestation(&mut bytes, attestation)?;
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn attestation_authentication_digest(
    trust_digest: Digest32,
    attestation: &SignedLearningEvidenceV1,
) -> Digest32 {
    let mut bytes = b"hepta.control-engineering.verified-topology-observer.v1\0".to_vec();
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(&attestation.signing_bytes());
    bytes.extend_from_slice(&attestation.signature);
    Digest32::of_bytes(&bytes)
}

fn push_attestation(
    bytes: &mut Vec<u8>,
    attestation: &SignedLearningEvidenceV1,
) -> Result<(), ControlEngineeringTopologyIterationErrorV1> {
    let signing = attestation.signing_bytes();
    push_len(bytes, signing.len())?;
    bytes.extend_from_slice(&signing);
    bytes.extend_from_slice(&attestation.signature);
    Ok(())
}

fn digest_receipt(
    receipt: &ControlEngineeringTopologyIterationReceiptV1,
) -> Result<Digest32, ControlEngineeringTopologyStoreErrorV1> {
    let mut bytes = b"hepta.control-engineering.topology-iteration-receipt.v1\0".to_vec();
    for digest in [
        receipt.iteration_key_digest,
        receipt.request_digest,
        receipt.envelope_digest,
        receipt.topology_grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    push_store_id(&mut bytes, &receipt.proposal_id)?;
    for digest in [
        receipt.proposal_digest,
        receipt.admission_digest,
        receipt.registry_frame_digest,
        receipt.product_composition_digest,
        receipt.grammar_observer_authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.recorded_at_unix_seconds.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn verify_topology_iteration_receipt(
    receipt: &ControlEngineeringTopologyIterationReceiptV1,
) -> Result<(), ControlEngineeringTopologyStoreErrorV1> {
    if receipt.candidate_generation == 0 || receipt.recorded_at_unix_seconds == 0 {
        return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
    }
    for digest in [
        receipt.iteration_key_digest,
        receipt.request_digest,
        receipt.envelope_digest,
        receipt.topology_grammar_digest,
        receipt.proposal_digest,
        receipt.admission_digest,
        receipt.registry_frame_digest,
        receipt.product_composition_digest,
        receipt.grammar_observer_authentication_digest,
        receipt.receipt_digest,
    ] {
        if digest.is_zero() {
            return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
        }
    }
    if digest_receipt(receipt)? != receipt.receipt_digest {
        return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
    }
    Ok(())
}

fn encode_receipt(
    receipt: &ControlEngineeringTopologyIterationReceiptV1,
    scope_digest: Digest32,
) -> Result<Vec<u8>, ControlEngineeringTopologyStoreErrorV1> {
    verify_topology_iteration_receipt(receipt)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(TOPOLOGY_RECEIPT_MAGIC);
    bytes.extend_from_slice(&TOPOLOGY_RECEIPT_VERSION.to_be_bytes());
    bytes.extend_from_slice(scope_digest.as_array());
    for digest in [
        receipt.iteration_key_digest,
        receipt.request_digest,
        receipt.envelope_digest,
        receipt.topology_grammar_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.candidate_generation.to_be_bytes());
    push_store_id(&mut bytes, &receipt.proposal_id)?;
    for digest in [
        receipt.proposal_digest,
        receipt.admission_digest,
        receipt.registry_frame_digest,
        receipt.product_composition_digest,
        receipt.grammar_observer_authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&receipt.recorded_at_unix_seconds.to_be_bytes());
    bytes.extend_from_slice(receipt.receipt_digest.as_array());
    Ok(bytes)
}

fn decode_receipt(
    bytes: &[u8],
    expected_scope: Digest32,
) -> Result<ControlEngineeringTopologyIterationReceiptV1, ControlEngineeringTopologyStoreErrorV1>
{
    let mut cursor = Cursor::new(bytes);
    if cursor.take(8)? != TOPOLOGY_RECEIPT_MAGIC
        || cursor.u16()? != TOPOLOGY_RECEIPT_VERSION
        || cursor.digest()? != expected_scope
    {
        return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
    }
    let receipt = ControlEngineeringTopologyIterationReceiptV1 {
        iteration_key_digest: cursor.digest()?,
        request_digest: cursor.digest()?,
        envelope_digest: cursor.digest()?,
        topology_grammar_digest: cursor.digest()?,
        candidate_generation: cursor.u64()?,
        proposal_id: cursor.stable_id()?,
        proposal_digest: cursor.digest()?,
        admission_digest: cursor.digest()?,
        registry_frame_digest: cursor.digest()?,
        product_composition_digest: cursor.digest()?,
        grammar_observer_authentication_digest: cursor.digest()?,
        recorded_at_unix_seconds: cursor.u64()?,
        receipt_digest: cursor.digest()?,
    };
    if !cursor.is_empty() {
        return Err(ControlEngineeringTopologyStoreErrorV1::Corrupt);
    }
    verify_topology_iteration_receipt(&receipt)?;
    Ok(receipt)
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ControlEngineeringTopologyIterationErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| ControlEngineeringTopologyIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(
    bytes: &mut Vec<u8>,
    value: usize,
) -> Result<(), ControlEngineeringTopologyIterationErrorV1> {
    let value = u32::try_from(value)
        .map_err(|_| ControlEngineeringTopologyIterationErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn push_store_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), ControlEngineeringTopologyStoreErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len())
        .map_err(|_| ControlEngineeringTopologyStoreErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn storage_error(
    error: crate::PlasticityStorageSecurityErrorV1,
) -> ControlEngineeringTopologyStoreErrorV1 {
    match error {
        crate::PlasticityStorageSecurityErrorV1::Io(kind) => {
            ControlEngineeringTopologyStoreErrorV1::Io(kind)
        }
        _ => ControlEngineeringTopologyStoreErrorV1::Corrupt,
    }
}

struct Cursor<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Cursor<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    fn take(
        &mut self,
        count: usize,
    ) -> Result<&'a [u8], ControlEngineeringTopologyStoreErrorV1> {
        let end = self
            .offset
            .checked_add(count)
            .ok_or(ControlEngineeringTopologyStoreErrorV1::Arithmetic)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(ControlEngineeringTopologyStoreErrorV1::Corrupt)?;
        self.offset = end;
        Ok(value)
    }

    fn u16(&mut self) -> Result<u16, ControlEngineeringTopologyStoreErrorV1> {
        let mut raw = [0_u8; 2];
        raw.copy_from_slice(self.take(2)?);
        Ok(u16::from_be_bytes(raw))
    }

    fn u32(&mut self) -> Result<u32, ControlEngineeringTopologyStoreErrorV1> {
        let mut raw = [0_u8; 4];
        raw.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(raw))
    }

    fn u64(&mut self) -> Result<u64, ControlEngineeringTopologyStoreErrorV1> {
        let mut raw = [0_u8; 8];
        raw.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(raw))
    }

    fn digest(&mut self) -> Result<Digest32, ControlEngineeringTopologyStoreErrorV1> {
        let mut raw = [0_u8; 32];
        raw.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(raw))
    }

    fn stable_id(&mut self) -> Result<StableId, ControlEngineeringTopologyStoreErrorV1> {
        let length = usize::try_from(self.u32()?)
            .map_err(|_| ControlEngineeringTopologyStoreErrorV1::Arithmetic)?;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| ControlEngineeringTopologyStoreErrorV1::Corrupt)?;
        StableId::new(value.to_string())
            .map_err(|_| ControlEngineeringTopologyStoreErrorV1::Corrupt)
    }

    fn is_empty(&self) -> bool {
        self.offset == self.bytes.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn topology_iteration_key_binds_envelope_generation_and_proposal() {
        let envelope = digest(b"envelope");
        let first = iteration_key_digest(envelope, 7, &id("proposal:1")).expect("key");
        let generation = iteration_key_digest(envelope, 8, &id("proposal:1")).expect("key");
        let proposal = iteration_key_digest(envelope, 7, &id("proposal:2")).expect("key");
        assert_ne!(first, generation);
        assert_ne!(first, proposal);
    }

    #[test]
    fn receipt_directory_requires_absolute_canonical_root() {
        let directory = tempfile::tempdir().expect("tempdir");
        let root = directory.path().canonicalize().expect("canonical root");
        assert!(
            ControlEngineeringTopologyReceiptDirectoryV1::open(
                root,
                digest(b"topology-receipt-scope"),
            )
            .is_ok()
        );
        assert!(matches!(
            ControlEngineeringTopologyReceiptDirectoryV1::open(
                PathBuf::from("relative"),
                digest(b"topology-receipt-scope"),
            ),
            Err(ControlEngineeringTopologyStoreErrorV1::InvalidRoot)
        ));
    }
}
