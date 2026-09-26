#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str, marker: str | None = None) -> None:
    text = read(path)
    if marker is not None and marker in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one literal match, found {count}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


def sub_once(path: str, pattern: str, replacement: str, marker: str | None = None) -> None:
    text = read(path)
    if marker is not None and marker in text:
        return
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:120]!r}")
    write(path, updated)


# ---------------------------------------------------------------------------
# PlannerStoreV1: kernel-released advisory writer lock, overflow-safe recovery,
# deterministic disk-full failpoint, and a real process-abort/restart test.
# ---------------------------------------------------------------------------
STORE = "codex-rs/hepta-control-plane/src/planner_store.rs"

replace_once(
    STORE,
    "use std::fs::OpenOptions;\nuse std::io::ErrorKind;\n",
    "use std::fs::OpenOptions;\nuse std::fs::TryLockError;\nuse std::io::ErrorKind;\n",
    "use std::fs::TryLockError;",
)

replace_once(
    STORE,
    "    BeforeDataSync,\n    BeforeAtomicRename,\n",
    "    BeforeDataSync,\n    DiskFullBeforeFrame,\n    BeforeAtomicRename,\n",
    "DiskFullBeforeFrame",
)

replace_once(
    STORE,
    "    path: PathBuf,\n    lock_path: PathBuf,\n    file: File,\n",
    "    path: PathBuf,\n    _writer_lock: File,\n    file: File,\n",
    "_writer_lock: File",
)

sub_once(
    STORE,
    r"    pub fn open\(path: impl AsRef<Path>\) -> Result<Self, PlannerStoreError> \{.*?\n    fn open_locked\(path: PathBuf, lock_path: PathBuf\) -> Result<Self, PlannerStoreError> \{",
    '''    pub fn open(path: impl AsRef<Path>) -> Result<Self, PlannerStoreError> {
        let path = path.as_ref().to_path_buf();
        let parent = path.parent().unwrap_or_else(|| Path::new("."));
        fs::create_dir_all(parent)?;
        let lock_path = lock_path_for(&path);
        let mut writer_lock = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .open(&lock_path)?;
        match writer_lock.try_lock() {
            Ok(()) => {}
            Err(TryLockError::WouldBlock) => return Err(PlannerStoreError::WriterLocked),
            Err(TryLockError::Error(error)) => return Err(error.into()),
        }
        writer_lock.set_len(0)?;
        writer_lock.write_all(b"hepta-control-planner-store-v1\\npid=")?;
        writer_lock.write_all(std::process::id().to_string().as_bytes())?;
        writer_lock.write_all(b"\\n")?;
        writer_lock.sync_all()?;
        sync_directory(parent)?;
        Self::open_locked(path, writer_lock)
    }

    fn open_locked(path: PathBuf, writer_lock: File) -> Result<Self, PlannerStoreError> {''',
    "match writer_lock.try_lock()",
)

replace_once(
    STORE,
    "        Ok(Self {\n            path,\n            lock_path,\n            file,\n",
    "        Ok(Self {\n            path,\n            _writer_lock: writer_lock,\n            file,\n",
    "_writer_lock: writer_lock",
)

replace_once(
    STORE,
    "        self.hit(PlannerStoreFailpointV1::BeforeFrameWrite)?;\n        let record = build_record(self.next_sequence, kind, payload)?;\n",
    '''        self.hit(PlannerStoreFailpointV1::BeforeFrameWrite)?;
        if self.failpoint == Some(PlannerStoreFailpointV1::DiskFullBeforeFrame) {
            self.failpoint = None;
            return Err(PlannerStoreError::Io(std::io::Error::new(
                ErrorKind::StorageFull,
                "injected planner-store disk-full failure",
            )));
        }
        let record = build_record(self.next_sequence, kind, payload)?;
''',
    "injected planner-store disk-full failure",
)

