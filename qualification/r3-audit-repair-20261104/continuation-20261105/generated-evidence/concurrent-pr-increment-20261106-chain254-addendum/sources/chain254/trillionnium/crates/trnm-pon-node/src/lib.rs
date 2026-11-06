//! Experimental native composition; never imports Python or activates production.
#![forbid(unsafe_code)]
mod ancestry_index;
pub mod consensus;
mod error;
/// One fixed Linux cgroup-v2 parent checker, shared by CLI and public V3 library.
pub mod host_kernel_parent;
pub mod ingress;
pub mod mining;
pub mod operator_checkpoint_tile;
pub mod operator_continuous_controller;
mod operator_continuous_cpu;
mod operator_continuous_history;
mod operator_continuous_lease;
pub mod operator_continuous_policy;
pub mod operator_continuous_pool;
mod operator_continuous_recipient;
mod operator_continuous_recovery;
pub mod operator_deployment;
pub mod operator_mining_controller;
pub mod operator_mining_policy;
pub(crate) mod operator_pq_auth;
pub mod operator_pq_startup;
pub mod operator_task_policy;
pub mod peer_polling;
pub mod pq_application_v6;
pub mod pq_rollback_witness;
pub mod public_submit;
/// Isolated V2 certificate reader; never votes, installs models or activates consensus.
pub mod release_finality;
mod store;
pub use error::{Error, ErrorCode, ErrorKind};
use serde_json::{json, Value};
pub use store::authenticated_migration::{
    verify_growth_rehearsal_v2, verify_growth_rehearsal_v2_with_snapshot_byte_limit,
    AuthenticatedMigrationProgress, AuthenticatedMigrationReceipt, GrowthMigrationPlanV2,
    GrowthRehearsalProgressV2, GrowthRehearsalReceiptV2, GrowthStorageReservationV2,
    PreservedTable, DEFAULT_GROWTH_REHEARSAL_SNAPSHOT_BYTE_LIMIT_V2,
};
pub use store::capacity_observation::CapacityObservation;
pub use store::evaluation_observation::{EvaluationAnchor, EvaluationObservation, EvaluationPhase};
pub use store::evaluation_round_observation::{
    EvaluationRoundAnchor, EvaluationRoundBaseAnchor, EvaluationRoundObservation,
};
pub use store::growth::{GrowthObservation, GrowthPacket, GrowthProgress, GrowthWorkingSnapshot};
pub use store::growth_reference::GrowthReferenceObservation;
pub use store::mempool::{
    PoolBatch, PoolGcSummary, PoolGroupStatus, PoolLimits, PoolReceipt, PoolState, PoolStatus,
    LOCAL_POOL_PROFILE,
};
pub use store::native_budget::{
    NativeBudgetInventoryV1, NativeBudgetLaneV1, NativeBudgetLocalRecordV1,
    NativeBudgetObservationV1, NativeBudgetRequestV1, NativeContributionClaimV1,
};
pub use store::pinned_account_query::PinnedNativeAccountQuery;
pub use store::storage_service::{
    native_cell_release_repair_subject_v2, native_cell_repair_subject_v1,
    NativeCellEffectReadbackV1, NativeCellReleaseEffectReadbackV2,
    NativeCellReleaseRepairRequestV2, NativeCellReleaseRetentionRequestV2,
    NativeCellReleaseRetirementReadbackV2, NativeCellRepairCpuObservationV1,
    NativeCellRepairRequestV1, NativeCellRetentionRequestV1,
};
pub use store::{
    ConfirmationBatch, ContinuousSearchRequest, DerivedCommitmentStatus, MiningEpochCancellation,
    NativeAccountProofProgress, Node, Observation, OwnedContinuousLeaseResult,
    OwnedContinuousPoolResult, OwnedMutationResult, OwnedSearchResult,
};
use trnm_crypto_primitives::pon_work;
use trnm_crypto_primitives::qualified_work_task::{derive_matrices, AdmissionContext};
use trnm_mvcc_fee::continuity_v1::{self, PROFILE as CONTINUITY_TASK_PROFILE};
use trnm_mvcc_fee::growth_profile_v2::PROFILE as GROWTH_TASK_PROFILE;
use trnm_mvcc_fee::pon_executor::{self, Config, State};
use trnm_mvcc_fee::pon_executor::{LEGACY_TASK_PROFILE, QUALIFIED_DEMANDS, SIGNED_TASK_PROFILE};
use trnm_mvcc_fee::qualified_task_lifecycle;
use trnm_protocol::pon_wire::{hash, Envelope, Hash, Header, HEADER_BYTES};
use trnm_protocol::qualified_work_task::lifecycle_v2::PROFILE as LIFECYCLE_TASK_PROFILE;
use trnm_protocol::qualified_work_task::lifecycle_v3::PROFILE as ATOMIC_TASK_PROFILE;
use trnm_protocol::qualified_work_task::lifecycle_v4::PROFILE as OVERLAP_TASK_PROFILE;
use trnm_protocol::qualified_work_task::{
    QualifiedWorkTask, SignedQualifiedWorkTask, TaskPurpose, LOGICAL_MULTIPLY_ADD_UNITS,
    MATRIX_ARTIFACT_BYTES,
};

