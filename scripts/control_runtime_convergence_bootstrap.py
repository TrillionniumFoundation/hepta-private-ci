#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


# Close the exact-head NDU regression without weakening the assertion.  The
# termination maximum is defined over emitted solver iterations; the initial
# predecessor residual is not an iteration receipt.
replace_once(
    "codex-rs/hepta-ndu/src/preference.rs",
    "    let mut maximum_residual_raw = initial_residual_raw;\n",
    "    let mut maximum_residual_raw = 0_i64;\n",
)

# Reject owner-snapshot widening and duplicate effect payloads instead of
# silently canonicalizing security-relevant input.
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "    DuplicateOwner(String),\n    DuplicateCandidate(String),\n    DuplicateResourceAxis(String),\n",
    "    DuplicateOwner(String),\n    UnexpectedOwner(String),\n    DuplicateCandidate(String),\n    DuplicatePayload(String),\n    DuplicateResourceAxis(String),\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "            Self::DuplicateOwner(owner) => write!(formatter, \"duplicate owner summary: {owner}\"),\n            Self::DuplicateCandidate(candidate) => {\n",
    "            Self::DuplicateOwner(owner) => write!(formatter, \"duplicate owner summary: {owner}\"),\n            Self::UnexpectedOwner(owner) => {\n                write!(formatter, \"owner summary is outside the required owner set: {owner}\")\n            }\n            Self::DuplicateCandidate(candidate) => {\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "            Self::DuplicateResourceAxis(axis) => {\n",
    "            Self::DuplicatePayload(candidate) => {\n                write!(formatter, \"candidate {candidate} repeats a final payload digest\")\n            }\n            Self::DuplicateResourceAxis(axis) => {\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "    let required_owner_set_digest = digest_owner_set(&request.required_owner_ids);\n    owner_summaries.sort_by(|left, right| left.owner_id.cmp(&right.owner_id));\n",
    "    let required_owner_set_digest = digest_owner_set(&request.required_owner_ids);\n    let required_owners: BTreeSet<_> = request.required_owner_ids.iter().cloned().collect();\n    if let Some(summary) = owner_summaries\n        .iter()\n        .find(|summary| !required_owners.contains(&summary.owner_id))\n    {\n        return Err(PlannerError::UnexpectedOwner(summary.owner_id.to_string()));\n    }\n    owner_summaries.sort_by(|left, right| left.owner_id.cmp(&right.owner_id));\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner.rs",
    "        candidate.final_payload_digests.sort();\n        candidate.final_payload_digests.dedup();\n        candidate.resource_costs.sort();\n",
    "        candidate.final_payload_digests.sort();\n        if candidate\n            .final_payload_digests\n            .windows(2)\n            .any(|window| window[0] == window[1])\n        {\n            return Err(PlannerError::DuplicatePayload(\n                candidate.candidate_id.to_string(),\n            ));\n        }\n        candidate.resource_costs.sort();\n",
)

planner_tests = read("codex-rs/hepta-control-plane/src/planner_tests.rs")
planner_tests += r'''

#[test]
fn extra_owner_summary_is_rejected_instead_of_poisoning_required_snapshot() {
    let mut extra = summary(OwnerReadinessV1::Unavailable, 1, 1_001);
    extra.owner_id = id("not-required");
    assert_eq!(
        must_err(collect_snapshot(
            snapshot_request(),
            vec![summary(OwnerReadinessV1::Ready, 950, 1_800), extra],
        )),
        PlannerError::UnexpectedOwner("not-required".to_string())
    );
}

#[test]
fn duplicate_final_payload_digest_is_rejected() {
    let snapshot = must(collect_snapshot(
        snapshot_request(),
        vec![summary(OwnerReadinessV1::Ready, 950, 1_800)],
    ));
    let mut request = planning_request(1);
    let duplicate = request.candidates[1].final_payload_digests[0];
    request.candidates[1].final_payload_digests.push(duplicate);
    assert_eq!(
        must_err(prepare_plan(&snapshot, request)),
        PlannerError::DuplicatePayload("work".to_string())
    );
}
'''
write("codex-rs/hepta-control-plane/src/planner_tests.rs", planner_tests)

# Replace scalar caller assertions with a canonical exact-record projection and
# bind request, retrieval and ranker identities into the planning objective.
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "pub struct ObservedContextV1<'a> {\n",
    "#[derive(Clone, Debug, Eq, PartialEq)]\npub struct ObservedContextRecordV1 {\n    pub record_id: StableId,\n    pub revision: Revision,\n    pub content_digest: Digest32,\n}\n\npub struct ObservedContextV1<'a> {\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "    pub read_digest: Digest32,\n    pub verified_item_count: u32,\n    pub encoded_context: &'a [u8],\n",
    "    pub read_digest: Digest32,\n    pub verified_records: Vec<ObservedContextRecordV1>,\n    pub request_digest: Digest32,\n    pub retrieval_profile_digest: Digest32,\n    pub ranker_policy_digest: Option<Digest32>,\n    pub encoded_context: &'a [u8],\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "    if observed.verified_item_count > 4\n        || observed.encoded_context.len() > 24 * 1024\n",
    "    if observed.verified_records.len() > 4\n        || observed.encoded_context.len() > 24 * 1024\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "    let id = |name: &str| StableId::new(name).map_err(|_| E::Planner(PlannerError::Arithmetic));\n",
    "    if observed.source_snapshot_digest.is_zero()\n        || observed.read_digest.is_zero()\n        || observed.request_digest.is_zero()\n        || observed.retrieval_profile_digest.is_zero()\n        || observed.ranker_policy_digest.is_some_and(Digest32::is_zero)\n        || observed\n            .verified_records\n            .iter()\n            .any(|record| record.content_digest.is_zero())\n    {\n        return Err(E::Planner(PlannerError::EmptyDigest(\"observed context binding\")));\n    }\n    let verified_item_count = u32::try_from(observed.verified_records.len())\n        .map_err(|_| E::Planner(PlannerError::Arithmetic))?;\n    let id = |name: &str| StableId::new(name).map_err(|_| E::Planner(PlannerError::Arithmetic));\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "    let mut objective = b\"hepta.control.deliver-verified-context.v1\\0\".to_vec();\n    objective.extend_from_slice(&observed.maximum_context_bytes.to_be_bytes());\n",
    "    let mut objective = b\"hepta.control.deliver-verified-context.v2\\0\".to_vec();\n    objective.extend_from_slice(&observed.maximum_context_bytes.to_be_bytes());\n    objective.extend_from_slice(observed.request_digest.as_array());\n    objective.extend_from_slice(observed.retrieval_profile_digest.as_array());\n    match observed.ranker_policy_digest {\n        Some(digest) => {\n            objective.push(1);\n            objective.extend_from_slice(digest.as_array());\n        }\n        None => objective.push(0),\n    }\n    objective.extend_from_slice(&verified_item_count.to_be_bytes());\n    for record in &observed.verified_records {\n        objective.extend_from_slice(&(record.record_id.as_str().len() as u64).to_be_bytes());\n        objective.extend_from_slice(record.record_id.as_str().as_bytes());\n        objective.extend_from_slice(&record.revision.get().to_be_bytes());\n        objective.extend_from_slice(record.content_digest.as_array());\n    }\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context.rs",
    "                        q32(observed.verified_item_count)\n",
    "                        q32(verified_item_count)\n",
)