sub_once(
    STORE,
    r"impl Drop for PlannerStoreV1 \{\n    fn drop\(&mut self\) \{.*?\n    \}\n\}",
    '''impl Drop for PlannerStoreV1 {
    fn drop(&mut self) {
        let _ = self.file.sync_all();
        // `_writer_lock` intentionally remains open until field drop. The
        // kernel releases File::try_lock locks on normal close and process
        // termination, so a crash cannot strand a permanent path lock.
    }
}''',
    "kernel releases File::try_lock locks",
)

replace_once(
    STORE,
    '''        let expected_sequence = records
            .last()
            .map_or(sequence, |record: &PlannerStoreRecordV1| {
                record.sequence + 1
            });
        if sequence == 0 || sequence != expected_sequence {
''',
    '''        let expected_sequence = records.last().map_or(Ok(sequence), |record: &PlannerStoreRecordV1| {
            record
                .sequence
                .checked_add(1)
                .ok_or(PlannerStoreError::LengthOverflow)
        })?;
        if sequence == 0 || sequence != expected_sequence {
''',
    "record.sequence\n                .checked_add(1)",
)

replace_once(
    STORE,
    '''    #[test]
    fn complete_frame_corruption_fails_closed() {
''',
    '''    #[test]
    fn disk_full_is_fail_closed_without_advancing_the_log() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        let mut store = PlannerStoreV1::open(&path).expect("open");
        store.set_failpoint(Some(PlannerStoreFailpointV1::DiskFullBeforeFrame));
        assert!(matches!(
            store.append_decision(&envelope()),
            Err(PlannerStoreError::Io(error)) if error.kind() == ErrorKind::StorageFull
        ));
        assert!(store.records().is_empty());
        store
            .append_decision(&envelope())
            .expect("append after released disk-full failpoint");
        assert_eq!(store.records().len(), 1);
    }

    #[test]
    fn crash_lock_holder_child() {
        let Some(path) = std::env::var_os("HEPTA_PLANNER_STORE_CRASH_PATH") else {
            return;
        };
        let marker = std::env::var_os("HEPTA_PLANNER_STORE_CRASH_MARKER")
            .expect("crash marker path");
        let _store = PlannerStoreV1::open(PathBuf::from(path)).expect("child acquires lock");
        fs::write(marker, b"lock-acquired").expect("write crash marker");
        std::process::abort();
    }

    #[test]
    fn process_crash_releases_single_writer_lock_for_restart() {
        let directory = tempfile::tempdir().expect("tempdir");
        let path = directory.path().join("planner.store");
        let marker = directory.path().join("lock-acquired.marker");
        let status = std::process::Command::new(std::env::current_exe().expect("test binary"))
            .arg("--exact")
            .arg("planner_store::tests::crash_lock_holder_child")
            .arg("--nocapture")
            .env("HEPTA_PLANNER_STORE_CRASH_PATH", &path)
            .env("HEPTA_PLANNER_STORE_CRASH_MARKER", &marker)
            .status()
            .expect("run crash child");
        assert!(!status.success(), "child must terminate abnormally");
        assert_eq!(fs::read(&marker).expect("crash marker"), b"lock-acquired");
        let _restarted = PlannerStoreV1::open(&path).expect("restart after process crash");
    }

    #[test]
    fn complete_frame_corruption_fails_closed() {
''',
    "process_crash_releases_single_writer_lock_for_restart",
)