/// Explicit research point-access proof gating over a complete native State.
pub mod account_archive_execution;
/// Explicit shadow account-archive research; never installed by Node lifecycle.
pub mod account_archive_prototype;
/// Explicit durable authenticated-state research; never installed by Node lifecycle.
pub mod authenticated_state_archive;

pub type Result<T> = std::result::Result<T, Error>;
/// (model bytes, input bytes, derived A, derived B) for the public maintenance fixture.
pub type BootstrapTaskMaterial = (Vec<u8>, Vec<u8>, Vec<u32>, Vec<u32>);
pub(crate) fn ensure(ok: bool, message: &str) -> Result<()> {
    if ok {
        Ok(())
    } else {
        Err(message.into())
    }
}
pub fn digest(text: &str) -> Result<Hash> {
    ensure(
        text.len() == 64
            && text
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "HASH",
    )?;
    let mut out = [0; 32];
    hex::decode_to_slice(text, &mut out).map_err(|_| Error::from("HASH"))?;
    Ok(out)
}
/// Fixed authenticated-development transport profile. This binds replay and signature
/// semantics only; it is not a production-network or confidentiality claim.
pub fn authenticated_profile_digest() -> Hash {
    hash(
        b"native-authenticated-development-v1",
        &[b"ed25519-strict/canonical-json/durable-replay"],
    )
}

/// Canonical logical request identity used by both the wire signature and durable replay owner.
pub fn authenticated_payload_digest(bytes: &[u8]) -> Hash {
    hash(b"native-authenticated-payload-v1", &[bytes])
}

pub fn sequence_root(tag: &str, items: &[Vec<u8>]) -> Hash {
    let mut leaves: Vec<_> = items
        .iter()
        .enumerate()
        .map(|(i, b)| {
            hash(
                format!("{tag}-leaf").as_bytes(),
                &[&(i as u64).to_le_bytes(), b],
            )
        })
        .collect();
    if leaves.is_empty() {
        return hash(format!("{tag}-empty").as_bytes(), &[]);
    }
    while leaves.len() > 1 {
        if leaves.len() % 2 == 1 {
            leaves.push(*leaves.last().expect("nonempty"));
        }
        leaves = leaves
            .chunks_exact(2)
            .map(|p| hash(format!("{tag}-node").as_bytes(), &[&p[0], &p[1]]))
            .collect();
    }
    leaves[0]
}