# Update context tests for exact record projection and new request bindings.
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context_tests.rs",
    "        verified_item_count: 2,\n        encoded_context: b\"verified content\",\n",
    "        verified_records: vec![\n            ObservedContextRecordV1 {\n                record_id: StableId::new(\"memory-a\").expect(\"record id\"),\n                revision: Revision::new(3).expect(\"revision\"),\n                content_digest: Digest32::of_bytes(b\"memory-a-content\"),\n            },\n            ObservedContextRecordV1 {\n                record_id: StableId::new(\"memory-b\").expect(\"record id\"),\n                revision: Revision::new(5).expect(\"revision\"),\n                content_digest: Digest32::of_bytes(b\"memory-b-content\"),\n            },\n        ],\n        request_digest: Digest32::of_bytes(b\"request\"),\n        retrieval_profile_digest: Digest32::of_bytes(b\"retrieval-profile\"),\n        ranker_policy_digest: Some(Digest32::of_bytes(b\"ranker-policy\")),\n        encoded_context: b\"verified content\",\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context_tests.rs",
    "    empty.verified_item_count = 0;\n",
    "    empty.verified_records.clear();\n",
)
replace_once(
    "codex-rs/hepta-control-plane/src/planner_context_tests.rs",
    "    oversized.verified_item_count = 5;\n",
    "    oversized.verified_records.push(ObservedContextRecordV1 {\n        record_id: StableId::new(\"memory-c\").expect(\"record id\"),\n        revision: Revision::new(1).expect(\"revision\"),\n        content_digest: Digest32::of_bytes(b\"memory-c-content\"),\n    });\n    oversized.verified_records.push(ObservedContextRecordV1 {\n        record_id: StableId::new(\"memory-d\").expect(\"record id\"),\n        revision: Revision::new(1).expect(\"revision\"),\n        content_digest: Digest32::of_bytes(b\"memory-d-content\"),\n    });\n    oversized.verified_records.push(ObservedContextRecordV1 {\n        record_id: StableId::new(\"memory-e\").expect(\"record id\"),\n        revision: Revision::new(1).expect(\"revision\"),\n        content_digest: Digest32::of_bytes(b\"memory-e-content\"),\n    });\n",
)
planner_context_tests = read("codex-rs/hepta-control-plane/src/planner_context_tests.rs")
planner_context_tests += r'''

#[test]
fn receipt_binds_request_retrieval_ranker_and_exact_record_projection() {
    let original = plan_observed_context(observed()).expect("original plan");
    let mut request = observed();
    request.request_digest = Digest32::of_bytes(b"other-request");
    let mut retrieval = observed();
    retrieval.retrieval_profile_digest = Digest32::of_bytes(b"other-retrieval-profile");
    let mut ranker = observed();
    ranker.ranker_policy_digest = Some(Digest32::of_bytes(b"other-ranker"));
    let mut record = observed();
    record.verified_records[0].revision = Revision::new(4).expect("revision");
    for changed in [request, retrieval, ranker, record] {
        assert_ne!(
            original.evaluation.plan.receipt_digest(),
            plan_observed_context(changed)
                .expect("changed plan")
                .evaluation
                .plan
                .receipt_digest()
        );
    }
}
'''
write("codex-rs/hepta-control-plane/src/planner_context_tests.rs", planner_context_tests)