# ---------------------------------------------------------------------------
# Protocol: preserve every request component needed for independent final-use
# replay and bind a process-local monotonic lease.
# ---------------------------------------------------------------------------
PROTOCOL = "codex-rs/hepta-agent-protocol/src/lib.rs"
replace_once(
    PROTOCOL,
    '''pub struct CognitiveContextPlan {
    /// Binds the evaluated context with `plan: null`, before any abstention.
    pub evaluated_context_digest: String,
    pub plan_receipt_digest: String,
    pub request_binding_digest: String,
    pub final_use_binding_digest: String,
    pub read_allowed: bool,
}
''',
    '''pub struct CognitiveContextPlan {
    /// Binds the evaluated context with `plan: null`, before any abstention.
    pub evaluated_context_digest: String,
    pub plan_receipt_digest: String,
    pub request_binding_digest: String,
    pub final_use_binding_digest: String,
    pub request_id: u64,
    pub query_digest: String,
    pub retrieval_profile_digest: String,
    pub ranker_digest: String,
    pub observed_at_monotonic_micros: u64,
    pub expires_at_monotonic_micros: u64,
    pub read_allowed: bool,
}
''',
    "observed_at_monotonic_micros",
)


# ---------------------------------------------------------------------------
# Agentd: exact request-component replay, current ranker/retrieval profile
# checks, and a true process-local monotonic expiry domain.
# ---------------------------------------------------------------------------
CONTEXT = "codex-rs/hepta-agentd/src/cognitive_context.rs"
replace_once(
    CONTEXT,
    "use std::collections::BTreeMap;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
    "use std::collections::BTreeMap;\nuse std::sync::OnceLock;\nuse std::time::Instant;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
    "use std::sync::OnceLock;",
)

replace_once(
    CONTEXT,
    '''const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
const CONTEXT_PLAN_OBSERVED_AT_MICROS: u64 = 1;
const CONTEXT_PLAN_EXPIRES_AT_MICROS: u64 = 1_000_001;
''',
    '''const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
const CONTEXT_PLAN_TTL_MICROS: u64 = 5_000_000;
const BASELINE_RETRIEVAL_PROFILE_DOMAIN: &[u8] =
    b"hepta.agentd.retrieval-profile.baseline.v1";
const BASELINE_RANKER_DOMAIN: &[u8] = b"hepta.agentd.ranker.baseline.v1";
static CONTEXT_PLAN_CLOCK_EPOCH: OnceLock<Instant> = OnceLock::new();
''',
    "CONTEXT_PLAN_CLOCK_EPOCH",
)

replace_once(
    CONTEXT,
    '''        ranker,
        None,
        None,
        None,
    )
''',
    '''        ranker,
        None,
        None,
        Some(1),
    )
''',
    "        Some(1),\n    )\n    .await\n}\n\n#[cfg(test)]\npub(crate) async fn read_with_retrieval_context",
)

replace_once(
    CONTEXT,
    '''        ranker,
        current_retrieval,
        None,
        None,
    )
''',
    '''        ranker,
        current_retrieval,
        None,
        Some(1),
    )
''',
)

replace_once(
    CONTEXT,
    '''    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let now = now_seconds()?;
''',
    '''    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
        return Err(CognitiveStoreError::Invalid(
            "context requires a 1..2048 byte query and a 1..4 result limit".to_string(),
        )
        .into());
    }
    let request_id = request_id.filter(|value| *value != 0).ok_or_else(|| {
        CognitiveStoreError::Invalid(
            "cognitive context requires a non-zero request id".to_string(),
        )
    })?;
    let now = now_seconds()?;
''',
    "cognitive context requires a non-zero request id",
)

replace_once(
    CONTEXT,
    '''    let expected_retrieval_context_digest = retrieval_context
        .as_ref()
        .map(RetrievalExecutionContextV1::binding_digest);
    if learning_sink.is_some() && retrieval_context.is_none() {
''',
    '''    let expected_retrieval_context_digest = retrieval_context
        .as_ref()
        .map(RetrievalExecutionContextV1::binding_digest);
    let query_digest = Digest32::of_bytes(query.as_bytes());
    let retrieval_profile_digest = expected_retrieval_context_digest
        .unwrap_or_else(baseline_retrieval_profile_digest);
    let ranker_digest = ranker
        .map(|ranker| ranker.policy_digest())
        .unwrap_or_else(baseline_ranker_digest);
    if learning_sink.is_some() && retrieval_context.is_none() {
''',
    "let retrieval_profile_digest = expected_retrieval_context_digest",
)

