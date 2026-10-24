//! Opt-in decoder owner composed with Agentd's existing recovered writer host.
//! Jobs use the existing control socket; they never extend its two-second I/O
//! deadline or accept arbitrary prompts, paths, source proofs or model pins.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_agent_protocol::MemoryCellReadIngress;
use codex_hepta_agent_protocol::MemoryCellReadSnapshot;
use codex_hepta_agent_protocol::MemoryCellReadState;
use codex_hepta_agent_protocol::MemoryCellRole;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::MemoryCellAdmissionV1;
use codex_hepta_memory::MemoryCellKeyV1;
use codex_hepta_memory::MemoryCellQueryV1;
use codex_hepta_memory::MemoryCellRoleV1;
use codex_hepta_memory::MemoryCellSourceClaimV1;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::sync::Semaphore;

#[cfg(feature = "qualification-cognitive-write")]
use crate::AgentdProductionWriterHost;
use crate::native_memory_model::NativeMemoryModelPort;
use crate::native_memory_types::NativeMemoryError;
use crate::native_memory_types::NativeMemoryModelConfigV1;

pub struct AgentdNativeMemoryCell {
    pub(crate) writer: Arc<ProductionDurableWriter>,
    access: CognitiveAccess,
    key: MemoryCellKeyV1,
    claim: MemoryCellSourceClaimV1,
    config: NativeMemoryModelConfigV1,
    jobs: Mutex<BTreeMap<String, (MemoryCellQueryV1, MemoryCellReadSnapshot)>>,
    capacity: Arc<Semaphore>,
    dispatches: Arc<AtomicU64>,
    pub(crate) cancellation: tokio_util::sync::CancellationToken,
}

#[cfg(feature = "qualification-cognitive-write")]
impl AgentdProductionWriterHost {
    /// Compose one explicitly registered source/adapter with this exact
    /// recovered owner. Normal daemon startup does not invent this profile.
    pub async fn native_memory_cell(
        &self,
        access: CognitiveAccess,
        key: MemoryCellKeyV1,
        claim: MemoryCellSourceClaimV1,
        config: NativeMemoryModelConfigV1,
    ) -> Result<Arc<AgentdNativeMemoryCell>, NativeMemoryError> {
        use std::io::Read;
        config.validate().map_err(NativeMemoryError::Rejected)?;
        let writer = self.writer();
        if writer.generation() != config.generation {
            return Err(NativeMemoryError::Rejected(
                "native model generation differs from writer".to_string(),
            ));
        }
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?
            .as_millis() as u64;
        let query = MemoryCellQueryV1 {
            request_id: StableId::new("memory-cell-install")
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?,
            key: key.clone(),
            deadline_unix_ms: now + 300_000,
        };
        let binding = writer
            .authorize_memory_cell(&access, &query, &claim)
            .await?;
        let path = config.checkpoint.join("lineage.json");
        let mut bytes = Vec::new();
        std::fs::File::open(path)
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?
            .take(256 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        if bytes.len() > 256 * 1024
            || Digest32::of_bytes(&bytes).to_string() != config.pins.manifest_sha256
        {
            return Err(NativeMemoryError::Rejected(
                "retained manifest changed".to_string(),
            ));
        }
        let manifest: serde_json::Value = serde_json::from_slice(&bytes)
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        if manifest["roots"] != serde_json::json!([binding.source_content_sha256.as_str()])
            || manifest["scope"] != config.scope
        {
            return Err(NativeMemoryError::Rejected(
                "single source ancestry or scope mismatch".to_string(),
            ));
        }
        Ok(Arc::new(AgentdNativeMemoryCell {
            writer,
            access,
            key,
            claim,
            config,
            jobs: Mutex::new(BTreeMap::new()),
            capacity: Arc::new(Semaphore::new(1)),
            dispatches: Arc::new(AtomicU64::new(0)),
            cancellation: tokio_util::sync::CancellationToken::new(),
        }))
    }
}

impl AgentdNativeMemoryCell {
    /// Per-process backend dispatch attempts, including failed invocations.
    /// It is a cost counter, not proof that every attempt completed inference.
    pub fn backend_dispatch_attempts(&self) -> u64 {
        self.dispatches.load(Ordering::SeqCst)
    }