replace_once(
    "codex-rs/hepta-control-plane/src/lib.rs",
    "pub use planner_context::ObservedContextPlanV1;\npub use planner_context::ObservedContextV1;\n",
    "pub use planner_context::ObservedContextPlanV1;\npub use planner_context::ObservedContextRecordV1;\npub use planner_context::ObservedContextV1;\n",
)

# Agentd constructs the planning observation from the exact owner read, binds
# request/retrieval/ranker identities, uses a process-monotonic TTL, and makes
# plan receipt identity part of final-use validation.
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "use std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
    "use std::sync::OnceLock;\nuse std::time::Instant;\nuse std::time::SystemTime;\nuse std::time::UNIX_EPOCH;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "use codex_hepta_control_plane::ObservedContextV1;\n",
    "use codex_hepta_control_plane::ObservedContextRecordV1;\nuse codex_hepta_control_plane::ObservedContextV1;\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "    let now_micros = u64::try_from(\n        SystemTime::now()\n            .duration_since(UNIX_EPOCH)\n            .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?\n            .as_micros(),\n    )\n    .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))?;\n    let plan = plan_observed_context(ObservedContextV1 {\n",
    "    let now_micros = monotonic_now_micros()?;\n    let verified_records = selected_read\n        .records()\n        .iter()\n        .map(|record| {\n            Ok(ObservedContextRecordV1 {\n                record_id: record.record_id.clone(),\n                revision: record.revision,\n                content_digest: record.content_digest.ok_or_else(|| {\n                    CognitiveStoreError::Corrupt(\n                        \"selected cognitive read omitted its content digest\".to_string(),\n                    )\n                })?,\n            })\n        })\n        .collect::<Result<Vec<_>, CognitiveStoreError>>()?;\n    let request_digest = context_request_digest(owner, body_generation, query, limit, request_id);\n    let retrieval_profile_digest = expected_retrieval_context_digest.unwrap_or_else(|| {\n        Digest32::of_bytes(b\"hepta.agentd.no-retrieval-context.v1\")\n    });\n    let plan = plan_observed_context(ObservedContextV1 {\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "        read_digest: selected_read_binding,\n        verified_item_count: response.items.len() as u32,\n        encoded_context: &encoded_context,\n",
    "        read_digest: selected_read_binding,\n        verified_records,\n        request_digest,\n        retrieval_profile_digest,\n        ranker_policy_digest: downstream_policy_digest,\n        encoded_context: &encoded_context,\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "    response.plan = Some(CognitiveContextPlan {\n        evaluated_context_digest: plan.context_digest.to_string(),\n        plan_receipt_digest: plan.evaluation.plan.receipt_digest().to_string(),\n        read_allowed: plan.read_allowed,\n    });\n",
    "    let plan_receipt_digest = plan.evaluation.plan.receipt_digest();\n    response.plan = Some(CognitiveContextPlan {\n        evaluated_context_digest: bind_context_plan(\n            plan.context_digest,\n            plan_receipt_digest,\n            plan.read_allowed,\n        )\n        .to_string(),\n        plan_receipt_digest: plan_receipt_digest.to_string(),\n        read_allowed: plan.read_allowed,\n    });\n",
)
replace_once(
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "        if Digest32::of_bytes(&encoded).to_string() != plan.evaluated_context_digest {\n",
    "        let context_digest = Digest32::of_bytes(&encoded);\n        let plan_receipt_digest: Digest32 = plan.plan_receipt_digest.parse().map_err(|error| {\n            CognitiveStoreError::Invalid(format!(\"invalid context plan receipt digest: {error}\"))\n        })?;\n        if plan_receipt_digest.is_zero()\n            || bind_context_plan(context_digest, plan_receipt_digest, plan.read_allowed).to_string()\n                != plan.evaluated_context_digest\n        {\n",
)
insert_anchor = "fn bind_selected_read(\n"
agentd = read("codex-rs/hepta-agentd/src/cognitive_context.rs")
if agentd.count(insert_anchor) != 1:
    raise RuntimeError("cognitive_context.rs: bind_selected_read anchor mismatch")
helpers = r'''fn bind_context_plan(
    context_digest: Digest32,
    plan_receipt_digest: Digest32,
    read_allowed: bool,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-plan-final-use.v1\0".to_vec();
    bytes.extend_from_slice(context_digest.as_array());
    bytes.extend_from_slice(plan_receipt_digest.as_array());
    bytes.push(u8::from(read_allowed));
    Digest32::of_bytes(&bytes)
}

fn context_request_digest(
    owner: &AgentId,
    body_generation: u64,
    query: &str,
    limit: u16,
    request_id: Option<u64>,
) -> Digest32 {
    let mut bytes = b"hepta.agentd.cognitive-context-request.v1\0".to_vec();
    bytes.extend_from_slice(owner.as_str().as_bytes());
    bytes.extend_from_slice(&body_generation.to_be_bytes());
    bytes.extend_from_slice(&limit.to_be_bytes());
    bytes.extend_from_slice(&(query.len() as u64).to_be_bytes());
    bytes.extend_from_slice(query.as_bytes());
    match request_id {
        Some(request_id) => {
            bytes.push(1);
            bytes.extend_from_slice(&request_id.to_be_bytes());
        }
        None => bytes.push(0),
    }
    Digest32::of_bytes(&bytes)
}

fn monotonic_now_micros() -> Result<u64, CognitiveStoreError> {
    static ORIGIN: OnceLock<Instant> = OnceLock::new();
    u64::try_from(ORIGIN.get_or_init(Instant::now).elapsed().as_micros())
        .map_err(|error| CognitiveStoreError::Unavailable(error.to_string()))
}

'''
agentd = agentd.replace(insert_anchor, helpers + insert_anchor, 1)
write("codex-rs/hepta-agentd/src/cognitive_context.rs", agentd)

replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    /// Binds the evaluated context with `plan: null`, before any abstention.\n    pub evaluated_context_digest: String,\n",
    "    /// Binds the evaluated context, the exact plan receipt and the read/abstain disposition.\n    pub evaluated_context_digest: String,\n",
)

