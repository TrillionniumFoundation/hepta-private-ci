#!/usr/bin/env python3
"""Add durable snapshot lineage and non-resurrectable closed-run tombstones."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "codex-rs/hepta-agentd/src/lane_b_runtime.rs"


def replace_once(text: str, old: str, new: str, marker: str) -> str:
    if old in text:
        if text.count(old) != 1:
            raise RuntimeError(f"{marker}: expected one source block, found {text.count(old)}")
        return text.replace(old, new)
    if marker in text:
        return text
    raise RuntimeError(f"{marker}: legacy block and migrated marker are absent")


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "const DURABLE_RUN_STORE_SCHEMA_VERSION: u32 = 1;\n",
        "const DURABLE_RUN_STORE_SCHEMA_VERSION: u32 = 2;\n",
        "DURABLE_RUN_STORE_SCHEMA_VERSION: u32 = 2",
    )

    old_store = '''#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunStoreV1 {
    schema_version: u32,
    store_revision: u64,
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    accepting_runs: bool,
    max_active_runs: usize,
}
'''
    new_store = '''#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunTombstoneV1 {
    snapshot: RunSnapshot,
    receipt: RunReceipt,
    record_sha256: String,
    removed_at_store_revision: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DurableRunStoreV1 {
    schema_version: u32,
    store_revision: u64,
    previous_store_sha256: Option<String>,
    composition: RuntimeComposition,
    runs: BTreeMap<String, RunRecord>,
    tombstones: BTreeMap<String, DurableRunTombstoneV1>,
    accepting_runs: bool,
    max_active_runs: usize,
}
'''
    text = replace_once(text, old_store, new_store, "struct DurableRunTombstoneV1")

    old_coordinator = '''    durable_path: Option<PathBuf>,
    durable_store_revision: u64,
}
'''
    new_coordinator = '''    durable_path: Option<PathBuf>,
    durable_store_revision: u64,
    committed_store_sha256: Option<String>,
    tombstones: BTreeMap<String, DurableRunTombstoneV1>,
}
'''
    text = replace_once(
        text,
        old_coordinator,
        new_coordinator,
        "committed_store_sha256: Option<String>",
    )

    old_compose = '''            durable_path: None,
            durable_store_revision: 0,
        })
'''
    new_compose = '''            durable_path: None,
            durable_store_revision: 0,
            committed_store_sha256: None,
            tombstones: BTreeMap::new(),
        })
'''
    text = replace_once(text, old_compose, new_compose, "committed_store_sha256: None")

    old_open = '''        if let Some(store) = load_durable_run_store(&durable_path)? {
            validate_durable_run_store(&store, &composition)?;
            return Ok(Self {
                composition,
                runs: store.runs,
                accepting_runs: store.accepting_runs,
                max_active_runs: store.max_active_runs,
                durable_path: Some(durable_path),
                durable_store_revision: store.store_revision,
            });
        }
'''
    new_open = '''        if let Some(store) = load_durable_run_store(&durable_path)? {
            validate_durable_run_store(&store, &composition)?;
            let committed_store_sha256 = durable_run_store_sha256(&store)?;
            return Ok(Self {
                composition,
                runs: store.runs,
                accepting_runs: store.accepting_runs,
                max_active_runs: store.max_active_runs,
                durable_path: Some(durable_path),
                durable_store_revision: store.store_revision,
                committed_store_sha256: Some(committed_store_sha256),
                tombstones: store.tombstones,
            });
        }
'''
    text = replace_once(text, old_open, new_open, "durable_run_store_sha256(&store)")

    old_persist_prefix = '''        let on_disk = load_durable_run_store(&path)?;
        let observed_revision = on_disk.as_ref().map_or(0, |store| store.store_revision);
        if observed_revision != self.durable_store_revision {
            return Err(AgentRunError::Persistence(format!(
                "stale durable run writer: expected revision {}, observed {observed_revision}",
                self.durable_store_revision
            )));
        }
'''
    new_persist_prefix = '''        let on_disk = load_durable_run_store(&path)?;
        let observed_revision = on_disk.as_ref().map_or(0, |store| store.store_revision);
        let observed_store_sha256 = on_disk
            .as_ref()
            .map(durable_run_store_sha256)
            .transpose()?;
        if observed_revision != self.durable_store_revision
            || observed_store_sha256 != self.committed_store_sha256
        {
            return Err(AgentRunError::Persistence(format!(
                "stale durable run writer: expected revision {} and digest {:?}, observed revision {observed_revision} and digest {observed_store_sha256:?}",
                self.durable_store_revision,
                self.committed_store_sha256,
            )));
        }
'''
    text = replace_once(
        text,
        old_persist_prefix,
        new_persist_prefix,
        "observed_store_sha256 != self.committed_store_sha256",
    )

    old_store_build = '''        let store = DurableRunStoreV1 {
            schema_version: DURABLE_RUN_STORE_SCHEMA_VERSION,
            store_revision: next_revision,
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            accepting_runs: self.accepting_runs,
            max_active_runs: self.max_active_runs,
        };
        validate_durable_run_store(&store, &self.composition)?;
        atomic_replace_durable_run_store(&path, &store)?;
        self.durable_store_revision = next_revision;
'''
    new_store_build = '''        let store = DurableRunStoreV1 {
            schema_version: DURABLE_RUN_STORE_SCHEMA_VERSION,
            store_revision: next_revision,
            previous_store_sha256: observed_store_sha256,
            composition: self.composition.clone(),
            runs: self.runs.clone(),
            tombstones: self.tombstones.clone(),
            accepting_runs: self.accepting_runs,
            max_active_runs: self.max_active_runs,
        };
        validate_durable_run_store(&store, &self.composition)?;
        let committed_store_sha256 = durable_run_store_sha256(&store)?;
        atomic_replace_durable_run_store(&path, &store)?;
        self.durable_store_revision = next_revision;
        self.committed_store_sha256 = Some(committed_store_sha256);
'''
    text = replace_once(
        text,
        old_store_build,
        new_store_build,
        "self.committed_store_sha256 = Some(committed_store_sha256)",
    )

    old_start = '''        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
'''
    new_start = '''        if self.tombstones.contains_key(&snapshot.run_id) {
            return Err(AgentRunError::Conflict);
        }
        if let Some(current) = self.runs.get(&snapshot.run_id) {
            if current.snapshot == snapshot {
                return Ok(receipt(current, /*idempotent*/ true));
            }
            return Err(AgentRunError::Conflict);
        }
'''
    text = replace_once(text, old_start, new_start, "self.tombstones.contains_key")

    old_capacity = '''        if self.active_run_count() >= self.max_active_runs || self.runs.len() >= MAX_RETAINED_RUNS {
            return Err(AgentRunError::CapacityExceeded);
        }
'''
    new_capacity = '''        if self.active_run_count() >= self.max_active_runs
            || self.runs.len().saturating_add(self.tombstones.len()) >= MAX_RETAINED_RUNS
        {
            return Err(AgentRunError::CapacityExceeded);
        }
'''
    text = replace_once(
        text,
        old_capacity,
        new_capacity,
        "self.runs.len().saturating_add(self.tombstones.len())",
    )

    old_remove = '''    pub fn remove_closed_run(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        let record = self.runs.get(run_id).ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        if !record.phase.closed() {
            return Err(AgentRunError::InvalidTransition);
        }
        let receipt = receipt(record, /*idempotent*/ false);
        self.runs.remove(run_id);
        Ok(receipt)
    }

    pub fn run(&self, run_id: &str) -> Option<RunReceipt> {
        self.runs
            .get(run_id)
            .map(|record| receipt(record, /*idempotent*/ false))
    }
'''
    new_remove = '''    pub fn remove_closed_run(
        &mut self,
        run_id: &str,
        expected_revision: u64,
    ) -> Result<RunReceipt, AgentRunError> {
        validate_identity(run_id, "run")?;
        if let Some(tombstone) = self.tombstones.get(run_id) {
            if tombstone.receipt.revision != expected_revision {
                return Err(AgentRunError::StaleRevision);
            }
            let mut receipt = tombstone.receipt.clone();
            receipt.idempotent = true;
            return Ok(receipt);
        }
        let record = self.runs.get(run_id).ok_or(AgentRunError::RunNotFound)?;
        require_revision(record, expected_revision)?;
        if !record.phase.closed() {
            return Err(AgentRunError::InvalidTransition);
        }
        let receipt = receipt(record, /*idempotent*/ false);
        let snapshot = record.snapshot.clone();
        let record_sha256 = durable_run_tombstone_sha256(&snapshot, &receipt)?;
        let removed_at_store_revision = self
            .durable_store_revision
            .checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        self.tombstones.insert(
            run_id.to_string(),
            DurableRunTombstoneV1 {
                snapshot,
                receipt: receipt.clone(),
                record_sha256,
                removed_at_store_revision,
            },
        );
        self.runs.remove(run_id);
        Ok(receipt)
    }

    pub fn run(&self, run_id: &str) -> Option<RunReceipt> {
        self.runs
            .get(run_id)
            .map(|record| receipt(record, /*idempotent*/ false))
            .or_else(|| {
                self.tombstones.get(run_id).map(|tombstone| {
                    let mut receipt = tombstone.receipt.clone();
                    receipt.idempotent = false;
                    receipt
                })
            })
    }
'''
    text = replace_once(text, old_remove, new_remove, "durable_run_tombstone_sha256")

    validate_anchor = '''    if store.schema_version != DURABLE_RUN_STORE_SCHEMA_VERSION
        || store.store_revision == 0
        || &store.composition != expected_composition
        || store.max_active_runs != expected_composition.max_active_runs
        || !(1..=MAX_SUPPORTED_ACTIVE_RUNS).contains(&store.max_active_runs)
        || store.runs.len() > MAX_RETAINED_RUNS
    {
'''
    validate_replacement = '''    if store.schema_version != DURABLE_RUN_STORE_SCHEMA_VERSION
        || store.store_revision == 0
        || &store.composition != expected_composition
        || store.max_active_runs != expected_composition.max_active_runs
        || !(1..=MAX_SUPPORTED_ACTIVE_RUNS).contains(&store.max_active_runs)
        || store.runs.len().saturating_add(store.tombstones.len()) > MAX_RETAINED_RUNS
    {
'''
    text = replace_once(
        text,
        validate_anchor,
        validate_replacement,
        "store.runs.len().saturating_add(store.tombstones.len())",
    )

    active_anchor = '''    let mut active = 0usize;
    for (run_id, record) in &store.runs {
'''
    active_replacement = '''    match (store.store_revision, store.previous_store_sha256.as_deref()) {
        (1, None) => {}
        (1, Some(_)) | (_, None) => {
            return Err(AgentRunError::Persistence(
                "durable run store predecessor binding is invalid".to_string(),
            ));
        }
        (_, Some(digest)) => validate_digest(digest, "durable previous store")?,
    }
    let mut active = 0usize;
    for (run_id, record) in &store.runs {
'''
    text = replace_once(
        text,
        active_anchor,
        active_replacement,
        "durable run store predecessor binding is invalid",
    )

    before_active_bound = '''    if active > store.max_active_runs {
'''
    tombstone_validation = '''    for (run_id, tombstone) in &store.tombstones {
        if store.runs.contains_key(run_id)
            || run_id != &tombstone.snapshot.run_id
            || run_id != &tombstone.receipt.run_id
            || tombstone.receipt.revision == 0
            || !tombstone.receipt.phase.closed()
            || tombstone.receipt.terminal_observed
                != tombstone.receipt.phase.terminal_observed()
            || tombstone.removed_at_store_revision == 0
            || tombstone.removed_at_store_revision > store.store_revision
        {
            return Err(AgentRunError::Persistence(
                "durable run tombstone identity or phase is invalid".to_string(),
            ));
        }
        validate_snapshot_fields(&tombstone.snapshot)?;
        validate_digest(&tombstone.record_sha256, "durable run tombstone")?;
        if tombstone.record_sha256
            != durable_run_tombstone_sha256(&tombstone.snapshot, &tombstone.receipt)?
        {
            return Err(AgentRunError::Persistence(
                "durable run tombstone digest changed".to_string(),
            ));
        }
        for (value, field) in [
            (
                tombstone.receipt.context_digest.as_deref(),
                "tombstone context",
            ),
            (
                tombstone.receipt.compilation_receipt_digest.as_deref(),
                "tombstone compilation receipt",
            ),
            (
                tombstone.receipt.dispatch_binding_digest.as_deref(),
                "tombstone dispatch binding",
            ),
            (
                tombstone
                    .receipt
                    .pre_effect_abort_commitment_digest
                    .as_deref(),
                "tombstone abort commitment",
            ),
            (
                tombstone.receipt.pre_effect_abort_proof_digest.as_deref(),
                "tombstone abort proof",
            ),
        ] {
            if let Some(value) = value {
                validate_digest(value, field)?;
            }
        }
        if let Some(reason) = tombstone.receipt.cancel_reason.as_deref() {
            validate_cancel_reason(reason)?;
        }
    }
    if active > store.max_active_runs {
'''
    text = replace_once(
        text,
        before_active_bound,
        tombstone_validation,
        "durable run tombstone digest changed",
    )

    support_anchor = '''fn atomic_replace_durable_run_store(
'''
    support = '''fn durable_run_store_sha256(
    store: &DurableRunStoreV1,
) -> Result<String, AgentRunError> {
    let encoded = serde_json::to_vec(store).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run store digest: {error}"))
    })?;
    let mut bytes = b"hepta.runtime.codex.agentd-run-store.v2\\0".to_vec();
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn durable_run_tombstone_sha256(
    snapshot: &RunSnapshot,
    receipt: &RunReceipt,
) -> Result<String, AgentRunError> {
    let encoded = serde_json::to_vec(&(snapshot, receipt)).map_err(|error| {
        AgentRunError::Persistence(format!("encode durable run tombstone: {error}"))
    })?;
    let mut bytes = b"hepta.runtime.codex.agentd-run-tombstone.v1\\0".to_vec();
    bytes.extend_from_slice(&encoded);
    Ok(Digest32::of_bytes(&bytes).to_string())
}

fn atomic_replace_durable_run_store(
'''
    text = replace_once(text, support_anchor, support, "fn durable_run_store_sha256(")

    if "closed_run_tombstone_survives_reopen_and_blocks_identity_reuse" not in text:
        tests_path = ROOT / "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs"
        tests = tests_path.read_text(encoding="utf-8")
        tests += r'''

#[test]
fn closed_run_tombstone_survives_reopen_and_blocks_identity_reuse() {
    let directory = tempfile::tempdir().expect("tempdir");
    let path = directory.path().join("agent-runs.json");
    let mut owner = AgentRunCoordinator::open_durable(composition(), path.clone())
        .expect("open owner");
    let admitted = owner.start_run(100, snapshot()).expect("start");
    owner.persist().expect("persist admission");
    let attached = owner
        .attach_context(101, admitted.revision, attachment())
        .expect("attach");
    owner.persist().expect("persist context");
    let dispatched = owner
        .mark_dispatched(102, "run.1", attached.revision)
        .expect("dispatch");
    owner.persist().expect("persist dispatch");
    let terminal = owner
        .observe_terminal(
            "run.1",
            dispatched.revision,
            RunPhase::Succeeded,
            true,
        )
        .expect("terminal");
    owner.persist().expect("persist terminal");
    owner
        .remove_closed_run("run.1", terminal.revision)
        .expect("archive closed run");
    owner.persist().expect("persist tombstone");
    drop(owner);

    let mut recovered = AgentRunCoordinator::open_durable(composition(), path)
        .expect("reopen owner");
    let status = recovered.run("run.1").expect("tombstoned status");
    assert_eq!(status.phase, RunPhase::Succeeded);
    assert!(status.terminal_observed);
    assert!(matches!(
        recovered.start_run(200, snapshot()),
        Err(AgentRunError::Conflict)
    ));
    let replay = recovered
        .remove_closed_run("run.1", status.revision)
        .expect("idempotent tombstone removal");
    assert!(replay.idempotent);
}
'''
        tests_path.write_text(tests, encoding="utf-8")

    TARGET.write_text(text, encoding="utf-8")
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