    pub(crate) async fn start(
        self: &Arc<Self>,
        ingress: MemoryCellReadIngress,
    ) -> Result<MemoryCellReadSnapshot, NativeMemoryError> {
        if self.cancellation.is_cancelled() {
            return Err(NativeMemoryError::Rejected(
                "native owner is closed".to_string(),
            ));
        }
        let query = MemoryCellQueryV1 {
            request_id: StableId::new(ingress.invocation_id.clone())
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?,
            key: MemoryCellKeyV1 {
                role: match ingress.role {
                    MemoryCellRole::Semantic => MemoryCellRoleV1::Semantic,
                    MemoryCellRole::Procedural => MemoryCellRoleV1::Procedural,
                },
                entity: ingress.entity,
                relation: ingress.relation,
            },
            deadline_unix_ms: ingress.deadline_unix_ms,
        };
        if query.key != self.key {
            return Err(NativeMemoryError::Rejected(
                "unknown typed source key".to_string(),
            ));
        }
        let permit = self
            .capacity
            .clone()
            .try_acquire_owned()
            .map_err(|_| NativeMemoryError::Rejected("native reader busy".to_string()))?;
        if self
            .jobs
            .lock()
            .map_err(|_| NativeMemoryError::Rejected("job owner poisoned".to_string()))?
            .len()
            >= 64
        {
            return Err(NativeMemoryError::Rejected(
                "bounded job history full".to_string(),
            ));
        }
        let admission = Arc::new(
            self.writer
                .admit_memory_cell(&self.access, &query, &self.claim)
                .await?,
        );
        let snapshot = MemoryCellReadSnapshot {
            invocation_id: ingress.invocation_id.clone(),
            state: MemoryCellReadState::Running,
            text: None,
            execution_json: None,
            execution_sha256: None,
            source_commit_event_id: None,
            refusal: None,
        };
        self.jobs
            .lock()
            .map_err(|_| NativeMemoryError::Rejected("job owner poisoned".to_string()))?
            .insert(ingress.invocation_id.clone(), (query, snapshot.clone()));
        let owner = Arc::clone(self);
        tokio::spawn(async move {
            let result = owner.execute(admission).await;
            if let Ok(mut jobs) = owner.jobs.lock() {
                if let Some((_, record)) = jobs.get_mut(&ingress.invocation_id) {
                    match result {
                        Ok(completed) => *record = completed,
                        Err(error) => {
                            record.state = MemoryCellReadState::Rejected;
                            record.refusal = Some(error.to_string().chars().take(2048).collect());
                        }
                    }
                }
            }
            drop(permit);
        });
        Ok(snapshot)
    }

    async fn execute(
        &self,
        admission: Arc<MemoryCellAdmissionV1>,
    ) -> Result<MemoryCellReadSnapshot, NativeMemoryError> {
        let mut model = NativeMemoryModelPort::new(
            Arc::clone(&self.writer),
            Arc::clone(&admission),
            self.config.clone(),
            tokio::runtime::Handle::current(),
            Arc::clone(&self.dispatches),
            self.cancellation.clone(),
        )?;
        let execution = tokio::task::spawn_blocking(move || -> Result<_, NativeMemoryError> {
            let request = model.request();
            // Call the actual pre-existing trait boundary, not a fixture port.
            let output = NeuronModelPort::execute(&mut model, &request).map_err(|error| {
                NativeMemoryError::Rejected(
                    model
                        .failure()
                        .unwrap_or("native model rejected")
                        .to_string()
                        + &format!(": {error}"),
                )
            })?;
            output
                .runtime_receipt
                .semantic_digest()
                .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
            model.take_execution()
        })
        .await
        .map_err(|e| NativeMemoryError::Rejected(format!("model task did not complete: {e}")))??;
        let json = serde_json::to_string(&execution)
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        if self.cancellation.is_cancelled() {
            return Err(NativeMemoryError::Rejected(
                "native owner closed before publication".to_string(),
            ));
        }
        let digest = Digest32::of_bytes(json.as_bytes());
        let committed = self.writer.finish_memory_cell(&admission, digest).await?;
        Ok(MemoryCellReadSnapshot {
            invocation_id: admission.query().request_id.as_str().to_string(),
            state: MemoryCellReadState::Succeeded,
            text: Some(execution.text),
            execution_json: Some(json),
            execution_sha256: Some(digest.to_string()),
            source_commit_event_id: Some(committed.event_id),
            refusal: None,
        })
    }

    pub(crate) async fn status(
        &self,
        invocation_id: String,
    ) -> Result<MemoryCellReadSnapshot, NativeMemoryError> {
        if self.cancellation.is_cancelled() {
            return Err(NativeMemoryError::Rejected(
                "native owner is closed".to_string(),
            ));
        }
        StableId::new(invocation_id.clone())
            .map_err(|e| NativeMemoryError::Rejected(e.to_string()))?;
        let found = self
            .jobs
            .lock()
            .map_err(|_| NativeMemoryError::Rejected("job owner poisoned".to_string()))?
            .get(&invocation_id)
            .cloned();
        let Some((query, snapshot)) = found else {
            // No implicit re-execution after process loss; the owner journal
            // independently rejects any spent nonce on a subsequent start.
            return Ok(MemoryCellReadSnapshot {
                invocation_id,
                state: MemoryCellReadState::Indeterminate,
                text: None,
                execution_json: None,
                execution_sha256: None,
                source_commit_event_id: None,
                refusal: Some(
                    "no retained job in this host process; no automatic replay".to_string(),
                ),
            });
        };
        if snapshot.state == MemoryCellReadState::Succeeded {
            self.writer
                .authorize_memory_cell(&self.access, &query, &self.claim)
                .await?;
        }
        Ok(snapshot)
    }
}