replace_once(
    CONTEXT,
    '''    let request_binding = context_request_binding(
        owner,
        body_generation,
        request_id,
        query,
        expected_retrieval_context_digest,
        downstream_policy_digest,
    );
    let plan = plan_observed_context(ObservedContextV1 {
''',
    '''    let request_binding = context_request_binding(
        owner,
        body_generation,
        request_id,
        query_digest,
        retrieval_profile_digest,
        ranker_digest,
    );
    let observed_at_monotonic_micros = context_plan_monotonic_micros()?;
    let expires_at_monotonic_micros = observed_at_monotonic_micros
        .checked_add(CONTEXT_PLAN_TTL_MICROS)
        .ok_or_else(|| CognitiveStoreError::Invalid("context plan lease overflow".to_string()))?;
    let plan = plan_observed_context(ObservedContextV1 {
''',
    "let observed_at_monotonic_micros = context_plan_monotonic_micros()?;",
)

replace_once(
    CONTEXT,
    '''        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: CONTEXT_PLAN_OBSERVED_AT_MICROS,
        expires_at_micros: CONTEXT_PLAN_EXPIRES_AT_MICROS,
''',
    '''        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: observed_at_monotonic_micros,
        expires_at_micros: expires_at_monotonic_micros,
''',
)

replace_once(
    CONTEXT,
    '''        request_binding,
        selected_read_binding,
        plan.read_allowed,
    );
''',
    '''        request_binding,
        selected_read_binding,
        observed_at_monotonic_micros,
        expires_at_monotonic_micros,
        plan.read_allowed,
    );
''',
)

replace_once(
    CONTEXT,
    '''        request_binding_digest: request_binding.to_string(),
        final_use_binding_digest: final_use_binding.to_string(),
        read_allowed: plan.read_allowed,
''',
    '''        request_binding_digest: request_binding.to_string(),
        final_use_binding_digest: final_use_binding.to_string(),
        request_id,
        query_digest: query_digest.to_string(),
        retrieval_profile_digest: retrieval_profile_digest.to_string(),
        ranker_digest: ranker_digest.to_string(),
        observed_at_monotonic_micros,
        expires_at_monotonic_micros,
        read_allowed: plan.read_allowed,
''',
    "query_digest: query_digest.to_string()",
)

replace_once(
    CONTEXT,
    '''        let request_id = request_id.ok_or(CognitiveContextError::RetrievalLearningUnavailable)?;
        let selected = assignment
''',
    '''        let selected = assignment
''',
)