/// Fixed-size work packet. Decoding grants neither work nor state authority.
#[derive(Clone, Debug)]
pub struct Packet {
    pub header: Header,
    pub transactions: Vec<Vec<u8>>,
    pub proof: Vec<u8>,
}
impl Packet {
    fn transaction_wire(raw: &[u8]) -> Result<()> {
        if raw.starts_with(b"QTX1") {
            // Parsing supplies no authorization. The selected M06 profile must
            // still perform real PQ verification; every legacy profile refuses.
            trnm_protocol::pq_transaction::decode_signed(raw)
                .map_err(|_| Error::from("TRANSACTION_CODEC"))?;
        } else {
            ensure((159..=2048).contains(&raw.len()), "TRANSACTION_LIMIT")?;
            Envelope::decode(raw).map_err(|_| Error::from("TRANSACTION_CODEC"))?;
        }
        Ok(())
    }
    /// Exact length after the complete original count/proof/envelope grammar.
    /// This is computation only, never packet, work or durable-state authority.
    pub(crate) fn checked_wire_length(&self) -> Result<usize> {
        ensure(
            self.transactions.len() <= 256 && self.proof.len() == pon_work::PROOF_BYTES,
            "PACKET_LIMIT",
        )?;
        // Validate in the original order before reserving transaction payloads.
        // In particular, a bad first envelope must not cause a large allocation
        // merely because later caller-supplied transactions have large lengths.
        let mut length = HEADER_BYTES + 2 + self.proof.len();
        for tx in &self.transactions {
            Self::transaction_wire(tx)?;
            length += 2 + tx.len();
        }
        ensure(length <= 1_048_576, "PACKET_LIMIT")?;
        Ok(length)
    }
    pub fn encode(&self) -> Result<Vec<u8>> {
        let length = self.checked_wire_length()?;
        let mut out = self.header.encode();
        // One bounded reservation removes intermediate payload growth/copies.
        // The validated transactions and proof are still copied into owned wire
        // bytes, and neither decoding nor final native validation is skipped.
        out.reserve_exact(length - out.len());
        out.extend((self.transactions.len() as u16).to_le_bytes());
        for tx in &self.transactions {
            out.extend((tx.len() as u16).to_le_bytes());
            out.extend(tx);
        }
        out.extend(&self.proof);
        ensure(out.len() <= 1_048_576, "PACKET_LIMIT")?;
        Ok(out)
    }
    pub fn decode(bytes: &[u8]) -> Result<Self> {
        ensure(
            (HEADER_BYTES + 2 + pon_work::PROOF_BYTES..=1_048_576).contains(&bytes.len()),
            "PACKET_LIMIT",
        )?;
        let header =
            Header::decode(&bytes[..HEADER_BYTES]).map_err(|_| Error::from("HEADER_CODEC"))?;
        let count = u16::from_le_bytes([bytes[HEADER_BYTES], bytes[HEADER_BYTES + 1]]) as usize;
        ensure(count <= 256, "TRANSACTION_LIMIT")?;
        let mut pos = HEADER_BYTES + 2;
        let mut transactions = Vec::with_capacity(count);
        for _ in 0..count {
            let len = bytes.get(pos..pos + 2).ok_or("PACKET_LENGTH")?;
            let n = u16::from_le_bytes([len[0], len[1]]) as usize;
            pos += 2;
            let qtx = bytes.get(pos..pos + 4) == Some(b"QTX1".as_slice());
            ensure(
                (159..=if qtx { 8192 } else { 2048 }).contains(&n),
                "TRANSACTION_LIMIT",
            )?;
            let tx = bytes.get(pos..pos + n).ok_or("PACKET_LENGTH")?;
            Self::transaction_wire(tx)?;
            transactions.push(tx.to_vec());
            pos += n;
        }
        ensure(bytes.len() - pos == pon_work::PROOF_BYTES, "PACKET_LENGTH")?;
        Ok(Self {
            header,
            transactions,
            proof: bytes[pos..].to_vec(),
        })
    }
    pub fn id(&self) -> Result<Hash> {
        ensure(self.proof.len() == pon_work::PROOF_BYTES, "WORK_LENGTH")?;
        let mut trace = [0; 32];
        trace.copy_from_slice(&self.proof[self.proof.len() - 32..]);
        Ok(self.header.block_id(trace))
    }
}

