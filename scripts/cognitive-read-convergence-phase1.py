from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent, indent


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}")
    target.write_text(text.replace(old, new, 1))


def rust_block(source: str, spaces: int) -> str:
    return indent(dedent(source).strip("\n"), " " * spaces)


ids_path = Path("codex-rs/hepta-cognitive-read/src/ids.rs")
ids = ids_path.read_text()
ids = ids.replace(
    "use codex_hepta_cognitive_types::MemoryKind;\n"
    "use codex_hepta_cognitive_types::RecordState;",
    "use codex_hepta_cognitive_types::MemoryKind;\n"
    "use codex_hepta_cognitive_types::MemoryRecord;\n"
    "use codex_hepta_cognitive_types::RecordState;",
    1,
)
body_start = ids.index("    let current = current_records(snapshot, request.snapshot_digest)?;")
body_end = ids.index("\n\n    Ok(ReadIdsResultV1 {", body_start)
new_body = rust_block(
    r"""
let current = current_records(snapshot, request.snapshot_digest)?;
let request_binding_digest = request.binding_digest();
let included_fields = fields.into_iter().collect::<Vec<_>>();
let mut selected_records = Vec::with_capacity(ids.len());
let mut missing_ids = Vec::new();
for id in ids {
    let Some(record) = current.get(&id) else {
        missing_ids.push(id);
        continue;
    };
    selected_records.push(*record);
}

// Compute the exact canonical size before cloning projected fields or
// allocating the result buffer. Exact-ID reads remain all-or-error,
// but an undersized caller budget now fails before materialization.
let encoded_len = encoded_result_len(&selected_records, &missing_ids, &included_fields)?;
if encoded_len > request.maximum_encoded_bytes {
    return Err(ReadIdsError::EncodedResultTooLarge {
        actual: encoded_len,
        maximum: request.maximum_encoded_bytes,
    });
}

let mut records = Vec::with_capacity(selected_records.len());
for record in selected_records {
    let mut citations = if included_fields.contains(&ReadFieldV1::Citations) {
        record.citations.clone()
    } else {
        Vec::new()
    };
    citations.sort();
    records.push(ReadProjectionRecordV1 {
        record_id: record.record_id.clone(),
        revision: record.revision,
        kind: record.kind,
        state: record.state,
        content_digest: included_fields
            .contains(&ReadFieldV1::ContentDigest)
            .then_some(record.content_digest),
        predecessor_digest: if included_fields.contains(&ReadFieldV1::PredecessorDigest) {
            record.predecessor_digest
        } else {
            None
        },
        citations,
    });
}

let mut bytes = Vec::with_capacity(encoded_len);
bytes.extend_from_slice(READ_IDS_RECEIPT_DOMAIN);
bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
bytes.extend_from_slice(request_binding_digest.as_array());
bytes.extend_from_slice(
    &u32::try_from(included_fields.len())
        .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
        .to_be_bytes(),
);
for field in &included_fields {
    bytes.push(field_code(*field));
}
bytes.extend_from_slice(
    &u32::try_from(records.len())
        .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
        .to_be_bytes(),
);
for record in &records {
    encode_record(&mut bytes, record)?;
}
bytes.extend_from_slice(
    &u32::try_from(missing_ids.len())
        .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?
        .to_be_bytes(),
);
for id in &missing_ids {
    push_id(&mut bytes, id);
}
bytes.push(0); // DENY_ALL
let receipt_digest = Digest32::of_bytes(&bytes);
bytes.extend_from_slice(receipt_digest.as_array());
debug_assert_eq!(bytes.len(), encoded_len);
""",
    4,
)
ids = ids[:body_start] + new_body + ids[body_end:]

helper_anchor = (
    "fn encode_record(bytes: &mut Vec<u8>, record: &ReadProjectionRecordV1) "
    "-> Result<(), ReadIdsError> {"
)
if ids.count(helper_anchor) != 1:
    raise SystemExit(f"{ids_path}: encode_record anchor mismatch")