sub_once(
    CONTEXT,
    r"    let evaluated_context_digest: Digest32 =.*?\n    // Ranking is part of the selected context semantics\.",
    '''    validate_context_plan_lease(plan, context_plan_monotonic_micros()?)?;
    let evaluated_context_digest: Digest32 =
        plan.evaluated_context_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid evaluated context digest: {error}"))
        })?;
    let plan_receipt_digest: Digest32 = plan.plan_receipt_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid plan receipt digest: {error}"))
    })?;
    let request_binding_digest: Digest32 =
        plan.request_binding_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid request binding digest: {error}"))
        })?;
    let query_digest: Digest32 = plan.query_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid query digest: {error}"))
    })?;
    let retrieval_profile_digest: Digest32 =
        plan.retrieval_profile_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid retrieval profile digest: {error}"))
        })?;
    let ranker_digest: Digest32 = plan.ranker_digest.parse().map_err(|error| {
        CognitiveStoreError::Invalid(format!("invalid ranker digest: {error}"))
    })?;
    let expected_final_use_binding: Digest32 =
        plan.final_use_binding_digest.parse().map_err(|error| {
            CognitiveStoreError::Invalid(format!("invalid final-use binding digest: {error}"))
        })?;
    let current_retrieval_profile_digest = retrieval_context_digest
        .unwrap_or_else(baseline_retrieval_profile_digest);
    let current_ranker_digest = ranker
        .map(|ranker| ranker.policy_digest())
        .unwrap_or_else(baseline_ranker_digest);
    if retrieval_profile_digest != current_retrieval_profile_digest
        || ranker_digest != current_ranker_digest
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context retrieval or ranker profile changed before final use".to_string(),
        )
        .into());
    }
    let actual_request_binding = context_request_binding(
        owner,
        body_generation,
        plan.request_id,
        query_digest,
        current_retrieval_profile_digest,
        current_ranker_digest,
    );
    if actual_request_binding != request_binding_digest {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context request binding changed before final use".to_string(),
        )
        .into());
    }
    let actual_final_use_binding = context_plan_final_use_binding(
        evaluated_context_digest,
        plan_receipt_digest,
        request_binding_digest,
        current_read_binding,
        plan.observed_at_monotonic_micros,
        plan.expires_at_monotonic_micros,
        plan.read_allowed,
    );
    if actual_final_use_binding != expected_final_use_binding {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context plan receipt binding changed before final use".to_string(),
        )
        .into());
    }
    let verified_records = verified_context_records(items)?;
    let replay = plan_observed_context(ObservedContextV1 {
        owner_id: StableId::new(owner.as_str())
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        body_generation: Generation::new(body_generation)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        source_snapshot_digest: expected_snapshot,
        read_digest: current_read_binding,
        request_binding_digest,
        verified_records: &verified_records,
        encoded_context: &encoded,
        maximum_context_bytes: MAX_CONTEXT_JSON_BYTES as u32,
        observed_at_micros: plan.observed_at_monotonic_micros,
        expires_at_micros: plan.expires_at_monotonic_micros,
    })
    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;
    if replay.read_allowed != plan.read_allowed
        || replay.context_digest != evaluated_context_digest
        || replay.evaluation.plan.receipt_digest() != plan_receipt_digest
    {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context planner receipt does not replay at final use".to_string(),
        )
        .into());
    }

    // Ranking is part of the selected context semantics.''',
    "let actual_request_binding = context_request_binding(",
)

