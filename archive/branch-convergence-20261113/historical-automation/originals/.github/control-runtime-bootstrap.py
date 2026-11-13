#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    content = read(path)
    observed = content.count(old)
    if observed != count:
        raise SystemExit(f"{path}: expected {count} occurrences, found {observed}: {old[:80]!r}")
    write(path, content.replace(old, new, count))


def append_once(path: str, marker: str, content: str) -> None:
    current = read(path)
    if marker in current:
        return
    write(path, current + content)


def restore(ref: str, path: str) -> None:
    content = subprocess.check_output(
        ["git", "show", f"{ref}:{path}"], cwd=ROOT, text=True
    )
    write(path, content)


subprocess.run(
    [
        "git",
        "fetch",
        "origin",
        "pull/957/head:refs/remotes/origin/control-runtime-pr957",
    ],
    cwd=ROOT,
    check=True,
)
restore("origin/control-runtime-pr957", "codex-rs/hepta-control-plane/src/planner_store.rs")
restore("origin/control-runtime-pr957", "codex-rs/hepta-control-plane/src/planner_store_tests.rs")

# Exact resource-profile binding and monotonic lower-bound validation.
replace(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "    InvalidResourceReservation(String),\n    MissingResourceAxis { candidate: String, axis: String },",
    "    InvalidResourceReservation(String),\n    ResourceProfileMismatch,\n    MissingResourceAxis { candidate: String, axis: String },",
)
replace(
    "codex-rs/hepta-control-plane/src/planner.rs",
    '''            Self::InvalidResourceReservation(axis) => {\n                write!(\n                    formatter,\n                    "invalid essential resource reservation for {axis}"\n                )\n            }\n            Self::MissingResourceAxis { candidate, axis } => {''',
    '''            Self::InvalidResourceReservation(axis) => {\n                write!(\n                    formatter,\n                    "invalid essential resource reservation for {axis}"\n                )\n            }\n            Self::ResourceProfileMismatch => {\n                formatter.write_str("resource profile digest does not bind exact reservations")\n            }\n            Self::MissingResourceAxis { candidate, axis } => {''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "impl StdError for PlannerError {}\n\npub fn collect_snapshot(",
    '''impl StdError for PlannerError {}\n\n/// Canonical identity of the exact bounded resource endowment and essential\n/// floors used by one planning request. Callers may name a profile elsewhere,\n/// but the planner accepts only this content-derived digest.\npub fn canonical_resource_profile_digest(\n    reservations: &[ResourceReservationV1],\n) -> Result<Digest32, PlannerError> {\n    if reservations.is_empty() || reservations.len() > MAX_RESOURCE_RESERVATIONS {\n        return Err(PlannerError::LimitExceeded("resource reservations"));\n    }\n    let mut normalized = reservations.to_vec();\n    normalized.sort_by(|left, right| left.axis.cmp(&right.axis));\n    validate_reservations(&normalized)?;\n    let mut bytes = Vec::new();\n    bytes.extend_from_slice(b"hepta.control.resource-profile.v1");\n    push_len(&mut bytes, normalized.len());\n    for reservation in &normalized {\n        push_id(&mut bytes, &reservation.axis);\n        bytes.extend_from_slice(&reservation.endowment.raw().to_be_bytes());\n        bytes.extend_from_slice(&reservation.essential_floor.raw().to_be_bytes());\n    }\n    Ok(Digest32::of_bytes(&bytes))\n}\n\npub fn collect_snapshot(''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner.rs",
    '''    request\n        .resource_reservations\n        .sort_by(|left, right| left.axis.cmp(&right.axis));\n    validate_reservations(&request.resource_reservations)?;\n\n    let source_candidate_set_digest = digest_candidates(&request.candidates);''',
    '''    request\n        .resource_reservations\n        .sort_by(|left, right| left.axis.cmp(&right.axis));\n    validate_reservations(&request.resource_reservations)?;\n    if canonical_resource_profile_digest(&request.resource_reservations)?\n        != request.resource_profile_digest\n    {\n        return Err(PlannerError::ResourceProfileMismatch);\n    }\n\n    let source_candidate_set_digest = digest_candidates(&request.candidates);''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner.rs",
    '''    if now_micros >= snapshot.expires_at_micros {\n        return Err(PlannerError::SnapshotExpired);\n    }\n    if !snapshot.missing_owner_ids.is_empty()''',
    '''    if now_micros < snapshot.collected_at_micros {\n        return Err(PlannerError::InvalidTime(\n            "current time before snapshot collection",\n        ));\n    }\n    if now_micros >= snapshot.expires_at_micros {\n        return Err(PlannerError::SnapshotExpired);\n    }\n    if !snapshot.missing_owner_ids.is_empty()''',
)

# One semantic state machine for live appends and reopen.
replace(
    "codex-rs/hepta-control-plane/src/planner_journal.rs",
    '''        if let Some((existing_kind, existing_payload)) = self.identities.get(&identity_digest) {\n            if *existing_kind == kind && *existing_payload == payload_digest {\n                return self\n                    .entries\n                    .iter()\n                    .find(|entry| entry.identity_digest == identity_digest)\n                    .cloned()\n                    .ok_or(PlannerJournalError::CorruptEntryDigest);\n            }\n            return Err(PlannerJournalError::IdentityConflict);\n        }\n        if self.entries.len() >= MAX_RECORDS {''',
    '''        if let Some((existing_kind, existing_payload)) = self.identities.get(&identity_digest) {\n            if *existing_kind == kind && *existing_payload == payload_digest {\n                return self\n                    .entries\n                    .iter()\n                    .find(|entry| entry.identity_digest == identity_digest)\n                    .cloned()\n                    .ok_or(PlannerJournalError::CorruptEntryDigest);\n            }\n            return Err(PlannerJournalError::IdentityConflict);\n        }\n        self.validate_semantic_transition(kind, payload_digest)?;\n        if self.entries.len() >= MAX_RECORDS {''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner_journal.rs",
    '''            if journal.identities.contains_key(&identity_digest) {\n                return Err(PlannerJournalError::DuplicateSerializedIdentity);\n            }\n            journal\n                .identities''',
    '''            if journal.identities.contains_key(&identity_digest) {\n                return Err(PlannerJournalError::DuplicateSerializedIdentity);\n            }\n            journal.validate_semantic_transition(kind, payload_digest)?;\n            journal\n                .identities''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner_journal.rs",
    '''    fn revoked_digests(&self) -> BTreeSet<Digest32> {\n        self.entries\n            .iter()\n            .filter(|entry| entry.kind == PlannerJournalKindV1::Revocation)\n            .map(|entry| entry.payload_digest)\n            .collect()\n    }\n}''',
    '''    #[must_use]\n    pub fn revoked_decision_digests(&self) -> Vec<Digest32> {\n        self.revoked_digests().into_iter().collect()\n    }\n\n    fn validate_semantic_transition(\n        &self,\n        kind: PlannerJournalKindV1,\n        payload_digest: Digest32,\n    ) -> Result<(), PlannerJournalError> {\n        match kind {\n            PlannerJournalKindV1::SelectedPlan => {\n                if !self.entries.iter().any(|entry| {\n                    entry.kind == PlannerJournalKindV1::Decision\n                        && entry.payload_digest == payload_digest\n                }) {\n                    return Err(PlannerJournalError::DecisionNotRecorded);\n                }\n                if self.revoked_digests().contains(&payload_digest) {\n                    return Err(PlannerJournalError::RevokedPlan);\n                }\n            }\n            PlannerJournalKindV1::Revocation => {\n                if !self.entries.iter().any(|entry| {\n                    entry.kind == PlannerJournalKindV1::Decision\n                        && entry.payload_digest == payload_digest\n                }) {\n                    return Err(PlannerJournalError::DecisionNotRecorded);\n                }\n            }\n            PlannerJournalKindV1::Snapshot | PlannerJournalKindV1::Decision => {}\n        }\n        Ok(())\n    }\n\n    fn revoked_digests(&self) -> BTreeSet<Digest32> {\n        self.entries\n            .iter()\n            .filter(|entry| entry.kind == PlannerJournalKindV1::Revocation)\n            .map(|entry| entry.payload_digest)\n            .collect()\n    }\n}''',
)

# Public exports and durable-store module.
replace(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "mod planner_ndu;\n",
    "mod planner_ndu;\nmod planner_store;\n",
)
replace(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "pub use planner::bind_ndu_plan_evaluation_v1;\n",
    "pub use planner::bind_ndu_plan_evaluation_v1;\npub use planner::canonical_resource_profile_digest;\n",
)
replace(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\n",
    "pub use planner_ndu::evaluate_prepared_plan_with_ndu;\npub use planner_store::PlannerJournalStoreV1;\npub use planner_store::PlannerStoreError;\n",
)
replace(
    "codex-rs/hepta-control-plane/Cargo.toml",
    'codex-hepta-types = { path = "../hepta-types" }\n',
    'codex-hepta-types = { path = "../hepta-types" }\nrustix = { workspace = true, features = ["fs", "process"] }\n',
)

# Planner fixtures now derive the exact resource identity.
replace(
    "codex-rs/hepta-control-plane/src/planner_tests.rs",
    "use super::bind_ndu_plan_evaluation_v1;\nuse super::collect_snapshot;",
    "use super::bind_ndu_plan_evaluation_v1;\nuse super::canonical_resource_profile_digest;\nuse super::collect_snapshot;",
)
replace(
    "codex-rs/hepta-control-plane/src/planner_tests.rs",
    '''fn planning_request(work_resource: i64) -> PlanningRequestV1 {\n    PlanningRequestV1 {\n        plan_id: id("plan-run-1"),\n        now_micros: 1_000,\n        deadline_micros: 1_900,\n        evaluation_policy_digest: digest("policy"),\n        resource_profile_digest: digest("resource-profile"),\n        candidates: vec![candidate("abstain", 0), candidate("work", work_resource)],\n        resource_reservations: vec![ResourceReservationV1 {\n            axis: id("compute"),\n            endowment: q32(10),\n            essential_floor: FixedQ32::ZERO,\n        }],\n    }\n}''',
    '''fn planning_request(work_resource: i64) -> PlanningRequestV1 {\n    let resource_reservations = vec![ResourceReservationV1 {\n        axis: id("compute"),\n        endowment: q32(10),\n        essential_floor: FixedQ32::ZERO,\n    }];\n    PlanningRequestV1 {\n        plan_id: id("plan-run-1"),\n        now_micros: 1_000,\n        deadline_micros: 1_900,\n        evaluation_policy_digest: digest("policy"),\n        resource_profile_digest: must(canonical_resource_profile_digest(&resource_reservations)),\n        candidates: vec![candidate("abstain", 0), candidate("work", work_resource)],\n        resource_reservations,\n    }\n}''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner_tests.rs",
    '''    let mut request = planning_request(9);\n    request.resource_reservations[0].essential_floor = q32(2);\n    let prepared = must(prepare_plan(&snapshot, request));''',
    '''    let mut request = planning_request(9);\n    request.resource_reservations[0].essential_floor = q32(2);\n    request.resource_profile_digest =\n        must(canonical_resource_profile_digest(&request.resource_reservations));\n    let prepared = must(prepare_plan(&snapshot, request));''',
)
append_once(
    "codex-rs/hepta-control-plane/src/planner_tests.rs",
    "fn exact_resource_reservations_are_bound_even_when_feasibility_is_unchanged",
    '''\n\n#[test]\nfn exact_resource_reservations_are_bound_even_when_feasibility_is_unchanged() {\n    let snapshot = must(collect_snapshot(\n        snapshot_request(),\n        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],\n    ));\n    let original = must(prepare_plan(&snapshot, planning_request(1)));\n\n    let mut changed_request = planning_request(1);\n    changed_request.resource_reservations[0].endowment = q32(100);\n    changed_request.resource_reservations[0].essential_floor = q32(20);\n    changed_request.resource_profile_digest = must(canonical_resource_profile_digest(\n        &changed_request.resource_reservations,\n    ));\n    let changed = must(prepare_plan(&snapshot, changed_request));\n\n    assert_eq!(original.feasible_candidates(), changed.feasible_candidates());\n    assert_ne!(original.resource_profile_digest(), changed.resource_profile_digest());\n    assert_ne!(original.prepared_digest(), changed.prepared_digest());\n}\n\n#[test]\nfn resource_profile_digest_drift_is_rejected() {\n    let snapshot = must(collect_snapshot(\n        snapshot_request(),\n        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],\n    ));\n    let mut request = planning_request(1);\n    request.resource_reservations[0].essential_floor = q32(1);\n\n    assert_eq!(\n        must_err(prepare_plan(&snapshot, request)),\n        PlannerError::ResourceProfileMismatch\n    );\n}\n\n#[test]\nfn planning_rejects_time_before_snapshot_collection() {\n    let snapshot = must(collect_snapshot(\n        snapshot_request(),\n        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],\n    ));\n    let mut request = planning_request(1);\n    request.now_micros = 999;\n\n    assert_eq!(\n        must_err(prepare_plan(&snapshot, request)),\n        PlannerError::InvalidTime("current time before snapshot collection")\n    );\n}\n''',
)

replace(
    "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
    "use crate::bind_ndu_plan_evaluation_v1;\nuse crate::collect_snapshot;",
    "use crate::bind_ndu_plan_evaluation_v1;\nuse crate::canonical_resource_profile_digest;\nuse crate::collect_snapshot;",
)
replace(
    "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
    '''fn must<T, E: Debug>(result: Result<T, E>) -> T {\n    match result {\n        Ok(value) => value,\n        Err(error) => panic!("unexpected error: {error:?}"),\n    }\n}\n''',
    '''fn must<T, E: Debug>(result: Result<T, E>) -> T {\n    match result {\n        Ok(value) => value,\n        Err(error) => panic!("unexpected error: {error:?}"),\n    }\n}\n\nfn must_err<T: Debug, E>(result: Result<T, E>) -> E {\n    match result {\n        Err(error) => error,\n        Ok(value) => panic!("expected error, received value: {value:?}"),\n    }\n}\n''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
    '''fn planning_request() -> PlanningRequestV1 {\n    PlanningRequestV1 {\n        plan_id: id("plan-run"),\n        now_micros: 100,\n        deadline_micros: 400,\n        evaluation_policy_digest: digest("policy"),\n        resource_profile_digest: digest("resource-profile"),\n        candidates: vec![candidate("abstain"), candidate("work")],\n        resource_reservations: vec![ResourceReservationV1 {\n            axis: id("compute"),\n            endowment: q32(10),\n            essential_floor: FixedQ32::ZERO,\n        }],\n    }\n}''',
    '''fn planning_request() -> PlanningRequestV1 {\n    let resource_reservations = vec![ResourceReservationV1 {\n        axis: id("compute"),\n        endowment: q32(10),\n        essential_floor: FixedQ32::ZERO,\n    }];\n    PlanningRequestV1 {\n        plan_id: id("plan-run"),\n        now_micros: 100,\n        deadline_micros: 400,\n        evaluation_policy_digest: digest("policy"),\n        resource_profile_digest: must(canonical_resource_profile_digest(&resource_reservations)),\n        candidates: vec![candidate("abstain"), candidate("work")],\n        resource_reservations,\n    }\n}''',
)
append_once(
    "codex-rs/hepta-control-plane/src/planner_journal_tests.rs",
    "fn raw_append_rejects_selection_without_recorded_decision",
    '''\n\n#[test]\nfn raw_append_rejects_selection_without_recorded_decision() {\n    let mut journal = PlannerJournalV1::new();\n    assert_eq!(\n        must_err(journal.append(\n            PlannerJournalKindV1::SelectedPlan,\n            digest("selection-operation"),\n            digest("unrecorded-decision"),\n        )),\n        PlannerJournalError::DecisionNotRecorded\n    );\n}\n\n#[test]\nfn reopen_rejects_hash_valid_selection_without_recorded_decision() {\n    let identity = digest("selection-operation");\n    let payload = digest("unrecorded-decision");\n    let predecessor = Digest32::ZERO;\n    let entry_digest = super::digest_entry(\n        1,\n        PlannerJournalKindV1::SelectedPlan,\n        identity,\n        payload,\n        predecessor,\n    );\n    let mut bytes = Vec::new();\n    bytes.extend_from_slice(super::MAGIC);\n    bytes.extend_from_slice(&1_u32.to_be_bytes());\n    bytes.extend_from_slice(&1_u64.to_be_bytes());\n    bytes.push(PlannerJournalKindV1::SelectedPlan.tag());\n    bytes.extend_from_slice(identity.as_array());\n    bytes.extend_from_slice(payload.as_array());\n    bytes.extend_from_slice(predecessor.as_array());\n    bytes.extend_from_slice(entry_digest.as_array());\n\n    assert_eq!(\n        must_err(PlannerJournalV1::reopen(&bytes)),\n        PlannerJournalError::DecisionNotRecorded\n    );\n}\n''',
)

replace(
    "codex-rs/hepta-control-plane/src/planner_ndu_tests.rs",
    "use crate::collect_snapshot;\n",
    "use crate::canonical_resource_profile_digest;\nuse crate::collect_snapshot;\n",
)
replace(
    "codex-rs/hepta-control-plane/src/planner_ndu_tests.rs",
    '''    let prepared = prepare_plan(\n        &snapshot,\n        PlanningRequestV1 {\n            plan_id: id("read-plan"),\n            now_micros: 100,\n            deadline_micros: 190,\n            evaluation_policy_digest: canonical_ndu_planning_policy_digest(&input)\n                .expect("policy binding"),\n            resource_profile_digest: digest("bounded-context-read"),\n            candidates: ["abstain", "read-context"]\n                .into_iter()\n                .map(|name| PlanCandidateV1 {\n                    candidate_id: id(name),\n                    operation_id: id(&format!("operation-{name}")),\n                    plan_digest: digest(name),\n                    required_owner_ids: vec![id("state-reader")],\n                    final_payload_digests: vec![],\n                    resource_costs: vec![PlannerAxisValueV1 {\n                        axis: id("context-read"),\n                        value: if name == "abstain" {\n                            FixedQ32::ZERO\n                        } else {\n                            FixedQ32::ONE\n                        },\n                    }],\n                })\n                .collect(),\n            resource_reservations: vec![ResourceReservationV1 {\n                axis: id("context-read"),\n                endowment: FixedQ32::ONE,\n                essential_floor: FixedQ32::ZERO,\n            }],\n        },\n    )\n    .expect("prepared plan");''',
    '''    let resource_reservations = vec![ResourceReservationV1 {\n        axis: id("context-read"),\n        endowment: FixedQ32::ONE,\n        essential_floor: FixedQ32::ZERO,\n    }];\n    let prepared = prepare_plan(\n        &snapshot,\n        PlanningRequestV1 {\n            plan_id: id("read-plan"),\n            now_micros: 100,\n            deadline_micros: 190,\n            evaluation_policy_digest: canonical_ndu_planning_policy_digest(&input)\n                .expect("policy binding"),\n            resource_profile_digest: canonical_resource_profile_digest(&resource_reservations)\n                .expect("resource profile binding"),\n            candidates: ["abstain", "read-context"]\n                .into_iter()\n                .map(|name| PlanCandidateV1 {\n                    candidate_id: id(name),\n                    operation_id: id(&format!("operation-{name}")),\n                    plan_digest: digest(name),\n                    required_owner_ids: vec![id("state-reader")],\n                    final_payload_digests: vec![],\n                    resource_costs: vec![PlannerAxisValueV1 {\n                        axis: id("context-read"),\n                        value: if name == "abstain" {\n                            FixedQ32::ZERO\n                        } else {\n                            FixedQ32::ONE\n                        },\n                    }],\n                })\n                .collect(),\n            resource_reservations,\n        },\n    )\n    .expect("prepared plan");''',
)
replace(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "use crate::canonical_ndu_planning_policy_digest;\n",
    "use crate::canonical_ndu_planning_policy_digest;\nuse crate::canonical_resource_profile_digest;\n",
)
replace(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    '''    let prepared = prepare_plan(\n        &snapshot,\n        PlanningRequestV1 {\n            plan_id: id("context-delivery")?,\n            now_micros: observed.observed_at_micros,\n            deadline_micros: observed.expires_at_micros,\n            evaluation_policy_digest: configuration_digest,\n            resource_profile_digest: objective_digest,\n            candidates,\n            resource_reservations: vec![ResourceReservationV1 {\n                axis: bytes_axis.clone(),\n                endowment: budget,\n                essential_floor: FixedQ32::ZERO,\n            }],\n        },\n    )\n    .map_err(E::Planner)?;''',
    '''    let resource_reservations = vec![ResourceReservationV1 {\n        axis: bytes_axis.clone(),\n        endowment: budget,\n        essential_floor: FixedQ32::ZERO,\n    }];\n    let resource_profile_digest =\n        canonical_resource_profile_digest(&resource_reservations).map_err(E::Planner)?;\n    let prepared = prepare_plan(\n        &snapshot,\n        PlanningRequestV1 {\n            plan_id: id("context-delivery")?,\n            now_micros: observed.observed_at_micros,\n            deadline_micros: observed.expires_at_micros,\n            evaluation_policy_digest: configuration_digest,\n            resource_profile_digest,\n            candidates,\n            resource_reservations,\n        },\n    )\n    .map_err(E::Planner)?;''',
)

# Agentd planner deadlines use a process-generation monotonic domain.
replace(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "use std::collections::BTreeMap;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;",
    "use std::collections::BTreeMap;\nuse std::sync::OnceLock;\nuse std::time::Instant;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;",
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    '''    let now_micros = u64::try_from(\n        SystemTime::now()\n            .duration_since(UNIX_EPOCH)\n            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?\n            .as_micros(),\n    )\n    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;''',
    "    let now_micros = planner_monotonic_micros()?;",
)
replace(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "fn now_seconds() -> Result<i64, CognitiveStoreError> {",
    '''fn planner_monotonic_micros() -> Result<u64, CognitiveStoreError> {\n    static ORIGIN: OnceLock<Instant> = OnceLock::new();\n    let micros = ORIGIN.get_or_init(Instant::now).elapsed().as_micros();\n    u64::try_from(micros).map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))\n}\n\nfn now_seconds() -> Result<i64, CognitiveStoreError> {''',
)
append_once(
    "codex-rs/hepta-agentd/src/cognitive_context_tests.rs",
    "fn planner_clock_is_monotonic_within_the_host_generation",
    '''\n\n#[test]\nfn planner_clock_is_monotonic_within_the_host_generation() {\n    let first = super::planner_monotonic_micros().unwrap();\n    let second = super::planner_monotonic_micros().unwrap();\n    assert!(second >= first);\n}\n''',
)

# Strict lint dependency repairs.
replace(
    "codex-rs/hepta-ndu/src/lib.rs",
    "pub use evaluator::evaluate_candidates;",
    "#[allow(deprecated)]\npub use evaluator::evaluate_candidates;",
)
replace(
    "codex-rs/hepta-ndu/src/preference_tests.rs",
    "fn iteration_exhaustion_is_unavailable()",
    "fn iteration_bound_exhaustion_is_unavailable()",
)

write(
    "codex-rs/hepta-operations/src/sqlite.rs",
    '''use std::path::Path;\n\nuse codex_state::SqliteConfig;\nuse codex_utils_absolute_path::AbsolutePathBuf;\nuse sqlx::SqlitePool;\n\nuse crate::DurableOperationError;\n\npub(crate) async fn open_durable_pool(\n    path: &Path,\n) -> Result<SqlitePool, DurableOperationError> {\n    let parent = path\n        .parent()\n        .filter(|parent| !parent.as_os_str().is_empty())\n        .unwrap_or_else(|| Path::new("."));\n    std::fs::create_dir_all(parent)\n        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;\n    let canonical_parent = std::fs::canonicalize(parent)\n        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;\n    let file_name = path\n        .file_name()\n        .ok_or_else(|| DurableOperationError::Unavailable("SQLite path has no file name".into()))?;\n    let absolute_path = canonical_parent.join(file_name);\n    let sqlite_home = AbsolutePathBuf::try_from(canonical_parent)\n        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;\n    SqliteConfig::from_sqlite_home(sqlite_home)\n        .open_durable_evidence_pool(&absolute_path)\n        .await\n        .map_err(|error| DurableOperationError::Unavailable(error.to_string()))\n}\n''',
)
replace(
    "codex-rs/hepta-operations/src/lib.rs",
    "mod outbox;\n",
    "mod outbox;\nmod sqlite;\n",
)
replace(
    "codex-rs/hepta-operations/Cargo.toml",
    "codex-hepta-types = { workspace = true }\n",
    "codex-hepta-types = { workspace = true }\ncodex-state = { workspace = true }\ncodex-utils-absolute-path = { workspace = true }\n",
)
for path in [
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    "codex-rs/hepta-operations/src/durable_store.rs",
]:
    replace(path, "use std::time::Duration;\n", "")
    for import_line in [
        "use sqlx::sqlite::SqliteConnectOptions;\n",
        "use sqlx::sqlite::SqliteJournalMode;\n",
        "use sqlx::sqlite::SqlitePoolOptions;\n",
        "use sqlx::sqlite::SqliteSynchronous;\n",
    ]:
        replace(path, import_line, "")

replace(
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    '''        if let Some(parent) = path.parent() {\n            std::fs::create_dir_all(parent)\n                .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;\n        }\n        let options = SqliteConnectOptions::new()\n            .filename(path)\n            .create_if_missing(true)\n            .journal_mode(SqliteJournalMode::Wal)\n            .synchronous(SqliteSynchronous::Full)\n            .foreign_keys(true)\n            .busy_timeout(Duration::from_secs(5));\n        let pool = SqlitePoolOptions::new()\n            .max_connections(4)\n            .connect_with(options)\n            .await\n            .map_err(sqlx_error)?;''',
    "        let pool = crate::sqlite::open_durable_pool(path).await?;",
)
replace(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''        if let Some(parent) = path.parent() {\n            std::fs::create_dir_all(parent)\n                .map_err(|error| DurableOperationError::Unavailable(error.to_string()))?;\n        }\n        let options = SqliteConnectOptions::new()\n            .filename(path)\n            .create_if_missing(true)\n            .journal_mode(SqliteJournalMode::Wal)\n            .synchronous(SqliteSynchronous::Full)\n            .foreign_keys(true)\n            .busy_timeout(Duration::from_secs(5));\n        let pool = SqlitePoolOptions::new()\n            .max_connections(4)\n            .connect_with(options)\n            .await\n            .map_err(sqlx_error)?;''',
    "        let pool = crate::sqlite::open_durable_pool(path).await?;",
)
replace(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''        if let Some(status) = load_outbox_tx(\n            &mut tx,\n            &operation.intent.destination,\n            scope_id,\n            operation_id,\n        )\n        .await?\n        {\n            if status.state != DurableOutboxState::Acknowledged {''',
    '''        if let Some(status) = load_outbox_tx(\n            &mut tx,\n            &operation.intent.destination,\n            scope_id,\n            operation_id,\n        )\n        .await?\n            && status.state != DurableOutboxState::Acknowledged\n        {''',
)
replace(
    "codex-rs/hepta-operations/src/durable_store.rs",
    '''                .await\n                .map_err(sqlx_error)?;\n            }\n        }\n        let operation = load_operation_tx''',
    '''                .await\n                .map_err(sqlx_error)?;\n        }\n        let operation = load_operation_tx''',
)

# Integration-test helpers must not use expect under strict all-target lint.
path = "codex-rs/hepta-control-plane/tests/runtime_retirement_dependencies.rs"
content = read(path)
content = content.replace(
    "use std::collections::BTreeSet;\n",
    "use std::collections::BTreeSet;\nuse std::fmt::Debug;\n",
    1,
)
content = content.replace(
    '''fn id(value: &str) -> StableId {\n    StableId::new(value).expect("valid identity")\n}\n\nfn generation() -> Generation {\n    Generation::new(1).expect("valid generation")\n}\n''',
    '''fn must<T, E: Debug>(result: Result<T, E>) -> T {\n    match result {\n        Ok(value) => value,\n        Err(error) => panic!("unexpected error: {error:?}"),\n    }\n}\n\nfn id(value: &str) -> StableId {\n    must(StableId::new(value))\n}\n\nfn generation() -> Generation {\n    must(Generation::new(1))\n}\n''',
    1,
)
content = content.replace('registry.register_candidate(value).expect("register");', 'must(registry.register_candidate(value));')
content = content.replace('registry.enter_shadow(&module, epoch).expect("shadow");', 'must(registry.enter_shadow(&module, epoch));')
content = content.replace('registry.enter_canary(&module, epoch).expect("canary");', 'must(registry.enter_canary(&module, epoch));')
content = content.replace(
    '''    registry\n        .promote_after_handoff(\n            &module,\n            epoch,\n            RuntimeModulePromotionWitnessV1 {\n                selection_digest: Digest32::of_bytes(b"fixture-selection"),\n                canary_digest: Digest32::of_bytes(b"fixture-canary"),\n                handoff_digest: Digest32::ZERO,\n            },\n        )\n        .expect("select stateless fixture");''',
    '''    must(registry.promote_after_handoff(\n        &module,\n        epoch,\n        RuntimeModulePromotionWitnessV1 {\n            selection_digest: Digest32::of_bytes(b"fixture-selection"),\n            canary_digest: Digest32::of_bytes(b"fixture-canary"),\n            handoff_digest: Digest32::ZERO,\n        },\n    ));''',
    1,
)
write(path, content)

# Explicit durability regressions for torn successor and equal-state retry.
append_once(
    "codex-rs/hepta-control-plane/src/planner_store_tests.rs",
    "fn torn_next_file_does_not_replace_last_synced_state",
    '''\n\n#[test]\nfn torn_next_file_does_not_replace_last_synced_state() {\n    let temporary = tempfile::tempdir().expect("tempdir");\n    let root = temporary.path().join("planner");\n    let (mut store, _) = PlannerJournalStoreV1::open(&root, &[]).expect("open store");\n    let journal = selected_journal();\n    store.persist(&journal).expect("persist selected state");\n    drop(store);\n\n    std::fs::write(root.join(super::NEXT_FILE), b"torn-successor").expect("write torn next");\n    let (_store, reopened) = PlannerJournalStoreV1::open(&root, &[]).expect("reopen state");\n    assert_eq!(reopened.entries(), journal.entries());\n}\n\n#[test]\nfn identical_persist_is_idempotent_and_does_not_rewrite_history() {\n    let temporary = tempfile::tempdir().expect("tempdir");\n    let root = temporary.path().join("planner");\n    let (mut store, _) = PlannerJournalStoreV1::open(&root, &[]).expect("open store");\n    let journal = selected_journal();\n    store.persist(&journal).expect("first persist");\n    let before = std::fs::read(root.join(super::STATE_FILE)).expect("read first state");\n    store.persist(&journal).expect("idempotent persist");\n    let after = std::fs::read(root.join(super::STATE_FILE)).expect("read second state");\n    assert_eq!(after, before);\n}\n''',
)

subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