#[derive(Clone)]
pub struct Settings {
    pub(crate) app: Config,
    pub(crate) genesis: Hash,
    pub(crate) initial: State,
    pub(crate) operator_bootstrap: Option<qualified_task_lifecycle::BootstrapLifecycleTask>,
    pub(crate) operator_material: Option<BootstrapTaskMaterial>,
    pub(crate) checkpoint_tile_paths: Option<operator_checkpoint_tile::CheckpointTileRuntimePaths>,
}
impl Settings {
    /// Explicit fresh transfer-only PQ account genesis. PQG1 dual-signature
    /// import preserves all source nonce floors and locked liability records.
    /// The source/export and revocation pins still need independent M13 authority;
    /// this library API does not activate a network or release deployed assets.
    #[cfg(feature = "pq-native-openssl")]
    pub fn from_pq_account_import(
        imported: pon_executor::pq_accounts::VerifiedPqGenesis,
    ) -> Result<Self> {
        let (app, mut initial) = imported.into_execution_parts();
        ensure(app.is_pq_account_profile(), "PQ_ACCOUNT_PROFILE")?;
        let (a, b) = maintenance();
        let task = pon_work::task_id(&a, &b).map_err(|_| Error::from("WORK_TASK"))?;
        initial.insert(format!("work:{}", hex::encode(task)), json!(true));
        let time = app.params["genesis_timestamp"].as_u64().ok_or("CONFIG")?;
        let genesis = hash(
            b"native-pq-account-genesis-v1",
            &[
                &app.network,
                &app.parameters,
                &pon_executor::root_for_config(&initial, &app)?,
                &time.to_le_bytes(),
            ],
        );
        Ok(Self {
            app,
            genesis,
            initial,
            operator_bootstrap: None,
            operator_material: None,
            checkpoint_tile_paths: None,
        })
    }
    /// An explicit new timestamp selects a distinct valueless devnet, not a hot upgrade.
    pub fn development(genesis_timestamp: Option<u64>) -> Result<Self> {
        Self::development_with_evaluation_policy(genesis_timestamp, "legacy-first-two-v3")
    }
    pub fn development_with_evaluation_policy(
        genesis_timestamp: Option<u64>,
        policy: &str,
    ) -> Result<Self> {
        Self::development_with_profiles(genesis_timestamp, policy, LEGACY_TASK_PROFILE)
    }
    pub fn development_with_profiles(
        genesis_timestamp: Option<u64>,
        policy: &str,
        task_profile: &str,
    ) -> Result<Self> {
        Self::development_with_model_profiles(
            genesis_timestamp,
            policy,
            task_profile,
            "linear-expert-dev-v1",
        )
    }
    pub fn development_with_model_profiles(
        genesis_timestamp: Option<u64>,
        policy: &str,
        task_profile: &str,
        model_profile: &str,
    ) -> Result<Self> {
        Self::development_with_model_profiles_and_task_windows(
            genesis_timestamp,
            policy,
            task_profile,
            model_profile,
            None,
        )
    }
    pub fn development_with_model_profiles_and_task_windows(
        genesis_timestamp: Option<u64>,
        policy: &str,
        task_profile: &str,
        model_profile: &str,
        windows: Option<trnm_mvcc_fee::model_task_windows_v1::PinnedTaskWindows<'_>>,
    ) -> Result<Self> {
        let mut app = Config::installed_with_model_profiles_and_task_windows(
            policy,
            task_profile,
            model_profile,
            windows,
        )?;
        if let Some(time) = genesis_timestamp {
            ensure(time > 0 && time <= i64::MAX as u64, "GENESIS_TIME")?;
            app.params["genesis_timestamp"] = json!(time);
            let label = if task_profile == GROWTH_TASK_PROFILE {
                format!("trnm-pon-growth-reference-v2-17-{policy}-{time}")
            } else if matches!(
                task_profile,
                LIFECYCLE_TASK_PROFILE
                    | ATOMIC_TASK_PROFILE
                    | OVERLAP_TASK_PROFILE
                    | CONTINUITY_TASK_PROFILE
                    | GROWTH_TASK_PROFILE
            ) {
                format!(
                    "trnm-pon-task-lifecycle-wall-devnet-{}-{policy}-{time}",
                    app.params["consensus_revision"].as_u64().ok_or("CONFIG")?
                )
            } else if task_profile == SIGNED_TASK_PROFILE {
                let revision = app.params["consensus_revision"].as_u64().ok_or("CONFIG")?;
                format!("trnm-pon-signed-task-wall-devnet-{revision}-{policy}-{time}")
            } else if policy == "legacy-first-two-v3" {
                format!("trnm-pon-native-wall-devnet-3-{time}")
            } else if policy == "native-public-evaluation-dev-v1" {
                format!("trnm-pon-native-evaluation-wall-devnet-6-{policy}-{time}")
            } else if policy == trnm_mvcc_fee::public_evaluation::QUORUM_PROFILE {
                let revision = app.params["consensus_revision"].as_u64().ok_or("CONFIG")?;
                format!("trnm-pon-native-evaluation-quorum-wall-devnet-{revision}-{policy}-{time}")
            } else {
                format!("trnm-pon-native-wall-devnet-4-{policy}-{time}")
            };
            let label = if matches!(
                policy,
                trnm_mvcc_fee::public_evaluation::PROFILE
                    | trnm_mvcc_fee::public_evaluation::QUORUM_PROFILE
            ) {
                format!(
                    "{label}-evaluation-storage{}",
                    if policy == trnm_mvcc_fee::public_evaluation::QUORUM_PROFILE {
                        trnm_mvcc_fee::public_evaluation::QUORUM_STORAGE_REVISION
                    } else {
                        trnm_mvcc_fee::public_evaluation::STORAGE_REVISION
                    }
                )
            } else {
                label
            };
            let label = if model_profile == "linear-expert-dev-v1" {
                label
            } else {
                format!("{label}-{model_profile}")
            };
            let label =
                if let Some(window_hash) = app.params["model_task_windows"]["sha256"].as_str() {
                    format!("{label}-task-windows-{window_hash}")
                } else {
                    label
                };
            app.params["chain_label"] = json!(label);
            app.network = hash(b"network", &[label.as_bytes()]);
            let wire: Value =
                serde_json::from_str(include_str!("../../../../config/pon/ledger-v1.json"))?;
            let work: Value =
                serde_json::from_str(include_str!("../../../../config/pon/work-profile-v1.json"))?;
            let model = &app.model_registry;
            app.parameters = hash(
                b"parameters",
                &[
                    &serde_json::to_vec(&app.params)?,
                    &serde_json::to_vec(&wire)?,
                    &serde_json::to_vec(&work)?,
                    &serde_json::to_vec(model)?,
                ],
            );
        }
        let (a, b) = maintenance();
        let task = pon_work::task_id(&a, &b).map_err(|_| Error::from("WORK_TASK"))?;
        let mut initial = State::new();
        let count = app.params["genesis_accounts"].as_u64().ok_or("CONFIG")?;
        let funding = app.params["genesis_funding_units_per_account"]
            .as_u64()
            .ok_or("CONFIG")?;
        initial.insert(
            "meta:issued".into(),
            json!(count.checked_mul(funding).ok_or("CONFIG")?),
        );
        initial.insert("model:current".into(), json!(hex::encode([0; 32])));
        if trnm_mvcc_fee::integer_factor_candidate_v2::enabled(&app) {
            initial.extend(
                trnm_mvcc_fee::integer_factor_candidate_v2::bootstrap_state(&app)
                    .map_err(Error::from)?,
            );
        }
        if matches!(
            task_profile,
            LIFECYCLE_TASK_PROFILE
                | ATOMIC_TASK_PROFILE
                | OVERLAP_TASK_PROFILE
                | CONTINUITY_TASK_PROFILE
                | GROWTH_TASK_PROFILE
        ) {
            let model: Vec<u8> = a.iter().flat_map(|v| v.to_le_bytes()).collect();
            let input: Vec<u8> = b.iter().flat_map(|v| v.to_le_bytes()).collect();
            initial.extend(qualified_task_lifecycle::bootstrap_state(&app, &model, &input)?.state);
        } else if task_profile == SIGNED_TASK_PROFILE {
            for index in 0..QUALIFIED_DEMANDS {
                let demand = app.qualified_demand_id(index)?;
                initial.insert(format!("work-demand-registry:{}",hex::encode(demand)),
                    json!({"purpose":Config::qualified_demand_purpose(index)? as u8,"scope":"public-development-fixture-not-real-user-demand"}));
            }
            let model: Vec<u8> = a.iter().flat_map(|v| v.to_le_bytes()).collect();
            let input: Vec<u8> = b.iter().flat_map(|v| v.to_le_bytes()).collect();
            let bootstrap = development_manifest(
                &app,
                0,
                TaskPurpose::Maintenance,
                &model,
                &input,
                0,
                1000,
                1,
            )?;
            let context = app.qualified_task_context(bootstrap.manifest.demand_id, 0)?;
            initial.insert(format!("work:{}",hex::encode(task)),json!({"schema":"qualified-work-registration-v1","manifest":hex::encode(bootstrap.encode().map_err(|_|Error::from("TASK_MANIFEST"))?),"admitted_height":0,"manifest_id":hex::encode(bootstrap.manifest.id().map_err(|_|Error::from("TASK_MANIFEST"))?)}));
            initial.insert(
                format!("work-source:{}", hex::encode(context.source)),
                json!(1),
            );
            initial.insert(
                format!("work-withdrawal:{}", hex::encode(context.source)),
                json!(hex::encode(context.withdrawal_head)),
            );
            initial.insert(
                format!("work-demand:{}", hex::encode(context.demand_id)),
                json!(hex::encode(
                    bootstrap
                        .manifest
                        .id()
                        .map_err(|_| Error::from("TASK_MANIFEST"))?
                )),
            );
        } else {
            initial.insert(format!("work:{}", hex::encode(task)), json!(true));
        }
        for i in 0..count {
            initial.insert(
                format!("account:{}", hex::encode(development_public(i)?)),
                json!({"balance":funding,"nonce":0}),
            );
        }
        if continuity_v1::enabled(&app) {
            initial.extend(continuity_v1::bootstrap_state(&app)?);
            continuity_v1::check_state(&initial, 0, &app)?;
        }
        let time = app.params["genesis_timestamp"].as_u64().ok_or("CONFIG")?;
        let genesis = hash(
            b"genesis",
            &[
                &app.network,
                &app.parameters,
                &pon_executor::root_for_config(&initial, &app)?,
                &time.to_le_bytes(),
            ],
        );
        Ok(Self {
            app,
            genesis,
            initial,
            operator_bootstrap: None,
            operator_material: None,
            checkpoint_tile_paths: None,
        })
    }
    pub fn network(&self) -> Hash {
        self.app.network
    }
    /// Complete actual-State computation selected by this frozen context. This
    /// is not a parent, admission or installation capability.
    pub fn state_root(&self, state: &State) -> Result<Hash> {
        Ok(pon_executor::root_for_config(state, &self.app)?)
    }

