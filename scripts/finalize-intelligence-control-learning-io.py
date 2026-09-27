#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


replace_once(
    "codex-rs/hepta-operations/src/durable_store.rs",
    "    pub async fn backlog_metrics(&self) -> Result<OperationBacklogMetrics, DurableOperationError> {\n",
    dedent(r'''
        /// Exact source-side reference check used by owner startup to retire a
        /// payload sidecar left before intent publication. Absence proves only
        /// that this operations store does not reference the digest.
        pub async fn payload_is_referenced_v1(
            &self,
            payload_digest: Digest32,
        ) -> Result<bool, DurableOperationError> {
            if payload_digest.is_zero() {
                return Err(DurableOperationError::Invalid("payload digest"));
            }
            let count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM operation_ledger WHERE payload_digest = ?",
            )
            .bind(payload_digest.as_array().as_slice())
            .fetch_one(&self.pool)
            .await
            .map_err(sqlx_error)?;
            Ok(count > 0)
        }

        pub async fn backlog_metrics(&self) -> Result<OperationBacklogMetrics, DurableOperationError> {
    ''').lstrip(),
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "const MAX_RECONCILE_BATCH: u32 = 256;\n",
    "const MAX_RECONCILE_BATCH: u32 = 256;\nconst MAX_LEARNING_BLOCKING_WORKERS: usize = 4;\nconst LEARNING_BLOCKING_TIMEOUT: Duration = Duration::from_secs(30);\nconst MAX_ORPHAN_PAYLOAD_SCAN: usize = 4096;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "    Poisoned,\n}\n",
    "    Poisoned,\n    Busy,\n    TimedOut,\n    WorkerCrashed,\n}\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "            Self::Io(_) | Self::Agentd(_) => true,\n",
    "            Self::Io(_) | Self::Agentd(_) | Self::Busy | Self::TimedOut | Self::WorkerCrashed => true,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "    writer: Mutex<LedgerWriter>,\n    reconciliation_cursor: tokio::sync::Mutex<Option<UnsettledOperationCursorV1>>,\n",
    "    writer: Arc<Mutex<LedgerWriter>>,\n    blocking_slots: Arc<tokio::sync::Semaphore>,\n    blocking_timeout: Duration,\n    reconciliation_cursor: tokio::sync::Mutex<Option<UnsettledOperationCursorV1>>,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "        let operations = DurableOperationStore::open(&root.join(\"operations.sqlite\")).await?;\n        Ok(Self {\n",
    "        let operations = DurableOperationStore::open(&root.join(\"operations.sqlite\")).await?;\n        prune_orphan_payloads_v1(&payload_root, &operations).await?;\n        Ok(Self {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "            writer: Mutex::new(writer),\n            reconciliation_cursor: tokio::sync::Mutex::new(None),\n",
    "            writer: Arc::new(Mutex::new(writer)),\n            blocking_slots: Arc::new(tokio::sync::Semaphore::new(MAX_LEARNING_BLOCKING_WORKERS)),\n            blocking_timeout: LEARNING_BLOCKING_TIMEOUT,\n            reconciliation_cursor: tokio::sync::Mutex::new(None),\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "    pub async fn enqueue_decision(\n",
    dedent(r'''
        async fn run_blocking_v1<T, F>(
            &self,
            work: F,
        ) -> Result<T, AgentdIntelligenceLearningErrorV1>
        where
            T: Send + 'static,
            F: FnOnce() -> Result<T, AgentdIntelligenceLearningErrorV1> + Send + 'static,
        {
            let permit = Arc::clone(&self.blocking_slots)
                .try_acquire_owned()
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Busy)?;
            let task = tokio::task::spawn_blocking(move || {
                let _permit = permit;
                work()
            });
            match tokio::time::timeout(self.blocking_timeout, task).await {
                Ok(Ok(result)) => result,
                Ok(Err(_)) => Err(AgentdIntelligenceLearningErrorV1::WorkerCrashed),
                Err(_) => Err(AgentdIntelligenceLearningErrorV1::TimedOut),
            }
        }

        pub async fn enqueue_decision(
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    dedent(r'''
            let payload = {
                let writer = self.writer.lock().map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                LearningPayloadV1::Decision(decision_payload(&writer, prepared, request)?)
            };
    ''').lstrip(),
    dedent(r'''
            let writer = Arc::clone(&self.writer);
            let prepared = prepared.clone();
            let payload = self
                .run_blocking_v1(move || {
                    let writer = writer
                        .lock()
                        .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                    Ok(LearningPayloadV1::Decision(decision_payload(
                        &writer,
                        &prepared,
                        request,
                    )?))
                })
                .await?;
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    dedent(r'''
            let payload = {
                let writer = self.writer.lock().map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                LearningPayloadV1::Outcome(outcome_payload(&writer, prepared, request)?)
            };
    ''').lstrip(),
    dedent(r'''
            let writer = Arc::clone(&self.writer);
            let prepared_for_payload = prepared.clone();
            let payload = self
                .run_blocking_v1(move || {
                    let writer = writer
                        .lock()
                        .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                    Ok(LearningPayloadV1::Outcome(outcome_payload(
                        &writer,
                        &prepared_for_payload,
                        request,
                    )?))
                })
                .await?;
    ''').lstrip(),
)
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "        persist_payload(&self.payload_root, payload_digest, &encoded)?;\n",
    "        let payload_root = self.payload_root.clone();\n        self.run_blocking_v1(move || persist_payload(&payload_root, payload_digest, &encoded))\n            .await?;\n",
)

# Replace dispatch with bounded grant, sidecar and writer work. The operation
# owner remains authoritative for the dispatching/unknown transitions.
start = read("codex-rs/hepta-agentd/src/intelligence_learning.rs")
old_start = start.index("    pub async fn dispatch_next(\n")
old_end = start.index("\n    pub async fn reconcile_unsettled(\n", old_start)
new_dispatch = dedent(r'''
    pub async fn dispatch_next(
        &self,
    ) -> Result<Option<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        let Some(claim) = self
            .operations
            .claim_next(
                &self.destination,
                &self.worker_id,
                self.generation,
                CLAIM_LEASE,
            )
            .await?
        else {
            return Ok(None);
        };
        let payload = self.load_payload(claim.intent.payload_digest).await?;
        validate_claim_payload(&claim.intent, &payload)?;
        let binding = claim.intent.final_use_binding();
        let grants = Arc::clone(&self.grants);
        let grant = self
            .run_blocking_v1(move || {
                grants
                    .signed_grant(&binding)
                    .map_err(AgentdIntelligenceLearningErrorV1::Agentd)
            })
            .await;
        let signed = match grant {
            Ok(value) => value,
            Err(error) => {
                self.operations
                    .defer_pre_dispatch_claim_v1(&claim, GRANT_RETRY_DELAY)
                    .await?;
                return Err(error);
            }
        };
        let authorized = self
            .operations
            .authorize_dispatch(&self.authority, &signed, &claim)
            .await?;
        let operations = self.operations.clone();
        let writer = Arc::clone(&self.writer);
        let runtime = tokio::runtime::Handle::current();
        let observation = self
            .run_blocking_v1(move || {
                runtime
                    .block_on(operations.execute_authorized(authorized, |_| {
                        let applied = match writer.lock() {
                            Ok(mut writer) => classify_apply(apply_payload(&mut writer, &payload)),
                            Err(_) => unknown(b"writer-poisoned"),
                        };
                        match &applied {
                            ApplyObservation::Acknowledged(receipt) => DispatchEffect::Dispatched {
                                value: applied.clone(),
                                dispatch_digest: receipt.chain_digest,
                                acknowledgement_digest: Some(receipt.chain_digest),
                            },
                            ApplyObservation::Rejected(digest)
                            | ApplyObservation::Revoked(digest)
                            | ApplyObservation::Indeterminate(digest) => {
                                DispatchEffect::Indeterminate {
                                    value: applied.clone(),
                                    reason_digest: *digest,
                                }
                            }
                        }
                    }))
                    .map_err(AgentdIntelligenceLearningErrorV1::Operation)
            })
            .await?;
        Ok(Some(
            self.settle_observation(
                &claim.intent.scope_id,
                &claim.intent.operation_id,
                observation,
            )
            .await?,
        ))
    }
''').lstrip()
write(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    start[:old_start] + new_dispatch + start[old_end:],
)

# Replace reconciliation so no std::sync mutex, grant provider or ledger file
# operation can block a Tokio runtime worker.
text = read("codex-rs/hepta-agentd/src/intelligence_learning.rs")
old_start = text.index("    pub async fn reconcile_unsettled(\n")
old_end = text.index("\n    #[must_use]\n    pub const fn owner_generation", old_start)
new_reconcile = dedent(r'''
    pub async fn reconcile_unsettled(
        &self,
        limit: u32,
    ) -> Result<Vec<AgentdIntelligenceLearningReceiptV1>, AgentdIntelligenceLearningErrorV1> {
        if limit == 0 || limit > MAX_RECONCILE_BATCH {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "reconciliation limit",
            ));
        }
        let mut cursor = self.reconciliation_cursor.lock().await;
        let page = self
            .operations
            .unsettled_operation_page_v1(&self.destination, cursor.as_ref(), limit)
            .await?;
        *cursor = page.next_cursor;
        drop(cursor);

        let mut receipts = Vec::with_capacity(page.records.len());
        for record in page.records {
            let record = if record.intent.owner_generation == self.generation {
                record
            } else {
                self.operations
                    .adopt_unsettled_generation(
                        &record.intent.scope_id,
                        &record.intent.operation_id,
                        self.generation,
                    )
                    .await?
            };
            let payload = self.load_payload(record.intent.payload_digest).await?;
            validate_claim_payload(&record.intent, &payload)?;

            let writer = Arc::clone(&self.writer);
            let observed_payload = payload.clone();
            let observed = self
                .run_blocking_v1(move || {
                    let writer = writer
                        .lock()
                        .map_err(|_| AgentdIntelligenceLearningErrorV1::Poisoned)?;
                    observe_applied_payload(&writer, &observed_payload).map_err(Into::into)
                })
                .await;
            let observation = match observed {
                Ok(Some(receipt)) => ApplyObservation::Acknowledged(receipt),
                Ok(None) => {
                    let binding = record.intent.final_use_binding();
                    let grants = Arc::clone(&self.grants);
                    let grant_binding = binding.clone();
                    match self
                        .run_blocking_v1(move || {
                            grants
                                .signed_grant(&grant_binding)
                                .map_err(AgentdIntelligenceLearningErrorV1::Agentd)
                        })
                        .await
                    {
                        Err(error) => unknown(format!("grant-unavailable:{error}").as_bytes()),
                        Ok(signed) => {
                            let authority = self.authority.clone();
                            let writer = Arc::clone(&self.writer);
                            let applied_payload = payload.clone();
                            match self
                                .run_blocking_v1(move || {
                                    let token = match claim_final_use(&authority, &signed, &binding) {
                                        Ok(value) => value,
                                        Err(error) => return Ok(classify_authority_error(error)),
                                    };
                                    match dispatch_final_use(
                                        &authority,
                                        token,
                                        &binding,
                                        || match writer.lock() {
                                            Ok(mut writer) => {
                                                apply_payload(&mut writer, &applied_payload)
                                            }
                                            Err(_) => Err(ProductionLedgerError::Binding(
                                                "writer poisoned",
                                            )),
                                        },
                                    ) {
                                        Ok(result) => Ok(classify_apply(result)),
                                        Err(error) => Ok(classify_authority_error(error)),
                                    }
                                })
                                .await
                            {
                                Ok(value) => value,
                                Err(error) => {
                                    unknown(format!("blocking-apply:{error}").as_bytes())
                                }
                            }
                        }
                    }
                }
                Err(error) => unknown(format!("observe:{error}").as_bytes()),
            };
            receipts.push(
                self.settle_observation(
                    &record.intent.scope_id,
                    &record.intent.operation_id,
                    observation,
                )
                .await?,
            );
        }
        Ok(receipts)
    }
''').lstrip()
write(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    text[:old_start] + new_reconcile + text[old_end:],
)

replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "    fn load_payload(&self, digest: Digest32) -> Result<PersistedLearningEnvelopeV1, AgentdIntelligenceLearningErrorV1> {\n        let bytes = read_payload_bytes(&payload_path(&self.payload_root, digest))?;\n        if Digest32::of_bytes(&bytes) != digest {\n            return Err(AgentdIntelligenceLearningErrorV1::Invalid(\"learning payload digest\"));\n        }\n        let value: PersistedLearningEnvelopeV1 = serde_json::from_slice(&bytes)\n            .map_err(|error| AgentdIntelligenceLearningErrorV1::Json(error.to_string()))?;\n        if value.schema_version != LEARNING_PAYLOAD_SCHEMA_VERSION {\n            return Err(AgentdIntelligenceLearningErrorV1::Invalid(\"learning payload schema\"));\n        }\n        Ok(value)\n    }\n",
    dedent(r'''
        async fn load_payload(
            &self,
            digest: Digest32,
        ) -> Result<PersistedLearningEnvelopeV1, AgentdIntelligenceLearningErrorV1> {
            let path = payload_path(&self.payload_root, digest);
            self.run_blocking_v1(move || {
                let bytes = read_payload_bytes(&path)?;
                if Digest32::of_bytes(&bytes) != digest {
                    return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                        "learning payload digest",
                    ));
                }
                let value: PersistedLearningEnvelopeV1 = serde_json::from_slice(&bytes)
                    .map_err(|error| AgentdIntelligenceLearningErrorV1::Json(error.to_string()))?;
                if value.schema_version != LEARNING_PAYLOAD_SCHEMA_VERSION {
                    return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                        "learning payload schema",
                    ));
                }
                Ok(value)
            })
            .await
        }
    ''').lstrip(),
)

# Startup-only bounded orphan cleanup. Payload publication precedes intent; after
# predecessor process death, an unreferenced sidecar has no authority or replay
# identity and is retired before the new runtime accepts work.
replace_once(
    "codex-rs/hepta-agentd/src/intelligence_learning.rs",
    "fn payload_path(root: &Path, digest: Digest32) -> PathBuf {\n",
    dedent(r'''
    async fn prune_orphan_payloads_v1(
        root: &Path,
        operations: &DurableOperationStore,
    ) -> Result<(), AgentdIntelligenceLearningErrorV1> {
        let mut entries = std::fs::read_dir(root)
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
        entries.sort_by_key(std::fs::DirEntry::file_name);
        if entries.len() > MAX_ORPHAN_PAYLOAD_SCAN {
            return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                "learning payload retention bound",
            ));
        }
        let mut removed = false;
        for entry in entries {
            let path = entry.path();
            let metadata = std::fs::symlink_metadata(&path)
                .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                    "learning payload retention entry",
                ));
            }
            let name = entry.file_name();
            let name = name.to_string_lossy();
            if name.contains(".tmp-") {
                std::fs::remove_file(&path)
                    .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
                removed = true;
                continue;
            }
            let Some(raw_digest) = name.strip_suffix(".json") else {
                return Err(AgentdIntelligenceLearningErrorV1::Invalid(
                    "learning payload retention name",
                ));
            };
            let digest = Digest32::from_str(raw_digest)
                .map_err(|_| AgentdIntelligenceLearningErrorV1::Invalid("payload file digest"))?;
            if !operations.payload_is_referenced_v1(digest).await? {
                std::fs::remove_file(&path)
                    .map_err(|error| AgentdIntelligenceLearningErrorV1::Io(error.to_string()))?;
                removed = true;
            }
        }
        if removed {
            sync_directory(root)?;
        }
        Ok(())
    }

    fn payload_path(root: &Path, digest: Digest32) -> PathBuf {
    ''').lstrip(),
)
