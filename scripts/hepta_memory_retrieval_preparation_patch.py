#!/usr/bin/env python3
"""One-shot migration to a separately tagged, unexposed preparation event.

This program runs only in a read-only preparation job. The write-scoped job
validates an explicit data-only path allowlist and an unchanged source commit.
"""
from pathlib import Path
import json
import re
import subprocess
import sys

L = "codex-rs/hepta-learning-ledger/src/"
A = "codex-rs/hepta-agentd/src/"
PATHS = tuple(L + name for name in (
    "lib.rs", "model.rs", "ledger.rs", "checkpoint.rs", "durable_codec.rs",
    "production.rs", "durable_tests.rs", "retrieval_preparation.rs", "retrieval_preparation_tests.rs",
)) + tuple(A + name for name in (
    "cognitive_context.rs", "cognitive_retrieval_learning.rs", "cognitive_retrieval_learning_tests.rs",
))

def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()

def replace(text, old, new, count=1):
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"preimage mismatch: expected {count}, found {actual}: {old[:100]!r}")
    return text.replace(old, new)

def apply():
    source = {path: Path(path).read_text(encoding="utf-8") for path in PATHS}
    if "mod retrieval_preparation;" in source[L + "lib.rs"]:
        raise RuntimeError("preparation migration has already been applied")
    p = L + "lib.rs"
    source[p] = replace(source[p], "mod retrieval_assignment;", "mod retrieval_assignment;\nmod retrieval_preparation;")
    source[p] = replace(source[p], "pub use retrieval_assignment::RetrievalAssignmentBridgeError;",
        "pub use retrieval_preparation::RetrievalPreparationFactV1;\npub use retrieval_preparation::retrieval_preparation_event_v1;\npub use retrieval_assignment::RetrievalAssignmentBridgeError;")

    p = L + "model.rs"
    text = replace(source[p], "    RetrievalAssignment(RetrievalAssignmentFact),",
        "    RetrievalAssignment(RetrievalAssignmentFact),\n    RetrievalPrepared(crate::RetrievalPreparationFactV1),")
    text = replace(text, "            Self::RetrievalAssignment(value) => &value.record_id,",
        "            Self::RetrievalAssignment(value) => &value.record_id,\n            Self::RetrievalPrepared(value) => &value.assignment.record_id,")
    start = text.index("    /// Exact ordered subset prepared for")
    end = text.index("    pub omitted_by_policy_limits:", start)
    text = text[:start] + '''    /// Legacy asserted delivery order. Preserve the exact stored values and
    /// positions; do not silently reinterpret historical tag-9 records.
    pub delivered_candidate_indices: Vec<u32>,
    /// Legacy assertion, not independently authenticated publication evidence.
    /// Some historical producer revisions reused this bit for preparation.
    /// Such records must never be automatically promoted to physical exposure.
    /// New product preparation writes use RetrievalPrepared (tag 10).
    pub context_exposed: bool,
    /// Historical asserted context identity. Actual publication/native use
    /// requires independently owned consumer evidence, not this digest alone.
    pub published_context_digest: Option<Digest32>,
''' + text[end:]
    source[p] = text

    p = L + "ledger.rs"
    text = source[p]
    text = replace(text,
        "            LedgerEvent::RetrievalAssignment(value) => self.validate_retrieval_assignment(value),",
        "            LedgerEvent::RetrievalAssignment(value) => self.validate_retrieval_assignment(value),\n            LedgerEvent::RetrievalPrepared(value) => self.validate_retrieval_assignment(&value.wire_assignment()),")
    text = replace(text, "LedgerEvent::RetrievalAssignment(_) => {}",
        "LedgerEvent::RetrievalAssignment(_) | LedgerEvent::RetrievalPrepared(_) => {}")
    text = replace(text, "| LedgerEvent::RetrievalAssignment(_) => true,",
        "| LedgerEvent::RetrievalAssignment(_)\n            | LedgerEvent::RetrievalPrepared(_) => true,")
    text = replace(text,
        "fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {\n    match event {",
        '''fn validate_support_digests(event: &LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::RetrievalPrepared(value) => {
            value.validate_unexposed()?;
            validate_support_digests(&LedgerEvent::RetrievalAssignment(value.wire_assignment()))?;
        }''')
    text = replace(text,
        "fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {\n    match event {",
        '''fn normalize_event(event: &mut LedgerEvent) -> Result<(), LedgerError> {
    match event {
        LedgerEvent::RetrievalPrepared(value) => {
            value.validate_unexposed()?;
            let mut shape = LedgerEvent::RetrievalAssignment(value.wire_assignment());
            normalize_event(&mut shape)?;
            let LedgerEvent::RetrievalAssignment(assignment) = shape else {
                return Err(LedgerError::InternalInvariant);
            };
            *value = crate::RetrievalPreparationFactV1::from_wire_assignment(assignment);
        }''')
    text = replace(text, "enum EventKind {\n    RetrievalAssignment,",
        "enum EventKind {\n    RetrievalAssignment,\n    RetrievalPrepared,")
    text = replace(text, "        EventKind::RetrievalAssignment => 9,",
        "        EventKind::RetrievalAssignment => 9,\n        EventKind::RetrievalPrepared => 10,")
    text = replace(text, "        LedgerEvent::RetrievalAssignment(_) => EventKind::RetrievalAssignment,",
        "        LedgerEvent::RetrievalAssignment(_) => EventKind::RetrievalAssignment,\n        LedgerEvent::RetrievalPrepared(_) => EventKind::RetrievalPrepared,")
    text = replace(text, "        LedgerEvent::RetrievalAssignment(value) => push_retrieval_assignment(&mut bytes, value),",
        "        LedgerEvent::RetrievalAssignment(value) => push_retrieval_assignment(&mut bytes, value),\n        LedgerEvent::RetrievalPrepared(value) => push_retrieval_assignment(&mut bytes, &value.wire_assignment()),")
    source[p] = text

    p = L + "checkpoint.rs"
    source[p] = replace(source[p], "LedgerEvent::RetrievalAssignment(_) => 9,",
        "LedgerEvent::RetrievalAssignment(_) => 9,\n        LedgerEvent::RetrievalPrepared(_) => 10,")

    p = L + "durable_codec.rs"
    text = replace(source[p], "    let event = match reader.byte()? {",
        "    let tag = reader.byte()?;\n    let event = match tag {")
    head = "        9 => LedgerEvent::RetrievalAssignment(RetrievalAssignmentFact {"
    start = text.index(head)
    end = text.index("\n        }),", start) + len("\n        }),")
    fields = text[start + len(head):end - len("\n        }),")]
    text = text[:start] + "        9 | 10 => {\n            let assignment = RetrievalAssignmentFact {" + fields + '''
            };
            if tag == 9 {
                LedgerEvent::RetrievalAssignment(assignment)
            } else {
                // Validate the wire state before extracting preparation fields;
                // otherwise a malformed state bit could be silently discarded.
                if assignment.context_exposed == assignment.delivered_candidate_indices.is_empty()
                    || assignment.context_exposed != assignment.published_context_digest.is_some()
                {
                    return Err(DurableLedgerError::Corrupt);
                }
                LedgerEvent::RetrievalPrepared(
                    crate::RetrievalPreparationFactV1::from_wire_assignment(assignment),
                )
            }
        },''' + text[end:]
    source[p] = text

    p = L + "production.rs"
    text = source[p]
    marker = "    pub fn append_retrieval_assignment_current("
    start = text.index(marker)
    end = text.index("\n    }", start) + len("\n    }")
    method = text[start:end]
    new_method = method.replace("append_retrieval_assignment_current", "append_retrieval_preparation_current")
    new_method = new_method.replace("crate::RetrievalAssignmentFact", "crate::RetrievalPreparationFactV1")
    new_method = new_method.replace(": RetrievalAssignmentFact", ": crate::RetrievalPreparationFactV1")
    new_method = new_method.replace("LedgerEvent::RetrievalAssignment", "LedgerEvent::RetrievalPrepared")
    new_method = new_method.replace("assignment.record_id", "assignment.assignment.record_id")
    if new_method == method or "RetrievalPreparationFactV1" not in new_method:
        raise RuntimeError("production append signature changed")
    text = text[:end] + "\n\n    /// Append an unexposed preparation using the existing writer/witness CAS.\n" + new_method + text[end:]
    source[p] = text
    print("PRODUCTION_PREPARATION_METHOD\n" + new_method)

    p = A + "cognitive_retrieval_learning.rs"
    text = source[p]
    text = replace(text, "use codex_hepta_learning_ledger::retrieval_assignment_event_with_delivery_policy;",
        "use codex_hepta_learning_ledger::retrieval_preparation_event_v1;")
    text = replace(text, "    pub(crate) fn append(", "    #[cfg(test)]\n    pub(crate) fn append(")
    text = replace(text, "    pub(crate) fn append_with_delivery(", "    #[cfg(test)]\n    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn append_with_delivery(")
    start = text.index("    #[allow(clippy::too_many_arguments)]\n    pub(crate) fn append_with_delivery_policy(")
    # Retain the compatibility helper only in tests; production has no exposed bit.
    wrapper = '''    #[cfg(test)]
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn append_with_delivery_policy(
        &self,
        owner: &AgentId,
        body_generation: u64,
        request_id: u64,
        observation: &RetrievalAssignmentObservationV1,
        delivered_candidates: &[RetrievalCandidateIdentityV1],
        context_exposed: bool,
        published_context_digest: Option<Digest32>,
        downstream_policy_digest: Option<Digest32>,
        delivery_propensity: ProbabilityQ32,
    ) -> Result<AppendReceipt, String> {
        if context_exposed == delivered_candidates.is_empty() {
            return Err("preparation shape mismatch".to_string());
        }
        self.append_preparation(owner, body_generation, request_id, observation,
            delivered_candidates, published_context_digest, downstream_policy_digest,
            delivery_propensity)
    }

'''
    product = text[start:]
    product = replace(product, "pub(crate) fn append_with_delivery_policy(", "pub(crate) fn append_preparation(")
    product = replace(product, "        context_exposed: bool,\n", "")
    product = product.replace("delivered_candidates", "prepared_candidates")
    product = product.replace("published_context_digest", "prepared_context_digest")
    product = replace(product, 'b"hepta.agentd.retrieval-assignment.v1"', 'b"hepta.agentd.retrieval-preparation.v1"')
    product = replace(product, '"retrieval-assignment:{}"', '"retrieval-preparation:{}"')
    product = replace(product, "retrieval_assignment_event_with_delivery_policy(", "retrieval_preparation_event_v1(")
    product = replace(product, "            context_exposed,\n", "")
    product = replace(product, "LedgerEvent::RetrievalAssignment(assignment)", "LedgerEvent::RetrievalPrepared(assignment)")
    product = replace(product, ".append_retrieval_assignment_current(assignment)", ".append_retrieval_preparation_current(assignment)")
    text = text[:start] + wrapper + product
    text = text.replace("durable learning-ledger sink for retrieval assignment evidence.",
        "durable learning-ledger sink for unexposed retrieval preparations.")
    source[p] = text

    p = A + "cognitive_context.rs"
    text = source[p]
    if "begin_shadow(&request_work)" not in text or "T: Send" in text:
        raise RuntimeError("owned-work predecessor not present")
    text = replace(text, "sink.append_with_delivery_policy(", "sink.append_preparation(")
    text = replace(text, "                    context_exposed,\n", "")
    text = text.replace("let context_exposed = !delivered_candidates.is_empty();", "let has_prepared_context = !delivered_candidates.is_empty();")
    text = text.replace("let published_context_digest = if context_exposed {", "let prepared_context_digest = if has_prepared_context {")
    text = replace(text, "                    published_context_digest,", "                    prepared_context_digest,")
    start = text.index("    // A concurrent correction, deletion, changed citation, expiry or restored")
    end = text.index("    // Every owner, ranker and retrieval-lifecycle fence has passed.", start)
    final_fence = text[start:end]
    text = replace(text, '''    // Every owner, ranker and retrieval-lifecycle fence has passed. The
    // append below is the idempotent AssignmentPrepared commit point.
    // It is not publication or native-consumption evidence; those facts
    // are joined from the durable native journal by exact context digest.''', '''    // Append only a separately tagged, unexposed preparation. The append may
    // outlive a cancelled waiter; final freshness is checked again afterwards.
    // Neither this event nor an equal digest authenticates consumer publication.''')
    text = replace(text, '''    // No fallible owner operation may follow a successful preparation
    // append: a late failure would create a durable fact for a response
    // the caller never received. External publication remains a separate
    // native-journal observation.
    Ok(response)''', '''    // An immutable preparation is allowed to survive failure. It cannot be
    // interpreted as publication, so freshness must not be weakened to avoid
    // recording an unexposed attempt whose response was never delivered.
''' + final_fence + '''    request_work.checkpoint()
        .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    Ok(response)''')
    source[p] = text

    source[L + "durable_tests.rs"] += '''
#[test]
fn preparation_reopen_and_torn_append_never_produce_exposure() {
    let LedgerEvent::RetrievalAssignment(assignment) = retrieval_assignment() else {
        panic!("retrieval fixture kind");
    };
    let event = LedgerEvent::RetrievalPrepared(
        crate::RetrievalPreparationFactV1::from_wire_assignment(assignment),
    );
    let fixture = Fixture::new();
    let snapshot = fixture.write_events(vec![event]);
    let bytes = must(fs::read(fixture.path()));
    let reopened = must(fixture.recover(anchored(&snapshot)));
    let restored = must(reopened.snapshot());
    assert_eq!(restored, snapshot);
    let LedgerEvent::RetrievalPrepared(prepared) = &restored.records()[0].event else {
        panic!("recovery reclassified a preparation");
    };
    assert!(!prepared.assignment.context_exposed);
    assert!(prepared.assignment.delivered_candidate_indices.is_empty());
    assert!(prepared.assignment.published_context_digest.is_none());
    assert_eq!(prepared.prepared_candidate_indices.len(), 1);
    assert!(prepared.prepared_context_digest.is_some());
    drop(reopened);
    for missing in 1..=32 {
        must(fs::write(fixture.path(), &bytes[..bytes.len() - missing]));
        assert!(fixture.recover(anchored(&snapshot)).is_err(),
            "acknowledged truncated preparation recovered with {missing} bytes missing");
    }
    must(fs::write(fixture.path(), bytes));
}
'''
    source[A + "cognitive_retrieval_learning_tests.rs"] += '''
#[test]
fn product_sink_nonempty_context_is_a_preparation_not_an_exposure() {
    let (_temp, sink) = sink();
    let observation = observation("prepared-packet");
    sink.append_preparation(&owner(), 1, 707, &observation,
        &observation.selected_candidates, Some(digest("exact-response")),
        None, ProbabilityQ32::ONE).expect("prepare");
    let snapshot = sink.writer.lock().expect("lock").snapshot().expect("snapshot");
    let LedgerEvent::RetrievalPrepared(prepared) = &snapshot.records()[0].event else {
        panic!("product sink emitted a legacy exposure event");
    };
    assert!(!prepared.assignment.context_exposed);
    assert!(prepared.assignment.delivered_candidate_indices.is_empty());
    assert!(prepared.assignment.published_context_digest.is_none());
    assert_eq!(prepared.prepared_candidate_indices, vec![0]);
    assert_eq!(prepared.prepared_context_digest, Some(digest("exact-response")));
}
'''
    for path, text in source.items():
        Path(path).write_text(text, encoding="utf-8")
        print("modified " + path)

def manifest(output):
    changed = set(git("diff", "--name-only").splitlines())
    if not changed <= set(PATHS):
        raise RuntimeError("formatter changed a path outside the source allowlist")
    entries = [{"path": path, "before": git("rev-parse", f"HEAD:{path}"),
                "content": Path(path).read_text(encoding="utf-8")} for path in PATHS]
    Path(output).write_text(json.dumps({"base": git("rev-parse", "HEAD"), "changes": entries}), encoding="utf-8")

if __name__ == "__main__":
    if sys.argv[1:] == ["apply"]:
        apply()
    elif len(sys.argv) == 3 and sys.argv[1] == "manifest":
        manifest(sys.argv[2])
    else:
        raise SystemExit("usage: preparation_patch.py apply | manifest OUTPUT")