    pub fn parameters(&self) -> Hash {
        self.app.parameters
    }
    pub fn task_profile(&self) -> &str {
        self.app.task_profile()
    }
    /// Explicit perpetual genesis maintenance material. This fixture makes no
    /// source signature, real user demand, useful-output or work hardness claim.
    pub fn consensus_maintenance_material(&self) -> Result<BootstrapTaskMaterial> {
        ensure(continuity_v1::enabled(&self.app), "CONTINUITY_PROFILE")?;
        let (model, input) = continuity_v1::maintenance_material();
        let (a, b) = continuity_v1::maintenance_matrices();
        Ok((model, input, a, b))
    }
    pub fn qualified_task_context(&self, demand_id: Hash, height: u64) -> Result<AdmissionContext> {
        Ok(self.app.qualified_task_context(demand_id, height)?)
    }
    /// Exact explicitly classified genesis maintenance statement for the signed dev profile.
    pub fn bootstrap_task_statement(&self) -> Result<SignedQualifiedWorkTask> {
        ensure(self.task_profile() == SIGNED_TASK_PROFILE, "TASK_PROFILE")?;
        let (model, input, _, _) = self.bootstrap_task_material()?;
        self.development_task_manifest(0, TaskPurpose::Maintenance, &model, &input, 0, 1000, 1)
    }
    /// Public fixture artifacts, never a generic model or training-data claim.
    pub fn bootstrap_task_material(&self) -> Result<BootstrapTaskMaterial> {
        if let Some(material) = &self.operator_material {
            return Ok(material.clone());
        }
        ensure(
            matches!(
                self.task_profile(),
                SIGNED_TASK_PROFILE
                    | LIFECYCLE_TASK_PROFILE
                    | ATOMIC_TASK_PROFILE
                    | OVERLAP_TASK_PROFILE
                    | CONTINUITY_TASK_PROFILE
                    | GROWTH_TASK_PROFILE
            ),
            "TASK_PROFILE",
        )?;
        let (a, b) = maintenance();
        let model = a.iter().flat_map(|v| v.to_le_bytes()).collect();
        let input = b.iter().flat_map(|v| v.to_le_bytes()).collect();
        Ok((model, input, a, b))
    }
    pub fn bootstrap_lifecycle_task(
        &self,
    ) -> Result<qualified_task_lifecycle::BootstrapLifecycleTask> {
        if let Some(bootstrap) = &self.operator_bootstrap {
            return Ok(bootstrap.clone());
        }
        ensure(
            matches!(
                self.task_profile(),
                LIFECYCLE_TASK_PROFILE
                    | ATOMIC_TASK_PROFILE
                    | OVERLAP_TASK_PROFILE
                    | CONTINUITY_TASK_PROFILE
                    | GROWTH_TASK_PROFILE
            ),
            "TASK_PROFILE",
        )?;
        let (model, input, _, _) = self.bootstrap_task_material()?;
        Ok(qualified_task_lifecycle::bootstrap_state(
            &self.app, &model, &input,
        )?)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn development_task_manifest(
        &self,
        index: u64,
        purpose: TaskPurpose,
        model: &[u8],
        input: &[u8],
        not_before: u64,
        expires: u64,
        demand_nonce: u64,
    ) -> Result<SignedQualifiedWorkTask> {
        ensure(
            self.operator_actor_profile().is_none(),
            "ACTOR_EXPLICIT_SIGNATURE_REQUIRED",
        )?;
        development_manifest(
            &self.app,
            index,
            purpose,
            model,
            input,
            not_before,
            expires,
            demand_nonce,
        )
    }
    pub fn genesis(&self) -> Hash {
        self.genesis
    }
    pub fn genesis_time(&self) -> u64 {
        self.app.params["genesis_timestamp"]
            .as_u64()
            .expect("validated settings")
    }
    pub(crate) fn limit(&self, name: &str) -> Result<u64> {
        self.app.params[name]
            .as_u64()
            .ok_or_else(|| "CONFIG".into())
    }
    pub(crate) fn target(&self, name: &str) -> Result<Hash> {
        digest(self.app.params[name].as_str().ok_or("CONFIG")?)
    }
}
#[allow(clippy::too_many_arguments)]
fn development_manifest(
    app: &Config,
    index: u64,
    purpose: TaskPurpose,
    model: &[u8],
    input: &[u8],
    not_before: u64,
    expires: u64,
    demand_nonce: u64,
) -> Result<SignedQualifiedWorkTask> {
    ensure(
        purpose == Config::qualified_demand_purpose(index)?,
        "TASK_PURPOSE",
    )?;
    let context = app.qualified_task_context(app.qualified_demand_id(index)?, not_before)?;
    let (a, b) =
        derive_matrices(model, input).map_err(|e| Error::from(format!("TASK_MATERIAL:{e:?}")))?;
    let mut manifest = QualifiedWorkTask {
        purpose,
        cost_class: 1,
        numeric_encoding: 1,
        hardness_status: 0,
        reuse: 1,
        network: context.network,
        parameters: context.parameters,
        work_profile: QualifiedWorkTask::profile_id(),
        source: context.source,
        demand_id: context.demand_id,
        source_record: context.source_record,
        model: hash(b"artifact", &[model]),
        layer: [1; 32],
        input: hash(b"qualified-task-input-v1", &[input]),
        recipe: QualifiedWorkTask::recipe_id(),
        matrix_task: pon_work::task_id(&a, &b).map_err(|_| Error::from("WORK_TASK"))?,
        availability_manifest: context.availability_manifest,
        availability_root: context.availability_root,
        authorization_scope: context.authorization_scope,
        withdrawal_head: context.withdrawal_head,
        output_meter: [1; 32],
        rows: 64,
        inner: 64,
        columns: 64,
        demand_nonce,
        not_before,
        expires,
        available_until: expires.checked_add(100).ok_or("TASK_AVAILABILITY")?,
        logical_multiply_add_units: LOGICAL_MULTIPLY_ADD_UNITS,
        model_bytes: MATRIX_ARTIFACT_BYTES,
        input_bytes: MATRIX_ARTIFACT_BYTES,
        useful_output_limit: purpose.output_limit(),
    };
    manifest.layer = QualifiedWorkTask::layer_id(manifest.model);
    manifest.output_meter = manifest.derived_output_meter();
    let seed = hash(b"DEV-ONLY-KEY", &[&0_u64.to_le_bytes()]);
    let key = trnm_crypto_primitives::signing_key_from_hex(&hex::encode(seed))
        .map_err(|_| Error::from("DEV_KEY"))?;
    let message = SignedQualifiedWorkTask::signing_message(&manifest)
        .map_err(|_| Error::from("TASK_MANIFEST"))?;
    let signature = hex::decode(trnm_crypto_primitives::sign_hex(&key, &message))
        .map_err(|_| Error::from("DEV_KEY"))?
        .try_into()
        .map_err(|_| Error::from("DEV_KEY"))?;
    Ok(SignedQualifiedWorkTask {
        manifest,
        signature,
    })
}
pub fn maintenance() -> (Vec<u32>, Vec<u32>) {
    (
        (0..pon_work::CELLS).map(|i| (i % 31) as u32).collect(),
        (0..pon_work::CELLS)
            .map(|i| ((i * 7) % 37) as u32)
            .collect(),
    )
}
/// These identities are publicly known test identities, never production key custody.
pub fn development_public(i: u64) -> Result<Hash> {
    let seed = hash(b"DEV-ONLY-KEY", &[&i.to_le_bytes()]);
    let key = trnm_crypto_primitives::signing_key_from_hex(&hex::encode(seed))
        .map_err(|_| Error::from("DEV_KEY"))?;
    digest(&trnm_crypto_primitives::public_key_hex(&key))
}

#[cfg(all(test, target_os = "linux"))]
mod operator_continuous_test_support;

#[cfg(test)]
pub(crate) mod packet_encoding_tests {
    use super::*;