# Canonical, granular maturity projection.  It records source facts without
# claiming independent acceptance, activation, promotion or release.
map_path = ROOT / "docs/modules/control.runtime/IMPLEMENTATION_MAP.json"
implementation = json.loads(map_path.read_text(encoding="utf-8"))
implementation["productCallerState"] = "read_only_source_composed_candidate"
implementation["productionWriterState"] = "not_composed"
implementation["subsystems"] = {
    "boundedGlobalPlanner": {
        "source": "candidate_implemented",
        "namedProductCaller": "not_composed",
        "productionWriter": "not_composed",
        "activation": False,
    },
    "agentdObservedContextPlanner": {
        "source": "candidate_implemented",
        "namedProductCaller": "source_composed_candidate",
        "productionWriter": "not_applicable_read_only",
        "activation": False,
    },
    "readOnlyOrganHost": {
        "source": "candidate_implemented",
        "namedProductCaller": "not_established",
        "productionWriter": "not_applicable_read_only",
        "activation": False,
    },
    "embodimentReferences": {
        "source": "reference_implemented",
        "namedProductCaller": "not_established",
        "productionWriter": "not_established",
        "activation": False,
    },
    "plannerDurability": {
        "source": "journal_reference_only",
        "namedProductCaller": "not_composed",
        "productionWriter": "not_composed",
        "activation": False,
    },
}
implementation["completion"]["exactHeadQualification"] = "candidate_pending_current_pr_ci"
implementation["completion"]["productionCaller"] = "read_only_agentd_candidate_only"
map_path.write_text(json.dumps(implementation, indent=2, sort_keys=False) + "\n", encoding="utf-8")