helpers = dedent(
    r"""
fn encoded_result_len(
    records: &[&MemoryRecord],
    missing_ids: &[StableId],
    included_fields: &[ReadFieldV1],
) -> Result<usize, ReadIdsError> {
    const DIGEST_BYTES: usize = 32;
    const COUNT_BYTES: usize = 4;

    u32::try_from(included_fields.len())
        .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
    u32::try_from(records.len()).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
    u32::try_from(missing_ids.len()).map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;

    let include_content = included_fields.contains(&ReadFieldV1::ContentDigest);
    let include_predecessor = included_fields.contains(&ReadFieldV1::PredecessorDigest);
    let include_citations = included_fields.contains(&ReadFieldV1::Citations);
    let mut length = 0_usize;

    add_encoded_len(&mut length, READ_IDS_RECEIPT_DOMAIN.len())?;
    add_encoded_len(&mut length, DIGEST_BYTES)?; // snapshot digest
    add_encoded_len(&mut length, DIGEST_BYTES)?; // request binding digest
    add_encoded_len(&mut length, COUNT_BYTES)?;
    add_encoded_len(&mut length, included_fields.len())?;
    add_encoded_len(&mut length, COUNT_BYTES)?;

    for record in records {
        add_encoded_id_len(&mut length, &record.record_id)?;
        add_encoded_len(&mut length, 8)?; // revision
        add_encoded_len(&mut length, 1)?; // kind
        add_encoded_len(&mut length, 1)?; // state
        add_encoded_len(&mut length, 1)?; // content option marker
        if include_content {
            add_encoded_len(&mut length, DIGEST_BYTES)?;
        }
        add_encoded_len(&mut length, 1)?; // predecessor option marker
        if include_predecessor && record.predecessor_digest.is_some() {
            add_encoded_len(&mut length, DIGEST_BYTES)?;
        }
        add_encoded_len(&mut length, COUNT_BYTES)?;
        if include_citations {
            u32::try_from(record.citations.len())
                .map_err(|_| ReadIdsError::InvalidCanonicalEncoding)?;
            for citation in &record.citations {
                add_encoded_id_len(&mut length, &citation.source_id)?;
                add_encoded_len(&mut length, DIGEST_BYTES)?;
            }
        }
    }

    add_encoded_len(&mut length, COUNT_BYTES)?;
    for id in missing_ids {
        add_encoded_id_len(&mut length, id)?;
    }
    add_encoded_len(&mut length, 1)?; // DENY_ALL authority posture
    add_encoded_len(&mut length, DIGEST_BYTES)?; // receipt digest
    Ok(length)
}

fn add_encoded_id_len(length: &mut usize, value: &StableId) -> Result<(), ReadIdsError> {
    add_encoded_len(length, 4)?;
    add_encoded_len(length, value.as_str().len())
}

fn add_encoded_len(length: &mut usize, amount: usize) -> Result<(), ReadIdsError> {
    *length = length
        .checked_add(amount)
        .ok_or(ReadIdsError::InvalidCanonicalEncoding)?;
    Ok(())
}

"""
)
ids = ids.replace(helper_anchor, helpers + helper_anchor, 1)
ids_path.write_text(ids)

tests_path = Path("codex-rs/hepta-cognitive-read/src/ids_tests.rs")
tests = tests_path.read_text()
test_marker = "fn exact_encoded_budget_succeeds_and_one_byte_less_fails_before_partial_return()"
if test_marker in tests:
    raise SystemExit(f"{tests_path}: phase-one tests already present")