    /// Original grow-as-you-append codec, retained only as an independent control.
    pub(crate) fn reference(packet: &Packet) -> Result<Vec<u8>> {
        ensure(
            packet.transactions.len() <= 256 && packet.proof.len() == pon_work::PROOF_BYTES,
            "PACKET_LIMIT",
        )?;
        let mut out = packet.header.encode();
        out.extend((packet.transactions.len() as u16).to_le_bytes());
        for tx in &packet.transactions {
            ensure((159..=2048).contains(&tx.len()), "TRANSACTION_LIMIT")?;
            Envelope::decode(tx).map_err(|_| Error::from("TRANSACTION_CODEC"))?;
            out.extend((tx.len() as u16).to_le_bytes());
            out.extend(tx);
        }
        out.extend(&packet.proof);
        ensure(out.len() <= 1_048_576, "PACKET_LIMIT")?;
        Ok(out)
    }

    pub(crate) fn reference_length(packet: &Packet) -> Result<usize> {
        reference(packet).map(|bytes| bytes.len())
    }

    fn packet(count: usize, tag: u8) -> Packet {
        let settings = Settings::development(Some(1)).unwrap();
        let node_dir = tempfile::tempdir().unwrap();
        let node = Node::open(node_dir.path(), settings.clone(), 1).unwrap();
        let mut packet = node
            .make(
                settings.genesis(),
                Vec::new(),
                development_public(2).unwrap(),
                11,
                4096,
            )
            .unwrap();
        packet.transactions = (0..count)
            .map(|index| {
                Envelope {
                    network: settings.network(),
                    sender: development_public(0).unwrap(),
                    nonce: index as u64 + 1,
                    expiry: 1000,
                    fee_limit: 10_000,
                    tag,
                    payload: vec![
                        0;
                        if tag == 13 {
                            trnm_protocol::qualified_work_task::SIGNED_TASK_BYTES
                        } else {
                            40
                        }
                    ],
                    signature: [0; 64],
                }
                .encode()
                .unwrap()
            })
            .collect();
        packet
    }