maturity = {
    "schema": "hepta.control-runtime-maturity.v1",
    "module": "control.runtime",
    "authorityDelta": "none",
    "candidateState": "source_candidate_pending_exact_head_qualification",
    "scopes": implementation["subsystems"],
    "qualification": {
        "sourceHeadRegression": "required_on_current_commit",
        "syntheticMergeRegression": "required_on_current_commit",
        "controlNduCallerRegression": "required_on_current_commit",
        "strictClippy": "required_on_current_commit",
        "formatting": "required_on_current_commit",
        "packageTests": "required_on_current_commit",
        "namedHostQualification": "required_on_current_commit",
    },
    "externallyGoverned": {
        "independentSemanticReview": False,
        "operatorAcceptance": False,
        "canary": False,
        "activation": False,
        "promotion": False,
        "release": False,
    },
    "nonClaims": [
        "The read-only Agentd caller is not a global planner production writer.",
        "A grant request is not a capability or execution acknowledgement.",
        "CI evidence does not grant activation, promotion or release authority.",
    ],
}
write(
    "docs/readiness/CONTROL_RUNTIME_MATURITY.json",
    json.dumps(maturity, indent=2) + "\n",
)

readiness = read("docs/readiness/CONTROL_RUNTIME_EXECUTION.md")
readiness += r'''

## Current maturity projection

The machine-readable current projection is
`docs/readiness/CONTROL_RUNTIME_MATURITY.json`. It distinguishes the bounded
global planner, the request-local Agentd observed-context caller, the read-only
organ host, embodiment references and planner durability. The Agentd caller is
a source-composed read-only candidate; it is not a global planner production
writer. Exact-head qualification, independent acceptance, activation,
promotion and release remain separate states.

Request-local context planning now binds the exact canonical record projection,
request identity, retrieval profile and optional ranker policy. Its final-use
binding includes the plan receipt digest and disposition. Planner TTL uses a
process-monotonic time domain. Global owner snapshots reject summaries outside
the declared required-owner set, and duplicate final-payload digests reject
rather than being silently removed.
'''
write("docs/readiness/CONTROL_RUNTIME_EXECUTION.md", readiness)

# Remove the one-shot bootstrap from the resulting source commit.
(ROOT / "scripts/control_runtime_convergence_bootstrap.py").unlink()
(ROOT / ".github/workflows/control-runtime-convergence-bootstrap.yml").unlink()