sub_once(
    CONTEXT,
    r"fn context_request_binding\(.*?\n\}\n\nfn context_plan_final_use_binding\(.*?\n\}\n",
    '''fn baseline_retrieval_profile_digest() -> Digest32 {
    Digest32::of_bytes(BASELINE_RETRIEVAL_PROFILE_DOMAIN)
}

fn baseline_ranker_digest() -> Digest32 {
    Digest32::of_bytes(BASELINE_RANKER_DOMAIN)
}

fn context_plan_monotonic_micros() -> Result<u64, CognitiveContextError> {
    let elapsed = CONTEXT_PLAN_CLOCK_EPOCH
        .get_or_init(Instant::now)
        .elapsed()
        .as_micros();
    u64::try_from(elapsed)
        .map(|value| value.saturating_add(1))
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()).into())
}

fn validate_context_plan_lease(
    plan: &CognitiveContextPlan,
    now_monotonic_micros: u64,
) -> Result<(), CognitiveContextError> {
    let lifetime = plan
        .expires_at_monotonic_micros
        .checked_sub(plan.observed_at_monotonic_micros)
        .ok_or_else(|| {
            CognitiveStoreError::Invalid("invalid cognitive context monotonic lease".to_string())
        })?;
    if plan.request_id == 0
        || plan.observed_at_monotonic_micros == 0
        || lifetime == 0
        || lifetime > CONTEXT_PLAN_TTL_MICROS
    {
        return Err(CognitiveStoreError::Invalid(
            "invalid cognitive context monotonic lease".to_string(),
        )
        .into());
    }
    if now_monotonic_micros < plan.observed_at_monotonic_micros {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context monotonic clock domain changed".to_string(),
        )
        .into());
    }
    if now_monotonic_micros >= plan.expires_at_monotonic_micros {
        return Err(CognitiveStoreError::Conflict(
            "cognitive context plan expired before final use".to_string(),
        )
        .into());
    }
    Ok(())
}

fn context_request_binding(
    owner: &AgentId,
    body_generation: u64,
    request_id: u64,
    query_digest: Digest32,
    retrieval_profile_digest: Digest32,
    ranker_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-request.v2\\0".to_vec();
    bytes.extend_from_slice(&(owner.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(&request_id.to_be_bytes());
    bytes.extend_from_slice(query_digest.as_array());
    bytes.extend_from_slice(retrieval_profile_digest.as_array());
    bytes.extend_from_slice(ranker_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn context_plan_final_use_binding(
    evaluated_context_digest: Digest32,
    plan_receipt_digest: Digest32,
    request_binding_digest: Digest32,
    read_binding_digest: Digest32,
    observed_at_monotonic_micros: u64,
    expires_at_monotonic_micros: u64,
    read_allowed: bool,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-final-use.v2\\0".to_vec();
    bytes.extend_from_slice(evaluated_context_digest.as_array());
    bytes.extend_from_slice(plan_receipt_digest.as_array());
    bytes.extend_from_slice(request_binding_digest.as_array());
    bytes.extend_from_slice(read_binding_digest.as_array());
    bytes.extend_from_slice(&observed_at_monotonic_micros.to_be_bytes());
    bytes.extend_from_slice(&expires_at_monotonic_micros.to_be_bytes());
    bytes.push(u8::from(read_allowed));
    Digest32::of_bytes(&bytes)
}
''',
    "fn baseline_retrieval_profile_digest()",
)

RANKER = "codex-rs/hepta-agentd/src/cognitive_ranker.rs"
replace_once(
    RANKER,
    '''    pub(crate) fn require_identity(&self, owner: &AgentId, generation: u64) -> Result<(), String> {
''',
    '''    pub(crate) fn policy_digest(&self) -> Digest32 {
        self.policy_digest
    }

    pub(crate) fn require_identity(&self, owner: &AgentId, generation: u64) -> Result<(), String> {
''',
    "pub(crate) fn policy_digest(&self)",
)

TESTS = "codex-rs/hepta-agentd/src/cognitive_context_tests.rs"
replace_once(
    TESTS,
    '''    assert_eq!(
        usize::from(current.verified_item_count),
        context.items.len()
    );
    let mut tampered_plan = context.plan.clone().unwrap();
''',
    '''    assert_eq!(
        usize::from(current.verified_item_count),
        context.items.len()
    );
    let plan = context.plan.as_ref().unwrap();
    assert_ne!(plan.request_id, 0);
    assert!(
        super::validate_context_plan_lease(plan, plan.expires_at_monotonic_micros).is_err(),
        "an unchanged packet must expire at its monotonic deadline"
    );
    let mut tampered_receipt = context.plan.clone().unwrap();
    tampered_receipt.plan_receipt_digest = "33".repeat(32);
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            Some(&tampered_receipt),
            None,
        )
        .await
        .is_err(),
        "a substituted plan receipt must fail final-use validation"
    );
    let mut tampered_query = context.plan.clone().unwrap();
    tampered_query.query_digest = "44".repeat(32);
    assert!(
        revalidate(
            &store,
            &owner,
            &context.snapshot_digest,
            &context.read_digest,
            context.omitted_records,
            &context.items,
            Some(&tampered_query),
            None,
        )
        .await
        .is_err(),
        "a substituted query digest must fail final-use validation"
    );
    let mut tampered_plan = context.plan.clone().unwrap();
''',
    "an unchanged packet must expire at its monotonic deadline",
)

print("control.runtime P0 fixups applied")