tests += dedent(
    r"""

#[test]
fn duplicate_fields_invalid_budgets_and_snapshot_mismatch_fail_closed() {
    let snapshot = snapshot(vec![record("memory:a", RecordState::Live)]);
    let duplicate_field = ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: vec![id("memory:a")],
        fields: vec![ReadFieldV1::ContentDigest, ReadFieldV1::ContentDigest],
        maximum_encoded_bytes: 4096,
    };
    assert_eq!(
        read_ids_v1(&snapshot, duplicate_field),
        Err(ReadIdsError::DuplicateField)
    );

    for requested in [0, MAX_ENCODED_READ_RESULT_BYTES_V2 + 1] {
        let invalid_budget = ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:a")],
            fields: Vec::new(),
            maximum_encoded_bytes: requested,
        };
        assert_eq!(
            read_ids_v1(&snapshot, invalid_budget),
            Err(ReadIdsError::InvalidMaximumEncodedBytes {
                requested,
                maximum: MAX_ENCODED_READ_RESULT_BYTES_V2,
            })
        );
    }

    let other = snapshot(vec![record("memory:other", RecordState::Live)]);
    let mismatched = ReadIdsRequestV1 {
        snapshot_digest: other.snapshot_digest,
        record_ids: vec![id("memory:a")],
        fields: Vec::new(),
        maximum_encoded_bytes: 4096,
    };
    assert_eq!(
        read_ids_v1(&snapshot, mismatched),
        Err(ReadIdsError::Read(Error::SnapshotMismatch))
    );
}

#[test]
fn request_order_is_canonical_for_exact_id_reads() {
    let snapshot = snapshot(vec![
        record("memory:a", RecordState::Live),
        record("memory:b", RecordState::Live),
    ]);
    let left = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:b"), id("memory:missing"), id("memory:a")],
            fields: vec![
                ReadFieldV1::PredecessorDigest,
                ReadFieldV1::ContentDigest,
            ],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("left canonical read");
    let right = read_ids_v1(
        &snapshot,
        ReadIdsRequestV1 {
            snapshot_digest: snapshot.snapshot_digest,
            record_ids: vec![id("memory:a"), id("memory:b"), id("memory:missing")],
            fields: vec![
                ReadFieldV1::ContentDigest,
                ReadFieldV1::PredecessorDigest,
            ],
            maximum_encoded_bytes: 4096,
        },
    )
    .expect("right canonical read");

    assert_eq!(
        left.request_binding_digest(),
        right.request_binding_digest()
    );
    assert_eq!(left.records(), right.records());
    assert_eq!(left.missing_ids(), right.missing_ids());
    assert_eq!(left.canonical_bytes(), right.canonical_bytes());
}

#[test]
fn exact_encoded_budget_succeeds_and_one_byte_less_fails_before_partial_return() {
    let snapshot = snapshot(vec![record("memory:a", RecordState::Live)]);
    let request = |maximum_encoded_bytes| ReadIdsRequestV1 {
        snapshot_digest: snapshot.snapshot_digest,
        record_ids: vec![id("memory:a"), id("memory:missing")],
        fields: vec![
            ReadFieldV1::ContentDigest,
            ReadFieldV1::PredecessorDigest,
            ReadFieldV1::Citations,
        ],
        maximum_encoded_bytes,
    };

    let baseline = read_ids_v1(&snapshot, request(4096)).expect("baseline read");
    let exact_size = baseline.canonical_bytes().len();
    let exact = read_ids_v1(&snapshot, request(exact_size)).expect("exact budget read");
    assert_eq!(exact.canonical_bytes().len(), exact_size);
    assert_eq!(
        read_ids_v1(&snapshot, request(exact_size - 1)),
        Err(ReadIdsError::EncodedResultTooLarge {
            actual: exact_size,
            maximum: exact_size - 1,
        })
    );
}
"""
)
tests_path.write_text(tests)

context_path = "codex-rs/hepta-agentd/src/cognitive_context.rs"
replace_once(
    context_path,
    "    let mut observed = observation.candidates().to_vec();\n",
    rust_block(
        r"""
let admission_records = admission_read
    .records()
    .iter()
    .map(|record| ((record.record_id.as_str(), record.revision.get()), record))
    .collect::<BTreeMap<_, _>>();
let mut observed = observation.candidates().to_vec();
""",
        4,
    )
    + "\n",
)