    fn same(packet: &Packet) {
        match (packet.checked_wire_length(), reference_length(packet)) {
            (Ok(actual), Ok(expected)) => assert_eq!(actual, expected),
            (Err(actual), Err(expected)) => assert_eq!(actual.to_string(), expected.to_string()),
            (actual, expected) => panic!("length disagreement: {actual:?} {expected:?}"),
        }
        match (packet.encode(), reference(packet)) {
            (Ok(actual), Ok(expected)) => assert_eq!(actual, expected),
            (Err(actual), Err(expected)) => assert_eq!(actual.to_string(), expected.to_string()),
            (actual, expected) => panic!("codec disagreement: {actual:?} {expected:?}"),
        }
    }

    #[test]
    fn bounded_packet_reservation_preserves_bytes_and_first_error() {
        for (count, tag) in [(0, 1), (1, 1), (16, 1), (256, 1), (256, 13)] {
            let packet = packet(count, tag);
            same(&packet);
            let encoded = packet.encode().unwrap();
            assert_eq!(Packet::decode(&encoded).unwrap().encode().unwrap(), encoded);
        }
        let original = packet(2, 1);
        for transactions in [
            vec![Vec::new()],
            vec![vec![0; 159]],
            vec![vec![0; 2049]],
            vec![vec![0; 159], vec![0; 2049]],
            vec![vec![0; 2049], vec![0; 159]],
            vec![original.transactions[0].clone(); 257],
        ] {
            let mut changed = original.clone();
            changed.transactions = transactions;
            same(&changed);
            changed.proof.pop();
            assert_eq!(changed.encode().unwrap_err().to_string(), "PACKET_LIMIT");
            same(&changed);
        }
    }
}
