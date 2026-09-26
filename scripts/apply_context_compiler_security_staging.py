#!/usr/bin/env python3
"""Apply context.compiler raw-data redaction and memory-only request handling."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "codex-rs/hepta-agentd/src/provider_bound_prompt_runtime.rs"
RUNTIME_TESTS = ROOT / "codex-rs/hepta-agentd/src/provider_bound_prompt_runtime_tests.rs"
V2 = ROOT / "codex-rs/hepta-context-compiler/src/v2.rs"
PROVIDER_BOUND = ROOT / "codex-rs/hepta-context-compiler/src/provider_bound.rs"
PROMPT_BOUND = ROOT / "codex-rs/hepta-intelligence/src/provider_bound_prompt.rs"
PROMPT_DELIVERY = ROOT / "codex-rs/hepta-intelligence/src/prompt_delivery.rs"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path.relative_to(ROOT)}: expected one replacement, found {count}: {old[:140]!r}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def patch_runtime() -> None:
    replace_once(RUNTIME, "const RUNTIME_SCHEMA: u32 = 1;", "const RUNTIME_SCHEMA: u32 = 2;")
    replace_once(
        RUNTIME,
        "    Inserted,\n    Unchanged,\n    ReplacedGeneration,",
        "    Inserted,\n    Unchanged,\n    Rehydrated,\n    ReplacedGeneration,",
    )
    replace_once(
        RUNTIME,
        "    RequestDigestMismatch,\n    StageDigestMismatch,",
        "    RequestDigestMismatch,\n    RecompileRequired,\n    StageDigestMismatch,",
    )
    replace_once(
        RUNTIME,
        '''impl fmt::Display for AgentdProviderBoundPromptRuntimeErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
''',
        '''impl AgentdProviderBoundPromptRuntimeErrorV2 {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidDispatchId => "provider_bound_runtime_invalid_dispatch_id",
            Self::InvalidAttemptId => "provider_bound_runtime_invalid_attempt_id",
            Self::InvalidGeneration => "provider_bound_runtime_invalid_generation",
            Self::InvalidTime => "provider_bound_runtime_invalid_time",
            Self::EmptyDigest(_) => "provider_bound_runtime_empty_digest",
            Self::RequestMissing => "provider_bound_runtime_request_missing",
            Self::RequestTooLarge => "provider_bound_runtime_request_too_large",
            Self::RequestDigestMismatch => "provider_bound_runtime_request_digest_mismatch",
            Self::RecompileRequired => "provider_bound_runtime_recompile_required",
            Self::StageDigestMismatch => "provider_bound_runtime_stage_digest_mismatch",
            Self::ClaimDigestMismatch => "provider_bound_runtime_claim_digest_mismatch",
            Self::TerminalDigestMismatch => "provider_bound_runtime_terminal_digest_mismatch",
            Self::StageNotFound => "provider_bound_runtime_stage_not_found",
            Self::StageConflict => "provider_bound_runtime_stage_conflict",
            Self::StaleGeneration => "provider_bound_runtime_stale_generation",
            Self::DispatchConflict => "provider_bound_runtime_dispatch_conflict",
            Self::TerminalWithoutDispatch => "provider_bound_runtime_terminal_without_dispatch",
            Self::TerminalBindingMismatch => "provider_bound_runtime_terminal_binding_mismatch",
            Self::TerminalConflict => "provider_bound_runtime_terminal_conflict",
            Self::TerminalAlreadyRecorded => "provider_bound_runtime_terminal_already_recorded",
            Self::IndeterminatePending => "provider_bound_runtime_indeterminate_pending",
            Self::CapacityExceeded => "provider_bound_runtime_capacity_exceeded",
            Self::CorruptState => "provider_bound_runtime_corrupt_state",
            Self::StateLocked => "provider_bound_runtime_state_locked",
            Self::StatePoisoned => "provider_bound_runtime_state_poisoned",
            Self::Unavailable => "provider_bound_runtime_unavailable",
            Self::IndeterminateDurability => "provider_bound_runtime_indeterminate_durability",
            Self::ReopenRequired => "provider_bound_runtime_reopen_required",
            Self::SourceAuthorityGranted => "provider_bound_runtime_source_authority_granted",
        }
    }
}

impl fmt::Display for AgentdProviderBoundPromptRuntimeErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}
''',
    )
    replace_once(
        RUNTIME,
        '''    exact_token_count: u64,
    exact_request_bytes: Vec<u8>,
    stage_digest: Digest32,
''',
        '''    exact_token_count: u64,
    exact_request_bytes_len: u64,
    exact_request_bytes: Option<Vec<u8>>,
    stage_digest: Digest32,
''',
    )
    replace_once(
        RUNTIME,
        '''            exact_token_count: prepared.final_tokenization().token_count(),
            exact_request_bytes: prepared.provider_request().bytes().to_vec(),
            stage_digest: Digest32::ZERO,
''',
        '''            exact_token_count: prepared.final_tokenization().token_count(),
            exact_request_bytes_len: u64::try_from(prepared.provider_request().bytes().len())
                .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::RequestTooLarge)?,
            exact_request_bytes: Some(prepared.provider_request().bytes().to_vec()),
            stage_digest: Digest32::ZERO,
''',
    )
    replace_once(
        RUNTIME,
        '''    pub fn exact_request_bytes(&self) -> &[u8] {
        &self.exact_request_bytes
    }
''',
        '''    pub fn exact_request_bytes(&self) -> Option<&[u8]> {
        self.exact_request_bytes.as_deref()
    }
''',
    )
    replace_once(
        RUNTIME,
        '''        if self.exact_request_bytes.is_empty() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestMissing);
        }
        if self.exact_request_bytes.len() > MAX_PROVIDER_REQUEST_BYTES_V2 {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestTooLarge);
        }
        if self.exact_token_count == 0
            || Digest32::of_bytes(&self.exact_request_bytes) != self.provider_request_digest
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch);
        }
''',
        '''        if self.exact_request_bytes_len == 0
            || self.exact_request_bytes_len
                > u64::try_from(MAX_PROVIDER_REQUEST_BYTES_V2).unwrap_or(u64::MAX)
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestTooLarge);
        }
        if self.exact_token_count == 0 {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch);
        }
        if let Some(bytes) = &self.exact_request_bytes
            && (u64::try_from(bytes.len()).unwrap_or(u64::MAX) != self.exact_request_bytes_len
                || Digest32::of_bytes(bytes) != self.provider_request_digest)
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch);
        }
''',
    )
    replace_once(
        RUNTIME,
        '''        push_u64(
            &mut bytes,
            u64::try_from(self.exact_request_bytes.len()).unwrap_or(u64::MAX),
        );
        Digest32::of_bytes(&bytes)
    }
}
''',
        '''        push_u64(&mut bytes, self.exact_request_bytes_len);
        Digest32::of_bytes(&bytes)
    }

    fn same_metadata(&self, other: &Self) -> bool {
        self.dispatch_id == other.dispatch_id
            && self.generation == other.generation
            && self.bundle_digest == other.bundle_digest
            && self.canonical_serialization_proof_digest
                == other.canonical_serialization_proof_digest
            && self.canonical_payload_digest == other.canonical_payload_digest
            && self.attachment_digest == other.attachment_digest
            && self.snapshot_successor_digest == other.snapshot_successor_digest
            && self.preparation_digest == other.preparation_digest
            && self.provider_request_digest == other.provider_request_digest
            && self.provider_request_coverage_digest == other.provider_request_coverage_digest
            && self.wire_semantic_digest == other.wire_semantic_digest
            && self.tokenizer_identity_digest == other.tokenizer_identity_digest
            && self.tokenizer_attestation_digest == other.tokenizer_attestation_digest
            && self.exact_token_count == other.exact_token_count
            && self.exact_request_bytes_len == other.exact_request_bytes_len
            && self.stage_digest == other.stage_digest
    }
}

impl fmt::Debug for ProviderBoundPromptStageV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderBoundPromptStageV2")
            .field("dispatch_id", &self.dispatch_id)
            .field("generation", &self.generation)
            .field("bundle_digest", &self.bundle_digest)
            .field("preparation_digest", &self.preparation_digest)
            .field("provider_request_digest", &self.provider_request_digest)
            .field("exact_token_count", &self.exact_token_count)
            .field("exact_request_bytes_len", &self.exact_request_bytes_len)
            .field("request_materialized", &self.exact_request_bytes.is_some())
            .field("stage_digest", &self.stage_digest)
            .finish()
    }
}
''',
    )
    replace_once(
        RUNTIME,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ProviderBoundPromptStageV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct ProviderBoundPromptStageV2",
    )
    replace_once(
        RUNTIME,
        '''            exact_request_bytes: entry.stage.exact_request_bytes.clone(),
        };
''',
        '''            exact_request_bytes: entry
                .stage
                .exact_request_bytes
                .clone()
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::RecompileRequired)?,
        };
''',
    )
    replace_once(
        RUNTIME,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ProviderBoundDispatchLeaseV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct ProviderBoundDispatchLeaseV2",
    )
    replace_once(
        RUNTIME,
        '''impl ProviderBoundDispatchLeaseV2 {
''',
        '''impl fmt::Debug for ProviderBoundDispatchLeaseV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderBoundDispatchLeaseV2")
            .field("disposition", &self.disposition)
            .field("dispatch_id", &self.dispatch_id)
            .field("generation", &self.generation)
            .field("attempt_id", &self.attempt_id)
            .field("claim_digest", &self.claim_digest)
            .field("provider_request_digest", &self.provider_request_digest)
            .field("exact_request_bytes_len", &self.exact_request_bytes.len())
            .finish()
    }
}

impl ProviderBoundDispatchLeaseV2 {
''',
    )
    replace_once(
        RUNTIME,
        '''            if let Some(existing) = &entry.dispatch {
                if existing.attempt_id != attempt_id {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
                }
                existing.validate_for(&entry.stage)?;
                return ProviderBoundDispatchLeaseV2::from_entry(
                    entry,
                    ProviderBoundDispatchDispositionV2::ExistingClaim,
                );
            }
''',
        '''            if entry.dispatch.is_some() {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
            }
''',
    )
    replace_once(
        RUNTIME,
        '''            entry.dispatch = Some(claim);
            ProviderBoundDispatchLeaseV2::from_entry(
                entry,
                ProviderBoundDispatchDispositionV2::Claimed,
            )
''',
        '''            entry.dispatch = Some(claim);
            let lease = ProviderBoundDispatchLeaseV2::from_entry(
                entry,
                ProviderBoundDispatchDispositionV2::Claimed,
            )?;
            entry.stage.exact_request_bytes = None;
            Ok(lease)
''',
    )
    old_stage = '''    fn stage(
        &self,
        stage: ProviderBoundPromptStageV2,
    ) -> Result<ProviderBoundStageDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        stage.validate()?;
        let key = stage.dispatch_id.to_string();
        self.commit_state(|state| {
            let Some(existing) = state.entries.get(&key) else {
                if state.entries.len() >= MAX_RUNTIME_ENTRIES {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::CapacityExceeded);
                }
                state.entries.insert(
                    key,
                    ProviderBoundRuntimeEntryV2 {
                        stage,
                        dispatch: None,
                        terminal: None,
                    },
                );
                return Ok(ProviderBoundStageDispositionV2::Inserted);
            };
            if existing.stage == stage {
                return Ok(ProviderBoundStageDispositionV2::Unchanged);
            }
            if stage.generation <= existing.stage.generation {
                return if stage.generation < existing.stage.generation {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
                } else {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StageConflict)
                };
            }
            if existing.dispatch.is_some()
                && !existing.terminal.as_ref().is_some_and(|value| value.is_final())
            {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
            }
            state.entries.insert(
                key,
                ProviderBoundRuntimeEntryV2 {
                    stage,
                    dispatch: None,
                    terminal: None,
                },
            );
            Ok(ProviderBoundStageDispositionV2::ReplacedGeneration)
        })
    }
'''
    new_stage = '''    fn stage(
        &self,
        stage: ProviderBoundPromptStageV2,
    ) -> Result<ProviderBoundStageDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        stage.validate()?;
        let key = stage.dispatch_id.to_string();
        self.commit_state(|state| {
            if !state.entries.contains_key(&key) {
                if state.entries.len() >= MAX_RUNTIME_ENTRIES {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::CapacityExceeded);
                }
                state.entries.insert(
                    key,
                    ProviderBoundRuntimeEntryV2 {
                        stage,
                        dispatch: None,
                        terminal: None,
                    },
                );
                return Ok(ProviderBoundStageDispositionV2::Inserted);
            }
            let existing = state
                .entries
                .get_mut(&key)
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?;
            if existing.stage == stage {
                return Ok(ProviderBoundStageDispositionV2::Unchanged);
            }
            if stage.generation == existing.stage.generation
                && existing.stage.same_metadata(&stage)
                && existing.stage.exact_request_bytes.is_none()
                && stage.exact_request_bytes.is_some()
            {
                if existing.dispatch.is_some() {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
                }
                existing.stage.exact_request_bytes = stage.exact_request_bytes;
                return Ok(ProviderBoundStageDispositionV2::Rehydrated);
            }
            if stage.generation <= existing.stage.generation {
                return if stage.generation < existing.stage.generation {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
                } else {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StageConflict)
                };
            }
            if existing.dispatch.is_some()
                && !existing.terminal.as_ref().is_some_and(|value| value.is_final())
            {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
            }
            *existing = ProviderBoundRuntimeEntryV2 {
                stage,
                dispatch: None,
                terminal: None,
            };
            Ok(ProviderBoundStageDispositionV2::ReplacedGeneration)
        })
    }
'''
    replace_once(RUNTIME, old_stage, new_stage)
    replace_once(
        RUNTIME,
        '''    exact_token_count: u64,
    exact_request_base64: String,
    stage_digest: [u8; 32],
''',
        '''    exact_token_count: u64,
    #[serde(default)]
    exact_request_bytes_len: u64,
    #[serde(default, rename = "exact_request_base64", skip_serializing_if = "Option::is_none")]
    legacy_exact_request_base64: Option<String>,
    stage_digest: [u8; 32],
''',
    )
    replace_once(
        RUNTIME,
        '''        let stored: StoredProviderBoundRuntimeStateV2 = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?;
        let state = restore_state(stored)?;
        Ok((store, state))
''',
        '''        let stored: StoredProviderBoundRuntimeStateV2 = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?;
        let stored_schema = stored.schema;
        let state = restore_state(stored)?;
        if stored_schema < RUNTIME_SCHEMA {
            store.persist(&state)?;
        }
        Ok((store, state))
''',
    )
    replace_once(
        RUNTIME,
        '''        exact_token_count: stage.exact_token_count,
        exact_request_base64: STANDARD_NO_PAD.encode(&stage.exact_request_bytes),
        stage_digest: stage.stage_digest.into_array(),
''',
        '''        exact_token_count: stage.exact_token_count,
        exact_request_bytes_len: stage.exact_request_bytes_len,
        legacy_exact_request_base64: None,
        stage_digest: stage.stage_digest.into_array(),
''',
    )
    replace_once(
        RUNTIME,
        '''    if stored.schema != RUNTIME_SCHEMA || stored.entries.len() > MAX_RUNTIME_ENTRIES {
''',
        '''    if !matches!(stored.schema, 1 | RUNTIME_SCHEMA)
        || stored.entries.len() > MAX_RUNTIME_ENTRIES
    {
''',
    )
    old_restore = '''        exact_token_count: stored.exact_token_count,
        exact_request_bytes: STANDARD_NO_PAD
            .decode(stored.exact_request_base64)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?,
        stage_digest: Digest32::from_array(stored.stage_digest),
'''
    new_restore = '''        exact_token_count: stored.exact_token_count,
        exact_request_bytes_len: if stored.exact_request_bytes_len != 0 {
            stored.exact_request_bytes_len
        } else {
            u64::try_from(
                STANDARD_NO_PAD
                    .decode(
                        stored
                            .legacy_exact_request_base64
                            .as_deref()
                            .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?,
                    )
                    .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?
                    .len(),
            )
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::RequestTooLarge)?
        },
        exact_request_bytes: None,
        stage_digest: Digest32::from_array(stored.stage_digest),
'''
    replace_once(RUNTIME, old_restore, new_restore)


def patch_runtime_tests() -> None:
    replace_once(
        RUNTIME_TESTS,
        '''        exact_token_count: u64::try_from(request.len()).unwrap_or(u64::MAX),
        exact_request_bytes: request.to_vec(),
        stage_digest: Digest32::ZERO,
''',
        '''        exact_token_count: u64::try_from(request.len()).unwrap_or(u64::MAX),
        exact_request_bytes_len: u64::try_from(request.len()).unwrap_or(u64::MAX),
        exact_request_bytes: Some(request.to_vec()),
        stage_digest: Digest32::ZERO,
''',
    )
    old_first = '''#[test]
fn durable_claim_reopens_with_the_exact_same_request_bytes() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:reopen");
    let attempt_id = id("attempt:provider-bound:one");
    let exact_request = b"provider-final-request\\0with-framing\\ncontext";
    let stage = stage(dispatch_id.as_str(), 1, exact_request);
    let original_stage_digest = stage.stage_digest();
    let original_request_digest = stage.provider_request_digest();

    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        assert_eq!(
            runtime.stage(stage.clone()).expect("stage"),
            ProviderBoundStageDispositionV2::Inserted
        );
        let lease = runtime
            .claim_dispatch(&dispatch_id, 1, attempt_id.clone(), 100)
            .expect("claim dispatch");
        assert_eq!(
            lease.disposition(),
            ProviderBoundDispatchDispositionV2::Claimed
        );
        assert_eq!(lease.exact_request_bytes(), exact_request);
        assert_eq!(lease.provider_request_digest(), original_request_digest);
    }

    let reopened = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("reopen runtime");
    let snapshot = reopened
        .snapshot(&dispatch_id)
        .expect("snapshot")
        .expect("entry");
    assert_eq!(snapshot.stage_digest, original_stage_digest);
    assert_eq!(snapshot.dispatch_attempt_id, Some(attempt_id.clone()));
    let lease = reopened
        .claim_dispatch(&dispatch_id, 1, attempt_id, 999)
        .expect("idempotent claim");
    assert_eq!(
        lease.disposition(),
        ProviderBoundDispatchDispositionV2::ExistingClaim
    );
    assert_eq!(lease.exact_request_bytes(), exact_request);
}
'''
    new_first = '''#[test]
fn durable_claim_reopens_as_indeterminate_without_releasing_request_bytes() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:reopen");
    let attempt_id = id("attempt:provider-bound:one");
    let exact_request = b"provider-final-request\\0with-framing\\ncontext";
    let stage = stage(dispatch_id.as_str(), 1, exact_request);
    let original_stage_digest = stage.stage_digest();
    let original_request_digest = stage.provider_request_digest();

    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        assert_eq!(
            runtime.stage(stage).expect("stage"),
            ProviderBoundStageDispositionV2::Inserted
        );
        let lease = runtime
            .claim_dispatch(&dispatch_id, 1, attempt_id.clone(), 100)
            .expect("claim dispatch");
        assert_eq!(
            lease.disposition(),
            ProviderBoundDispatchDispositionV2::Claimed
        );
        assert_eq!(lease.exact_request_bytes(), exact_request);
        assert_eq!(lease.provider_request_digest(), original_request_digest);
    }

    let state_bytes = std::fs::read(temporary.path().join(STATE_FILE)).expect("read state");
    assert!(!state_bytes.windows(exact_request.len()).any(|window| window == exact_request));
    assert!(!String::from_utf8_lossy(&state_bytes).contains("exact_request_base64"));

    let reopened = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("reopen runtime");
    let snapshot = reopened
        .snapshot(&dispatch_id)
        .expect("snapshot")
        .expect("entry");
    assert_eq!(snapshot.stage_digest, original_stage_digest);
    assert_eq!(snapshot.dispatch_attempt_id, Some(attempt_id.clone()));
    assert_eq!(
        reopened.claim_dispatch(&dispatch_id, 1, attempt_id, 999),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending)
    );
}

#[test]
fn undispatched_stage_reopens_metadata_only_and_requires_exact_restage() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:restage");
    let attempt_id = id("attempt:provider-bound:restage");
    let exact_request = b"request-that-must-not-be-persisted";
    let prepared_stage = stage(dispatch_id.as_str(), 11, exact_request);
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime.stage(prepared_stage.clone()).expect("stage");
    }

    let reopened = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
        .expect("reopen runtime");
    assert_eq!(
        reopened.claim_dispatch(&dispatch_id, 11, attempt_id.clone(), 110),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::RecompileRequired)
    );
    assert_eq!(
        reopened.stage(prepared_stage).expect("rehydrate exact bytes"),
        ProviderBoundStageDispositionV2::Rehydrated
    );
    let lease = reopened
        .claim_dispatch(&dispatch_id, 11, attempt_id, 111)
        .expect("claim after exact restage");
    assert_eq!(lease.exact_request_bytes(), exact_request);
}
'''
    replace_once(RUNTIME_TESTS, old_first, new_first)
    old_corrupt = '''#[test]
fn corrupt_request_bytes_are_rejected_on_reopen() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:corrupt");
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime
            .stage(stage(dispatch_id.as_str(), 1, b"original-request"))
            .expect("stage");
    }

    let state_path = temporary.path().join(STATE_FILE);
    let mut value: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&state_path).expect("read state"),
    )
    .expect("decode state");
    value["entries"][0]["stage"]["exact_request_base64"] =
        serde_json::Value::String(STANDARD_NO_PAD.encode(b"tampered-request"));
    std::fs::write(
        &state_path,
        serde_json::to_vec(&value).expect("encode corruption"),
    )
    .expect("write corruption");

    assert!(matches!(
        AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path()),
        Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch)
            | Err(AgentdProviderBoundPromptRuntimeErrorV2::StageDigestMismatch)
            | Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)
    ));
}
'''
    new_corrupt = '''#[test]
fn legacy_persisted_request_bytes_are_scrubbed_during_reopen_migration() {
    let temporary = tempfile::tempdir().expect("tempdir");
    let dispatch_id = id("dispatch:provider-bound:legacy-scrub");
    let exact_request = b"legacy-request-plaintext";
    {
        let runtime = AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("open runtime");
        runtime
            .stage(stage(dispatch_id.as_str(), 1, exact_request))
            .expect("stage");
    }

    let state_path = temporary.path().join(STATE_FILE);
    let mut value: serde_json::Value = serde_json::from_slice(
        &std::fs::read(&state_path).expect("read state"),
    )
    .expect("decode state");
    value["schema"] = serde_json::Value::from(1);
    let stage_value = value["entries"][0]["stage"]
        .as_object_mut()
        .expect("stage object");
    stage_value.remove("exact_request_bytes_len");
    stage_value.insert(
        "exact_request_base64".to_owned(),
        serde_json::Value::String(STANDARD_NO_PAD.encode(exact_request)),
    );
    std::fs::write(
        &state_path,
        serde_json::to_vec(&value).expect("encode legacy state"),
    )
    .expect("write legacy state");

    drop(
        AgentdProviderBoundPromptRuntimeV2::open_state_dir(temporary.path())
            .expect("migrate legacy state"),
    );
    let migrated = std::fs::read(&state_path).expect("read migrated state");
    let migrated_text = String::from_utf8_lossy(&migrated);
    assert!(!migrated_text.contains("exact_request_base64"));
    assert!(!migrated.windows(exact_request.len()).any(|window| window == exact_request));
    let migrated_value: serde_json::Value =
        serde_json::from_slice(&migrated).expect("decode migrated state");
    assert_eq!(migrated_value["schema"], serde_json::Value::from(RUNTIME_SCHEMA));
}
'''
    replace_once(RUNTIME_TESTS, old_corrupt, new_corrupt)


def patch_redacted_debug() -> None:
    replace_once(
        V2,
        '''#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextRealizedItemV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content: Vec<u8>,
}
''',
        '''#[derive(Clone, Eq, PartialEq)]
pub struct ContextRealizedItemV2 {
    pub item_id: StableId,
    pub role: ContextRoleV2,
    pub content: Vec<u8>,
}

impl fmt::Debug for ContextRealizedItemV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextRealizedItemV2")
            .field("item_id", &self.item_id)
            .field("role", &self.role)
            .field("content_digest", &Digest32::of_bytes(&self.content))
            .field("content_bytes", &self.content.len())
            .finish()
    }
}
''',
    )
    replace_once(
        V2,
        '''#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SerializedContextV2 {
    receipt: ContextSerializationReceiptV2,
    payload: Vec<u8>,
}
''',
        '''#[derive(Clone, Eq, PartialEq)]
pub struct SerializedContextV2 {
    receipt: ContextSerializationReceiptV2,
    payload: Vec<u8>,
}

impl fmt::Debug for SerializedContextV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("SerializedContextV2")
            .field("receipt", &self.receipt)
            .field("payload_digest", &Digest32::of_bytes(&self.payload))
            .field("payload_bytes", &self.payload.len())
            .finish()
    }
}
''',
    )
    replace_once(
        PROVIDER_BOUND,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct CanonicalContextPayloadV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct CanonicalContextPayloadV2",
    )
    replace_once(
        PROVIDER_BOUND,
        '''impl CanonicalContextPayloadV2 {
''',
        '''impl fmt::Debug for CanonicalContextPayloadV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CanonicalContextPayloadV2")
            .field("payload_digest", &self.coverage.payload_digest)
            .field("payload_bytes", &self.payload.len())
            .field("segment_count", &self.coverage.segments.len())
            .finish()
    }
}

impl CanonicalContextPayloadV2 {
''',
    )
    replace_once(
        PROVIDER_BOUND,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct CanonicalSerializedContextProofV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct CanonicalSerializedContextProofV2",
    )
    replace_once(
        PROVIDER_BOUND,
        '''impl CanonicalSerializedContextProofV2 {
''',
        '''impl fmt::Debug for CanonicalSerializedContextProofV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CanonicalSerializedContextProofV2")
            .field(
                "serialization_receipt_digest",
                &self.serialized_context.receipt().receipt_digest(),
            )
            .field("canonical_payload", &self.canonical_payload)
            .field("proof_digest", &self.proof_digest)
            .finish()
    }
}

impl CanonicalSerializedContextProofV2 {
''',
    )
    replace_once(
        PROVIDER_BOUND,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct VerifiedProviderRequestV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct VerifiedProviderRequestV2",
    )
    replace_once(
        PROVIDER_BOUND,
        '''impl VerifiedProviderRequestV2 {
''',
        '''impl fmt::Debug for VerifiedProviderRequestV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("VerifiedProviderRequestV2")
            .field("request_digest", &self.request_digest)
            .field("request_bytes", &self.bytes.len())
            .field(
                "canonical_context_payload_digest",
                &self.canonical_context_payload_digest,
            )
            .field("framing_policy_digest", &self.framing_policy_digest)
            .field("segment_count", &self.segments.len())
            .field("coverage_digest", &self.coverage_digest)
            .finish()
    }
}

impl VerifiedProviderRequestV2 {
''',
    )
    replace_once(
        PROMPT_BOUND,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ProviderRequestMaterializationV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct ProviderRequestMaterializationV2",
    )
    replace_once(
        PROMPT_BOUND,
        '''/// Qualified provider request constructor.
''',
        '''impl fmt::Debug for ProviderRequestMaterializationV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProviderRequestMaterializationV2")
            .field("exact_request_digest", &Digest32::of_bytes(&self.exact_request_bytes))
            .field("exact_request_bytes", &self.exact_request_bytes.len())
            .field("segment_count", &self.segments.len())
            .field("wire_semantic_digest", &self.wire_semantic_digest)
            .finish()
    }
}

/// Qualified provider request constructor.
''',
    )
    replace_once(
        PROMPT_BOUND,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PreparedProviderBoundPromptV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct PreparedProviderBoundPromptV2",
    )
    replace_once(
        PROMPT_BOUND,
        '''impl PreparedProviderBoundPromptV2 {
''',
        '''impl fmt::Debug for PreparedProviderBoundPromptV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedProviderBoundPromptV2")
            .field("realization_count", &self.realizations.len())
            .field("canonical_serialization", &self.canonical_serialization)
            .field("attachment_digest", &self.attachment.attachment_digest())
            .field("snapshot_successor_digest", &self.snapshot_successor.chain_digest())
            .field("preparation_digest", &self.preparation.preparation_digest())
            .field("provider_request", &self.provider_request)
            .field(
                "tokenizer_attestation_digest",
                &self.final_tokenization.attestation_digest(),
            )
            .field("bundle_digest", &self.bundle_digest)
            .finish()
    }
}

impl PreparedProviderBoundPromptV2 {
''',
    )
    replace_once(
        PROMPT_DELIVERY,
        "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct PromptRegistryCompiledContextV2",
        "#[derive(Clone, Eq, PartialEq)]\npub struct PromptRegistryCompiledContextV2",
    )
    replace_once(
        PROMPT_DELIVERY,
        '''impl PromptRegistryCompiledContextV2 {
''',
        '''impl fmt::Debug for PromptRegistryCompiledContextV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptRegistryCompiledContextV2")
            .field(
                "compilation_id",
                self.compiled.receipt().compilation_id(),
            )
            .field("selected_delivery_count", &self.selected_deliveries.len())
            .field("serialized_payload_digest", &Digest32::of_bytes(&self.serialized_payload))
            .field("serialized_payload_bytes", &self.serialized_payload.len())
            .field("delivery_set_digest", &self.delivery_set_digest)
            .finish()
    }
}

impl PromptRegistryCompiledContextV2 {
''',
    )


def main() -> int:
    patch_runtime()
    patch_runtime_tests()
    patch_redacted_debug()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