replace_once(
    context_path,
    rust_block(
        r"""
let accepted = admission_read.records().iter().any(|record| {
    record.is_live()
        && record.record_id.as_str() == binding.memory.memory_id.as_str()
        && record.revision.get() == binding.memory.revision
        && record
            .content_digest
            .is_some_and(|digest| digest.to_string() == binding.content_sha256.as_str())
        && binding.scope == scope
});
""",
        8,
    ),
    rust_block(
        r"""
let accepted = admission_records
    .get(&(
        binding.memory.memory_id.as_str(),
        binding.memory.revision,
    ))
    .is_some_and(|record| {
        record.is_live()
            && record
                .content_digest
                .is_some_and(|digest| digest.to_string() == binding.content_sha256.as_str())
            && binding.scope == scope
    });
""",
        8,
    ),
)

replace_once(
    context_path,
    rust_block(
        r"""
let accepted = admission_read.records().iter().any(|record| {
    record.is_live()
        && record.record_id.as_str() == memory.id.memory_id.as_str()
        && record.revision.get() == memory.id.revision
        && record
            .content_digest
            .is_some_and(|digest| digest.to_string() == memory.content_sha256.as_str())
        && memory.scope == scope
});
""",
        8,
    ),
    rust_block(
        r"""
let accepted = admission_records
    .get(&(memory.id.memory_id.as_str(), memory.id.revision))
    .is_some_and(|record| {
        record.is_live()
            && record
                .content_digest
                .is_some_and(|digest| digest.to_string() == memory.content_sha256.as_str())
            && memory.scope == scope
    });
""",
        8,
    ),
)

replace_once(
    "codex-rs/hepta-agentd/src/test_support.rs",
    "            Arg0DispatchPaths::default(),\n",
    rust_block(
        r"""
Arg0DispatchPaths {
    codex_self_exe: Some(std::env::current_exe()?),
    codex_linux_sandbox_exe: None,
    main_execve_wrapper_exe: None,
},
""",
        12,
    )
    + "\n",
)

replace_once(
    "codex-rs/hepta-infer-worker-host/src/native_app_server_tests.rs",
    rust_block(
        r"""
let turn_start = source
    .find("client.request_typed::<TurnStartResponse>(ClientRequest::TurnStart")
    .expect("physical turn start");
""",
        4,
    ),
    rust_block(
        r"""
assert!(source.contains("request_typed_observed(ClientRequest::TurnStart"));
let turn_start = source
    .find("send_authorized_turn_start(&mut client, entered_use, turn_params)")
    .expect("authorized physical turn start");
""",
        4,
    ),
)

guide_path = "docs/modules/cognitive.read/TECHNICAL.md"
replace_once(
    guide_path,
    "The canonical work package `MEM-READ-1-SNAPSHOT-PORT` is "
    "`source_implemented_execution_pending`.",
    "The production Agentd read entry is "
    "`read_with_retrieval_context_and_learning`, and the final-use entry is "
    "`revalidate_with_retrieval_context`. The shorter `read` and `revalidate` "
    "wrappers are test-only conveniences and are not product callers.\n\n"
    "The canonical work package `MEM-READ-1-SNAPSHOT-PORT` is "
    "`source_implemented_execution_pending`.",
)

map_path = Path("docs/modules/cognitive.read/IMPLEMENTATION_MAP.json")
implementation_map = json.loads(map_path.read_text())
for operation in implementation_map["operations"]:
    if operation["operation"] == "final_use_revalidate":
        operation["nativeSymbol"] = "revalidate_with_retrieval_context"
caller_symbols = {
    "owner_read_adapter": (
        "pub(crate) async fn read_with_retrieval_context_and_learning("
    ),
    "owner_final_use_revalidation": (
        "pub(crate) async fn revalidate_with_retrieval_context("
    ),
}
for caller in implementation_map["productCallers"]:
    if caller["role"] in caller_symbols:
        caller["nativeSymbol"] = caller_symbols[caller["role"]]
map_path.write_text(json.dumps(implementation_map, indent=2) + "\n")
