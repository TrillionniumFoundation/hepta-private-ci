#!/usr/bin/env python3
"""Apply the reviewed lifecycle binding to exactly known Agentd source objects.

This is a one-time, narrow migration. Unknown source blobs are conflicts, never
an invitation to regex-edit concurrent work. CI publishes the resulting native
files before measuring them; executing this script alone is not qualification.
"""
from pathlib import Path
import hashlib

ROOT = Path(__file__).resolve().parents[1]


def checked_read(path: str, expected: str, marker: str) -> str | None:
    raw = (ROOT / path).read_bytes()
    text = raw.decode()
    if marker in text:
        return None
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != expected:
        raise RuntimeError(f"{path}: source conflict ({actual}, expected {expected})")
    return text


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"expected exactly one binding site: {old[:90]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    updates = {}
    path = "codex-rs/hepta-agentd/src/cognitive_context.rs"
    text = checked_read(path, "494043d2e03a7f738ad1de3a065766a4423cef0b", "mod retrieval_lease;")
    if text is not None:
        text = replace_once(text, "use codex_hepta_memory::RetrievalExecutionContextV1;\n", "")
        text = replace_once(text, "const MAX_CONTEXT_JSON_BYTES:",
            '#[path = "cognitive_retrieval_lease.rs"]\nmod retrieval_lease;\nuse retrieval_lease::AcquiredRetrievalContext;\n\nconst MAX_CONTEXT_JSON_BYTES:')
        text = replace_once(text, ".map(RetrievalExecutionContextV1::binding_digest)",
            ".map(AcquiredRetrievalContext::binding_digest)")
        text = replace_once(text, "        let execution = execute_owner_observation(\n",
            "        let lease_expires_unix_ms = context.bound_deadline(lease_expires_unix_ms);\n"
            "        if lease_expires_unix_ms <= acquired_at_unix_ms {\n"
            "            return Err(CognitiveContextError::RetrievalContextUnavailable);\n"
            "        }\n"
            "        let execution = execute_owner_observation(\n")
        start = text.index("async fn load_retrieval_context(")
        end = text.index("fn now_seconds()", start)
        text = text[:start] + '''async fn load_retrieval_context(
    current: &std::sync::Arc<dyn crate::CurrentMemoryRetrievalContext>,
    owner: &AgentId,
    body_generation: u64,
) -> Result<AcquiredRetrievalContext, CognitiveContextError> {
    let current = std::sync::Arc::clone(current);
    let owner = owner.clone();
    let (context, lifecycle_binding, lease_expires_unix_ms) =
        tokio::task::spawn_blocking(move || current.acquire_context(&owner, body_generation))
            .await
            .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?
            .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    context.validate().map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?;
    if lifecycle_binding.is_zero() {
        return Err(CognitiveContextError::RetrievalContextUnavailable);
    }
    if let Some(lease) = lease_expires_unix_ms {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)
            .map_err(|_| CognitiveContextError::RetrievalContextUnavailable)?.as_millis();
        if u128::from(lease) <= now {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    Ok(AcquiredRetrievalContext { context, lifecycle_binding, lease_expires_unix_ms })
}

''' + text[end:]
        text = replace_once(text, "    Ok(response)\n}", '''    // Append completion is not a freshness fence. A prepared assignment does
    // not prove native consumption; publication still requires current owners.
    store.revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?).await?;
    if let (Some(current), Some(expected)) = (current_retrieval, expected_retrieval_context_digest) {
        if load_retrieval_context(current, owner, body_generation).await?.binding_digest() != expected {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    Ok(response)
}''')
        text = replace_once(text, "    Ok(CognitiveContextRevalidation {", '''    // The optional ranker above may await. Recheck both owners after that gap.
    store.revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?).await?;
    if let (Some(current), Some(expected)) = (current_retrieval, retrieval_context_digest) {
        if load_retrieval_context(current, owner, body_generation).await?.binding_digest() != expected {
            return Err(CognitiveContextError::RetrievalContextUnavailable);
        }
    }
    Ok(CognitiveContextRevalidation {''')
        updates[path] = text
    path = "codex-rs/hepta-agentd/src/lib.rs"
    text = checked_read(path, "c075e561eaa96820706ad98d20972eb5fd924b06", "pub use cognitive_retrieval_context::ProductRetrievalContextControlV1;")
    if text is not None:
        text = replace_once(text, "pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;",
            "pub use cognitive_retrieval_context::CurrentMemoryRetrievalContext;\n"
            "pub use cognitive_retrieval_context::ProductRetrievalContextControlV1;\n"
            "pub use cognitive_retrieval_context::ProductRetrievalContextSnapshotV1;\n"
            "pub use cognitive_retrieval_context::RetrievalRecoveryWitnessV1;")
        updates[path] = text
    path = "codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs"
    text = checked_read(path, "bf1dcdcd86aff60bc528d42915cee909efd944a6", "same_payload_product_epoch_invalidates_final_use")
    if text is not None:
        text += '''

#[tokio::test]
async fn same_payload_product_epoch_invalidates_final_use() {
    let (_temp, store, owner, context, _memory_id) = fixture(963).await;
    let lease = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()).unwrap() + 120_000;
    let (reader, control) = <dyn CurrentMemoryRetrievalContext>::product_with_control(owner.clone(), 1, context, lease).unwrap();
    let response = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&reader)).await.unwrap();
    assert!(!response.items.is_empty());
    control.renew(1, lease).unwrap();
    let current = crate::cognitive_context::revalidate_with_retrieval_context(
        &store, &owner, &response.snapshot_digest, &response.read_digest,
        response.omitted_records, &response.items, response.plan.as_ref(), None, 1, Some(&reader),
    ).await;
    assert!(current.is_err(), "same payload with another lease epoch must invalidate the old read");
}

#[tokio::test]
async fn revoked_product_context_invalidates_final_use() {
    let (_temp, store, owner, context, _memory_id) = fixture(964).await;
    let lease = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis()).unwrap() + 120_000;
    let (reader, control) = <dyn CurrentMemoryRetrievalContext>::product_with_control(owner.clone(), 1, context, lease).unwrap();
    let response = read_with_retrieval_context(&store, &owner, 1, "lemon", 4, None, Some(&reader)).await.unwrap();
    control.revoke(1).unwrap();
    assert!(crate::cognitive_context::revalidate_with_retrieval_context(
        &store, &owner, &response.snapshot_digest, &response.read_digest,
        response.omitted_records, &response.items, response.plan.as_ref(), None, 1, Some(&reader),
    ).await.is_err());
}
'''
        updates[path] = text
    # Validate every source before writing any target.
    for path, content in updates.items():
        (ROOT / path).write_text(content)
    print(f"applied {len(updates)} exact-object lifecycle bindings")


if __name__ == "__main__":
    main()
