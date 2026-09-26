#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one replacement, found {count}: {old[:80]!r}")
    file.write_text(text.replace(old, new, 1))


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    file = Path(path)
    text = file.read_text()
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"{path}: expected at least {minimum} replacements, found {count}: {old!r}")
    file.write_text(text.replace(old, new))


CARGO = "codex-rs/hepta-agentd/Cargo.toml"
replace_once(
    CARGO,
    '''[features]
# Agentd is the named Hepta product host for scoped cognitive mutations. This
# default is local to the Agentd crate; ordinary Codex/App Server binaries do
# not enable HeptaCognitiveWrite by default.
default = ["production-cognitive-write"]
production-cognitive-write = []
# Adds the qualification-only turn-lifecycle witness seam on top of the real
# product mutation profile. It never substitutes for production authority.
qualification-cognitive-write = ["production-cognitive-write"]
qualification-legacy-learning-write = ["codex-hepta-learning-ledger/qualification-legacy-write"]
''',
    '''[features]
# Production mutation authority is supplied by the independently recovered
# Agentd production host, never by a Cargo feature. This feature only enables
# the qualification witness and fail-closed startup seam.
default = []
qualification-cognitive-write = []
''',
)
replace_once(
    CARGO,
    'codex-hepta-learning-ledger = { path = "../hepta-learning-ledger", features = ["qualification-legacy-write"] }',
    'codex-hepta-learning-ledger = { path = "../hepta-learning-ledger" }',
)
replace_once(
    CARGO,
    'thiserror = { workspace = true }\n',
    'thiserror = { workspace = true }\ntracing = { workspace = true }\n',
)

APP_RUNTIME = "codex-rs/hepta-agentd/src/app_runtime.rs"
replace_once(
    APP_RUNTIME,
    '''#[cfg(feature = "production-cognitive-write")]
const COGNITIVE_WRITE_ENABLED: bool = true;
#[cfg(not(feature = "production-cognitive-write"))]
const COGNITIVE_WRITE_ENABLED: bool = false;
''',
    '''// Cargo features never grant production mutation authority. The static
// switch exists only for the qualification witness profile; the production
// path is enabled exclusively by a recovered mutation host.
const COGNITIVE_WRITE_ENABLED: bool = cfg!(feature = "qualification-cognitive-write");
''',
)

for path in [
    "codex-rs/hepta-agentd/src/runtime.rs",
    "codex-rs/hepta-agentd/src/runtime_tests.rs",
    "codex-rs/hepta-agentd/tests/cognitive_product_e2e.rs",
]:
    replace_all(path, "production-cognitive-write", "qualification-cognitive-write")

LIB = "codex-rs/hepta-agentd/src/lib.rs"
replace_once(LIB, "mod cognitive_context;\n", "mod cognitive_context;\nmod cognitive_context_metrics;\n")

CONTEXT = "codex-rs/hepta-agentd/src/cognitive_context.rs"
replace_once(
    CONTEXT,
    "use std::time::SystemTime;\n",
    "use std::time::Instant;\nuse std::time::SystemTime;\n",
)
replace_once(
    CONTEXT,
    "use codex_hepta_cognitive_read::ReadIdsResultV1;\n",
    "use codex_hepta_cognitive_read::ReadIdsResultV1;\nuse codex_hepta_cognitive_read::ReadProjectionRecordV1;\n",
)
replace_once(
    CONTEXT,
    "use crate::CognitiveContextSnapshot;\n",
    "use crate::CognitiveContextSnapshot;\nuse crate::cognitive_context_metrics;\n",
)
replace_once(
    CONTEXT,
    '''const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
''',
    '''const MAX_CONTEXT_JSON_BYTES: usize = crate::MAX_COGNITIVE_CONTEXT_BYTES;
const CONTEXT_READ_BINDING_DOMAIN: &[u8] = b"hepta.agentd.cognitive-context-read.v1";
type AdmissionKey = (String, u64, String);

fn admitted_record_index(
    records: &[ReadProjectionRecordV1],
) -> BTreeMap<AdmissionKey, &ReadProjectionRecordV1> {
    records
        .iter()
        .filter_map(|record| {
            record.content_digest.map(|digest| {
                (
                    (
                        record.record_id.as_str().to_string(),
                        record.revision.get(),
                        digest.to_string(),
                    ),
                    record,
                )
            })
        })
        .collect()
}

fn planned_context_encoded_len(
    response: &CognitiveContextSnapshot,
) -> Result<usize, CognitiveStoreError> {
    let zero = Digest32::ZERO.to_string();
    [false, true]
        .into_iter()
        .map(|read_allowed| {
            let mut candidate = response.clone();
            candidate.snapshot_digest = zero.clone();
            candidate.read_digest = zero.clone();
            candidate.plan = Some(CognitiveContextPlan {
                evaluated_context_digest: zero.clone(),
                plan_receipt_digest: zero.clone(),
                read_allowed,
            });
            serde_json::to_vec(&candidate)
                .map(|encoded| encoded.len())
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))
        })
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .max()
        .ok_or_else(|| CognitiveStoreError::Invalid("missing context plan shape".to_string()))
}
''',
)
replace_once(
    CONTEXT,
    ''') -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
''',
    ''') -> Result<CognitiveContextSnapshot, CognitiveContextError> {
    let started = Instant::now();
    cognitive_context_metrics::record_request();
    if query.is_empty() || query.len() > 2048 || !(1..=4).contains(&limit) {
''',
)
replace_once(
    CONTEXT,
    '''        })
        .map_err(map_read_ids_error)?;
    let mut observed = observation.candidates().to_vec();
''',
    '''        })
        .map_err(map_read_ids_error)?;
    cognitive_context_metrics::record_read(
        admission_read.payload_encoded_bytes(),
        admission_read.total_encoded_bytes(),
        admission_read.missing_ids().len(),
    );
    let admission_index = admitted_record_index(admission_read.records());
    let mut observed = observation.candidates().to_vec();
''',
)
replace_once(
    CONTEXT,
    '''        let accepted = admission_read.records().iter().any(|record| {
            record.is_live()
                && record.record_id.as_str() == binding.memory.memory_id.as_str()
                && record.revision.get() == binding.memory.revision
                && record
                    .content_digest
                    .is_some_and(|digest| digest.to_string() == binding.content_sha256.as_str())
                && binding.scope == scope
        });
''',
    '''        let admission_key = (
            binding.memory.memory_id.as_str().to_string(),
            binding.memory.revision,
            binding.content_sha256.as_str().to_string(),
        );
        let accepted = admission_index
            .get(&admission_key)
            .is_some_and(|record| record.is_live())
            && binding.scope == scope;
''',
)
replace_once(
    CONTEXT,
    '''        let RevalidationStatus::Current(explanation) = status else {
            continue;
        };
''',
    '''        let RevalidationStatus::Current(explanation) = status else {
            cognitive_context_metrics::record_revalidation_failure("candidate_not_current");
            continue;
        };
''',
)
replace_once(
    CONTEXT,
    '''        let accepted = admission_read.records().iter().any(|record| {
            record.is_live()
                && record.record_id.as_str() == memory.id.memory_id.as_str()
                && record.revision.get() == memory.id.revision
                && record
                    .content_digest
                    .is_some_and(|digest| digest.to_string() == memory.content_sha256.as_str())
                && memory.scope == scope
        });
''',
    '''        let admission_key = (
            memory.id.memory_id.as_str().to_string(),
            memory.id.revision,
            memory.content_sha256.as_str().to_string(),
        );
        let accepted = admission_index
            .get(&admission_key)
            .is_some_and(|record| record.is_live())
            && memory.scope == scope;
''',
)
replace_once(
    CONTEXT,
    '''        let encoded_bytes = serde_json::to_vec(&response)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?
            .len();
        if encoded_bytes > MAX_CONTEXT_JSON_BYTES - 1024 {
            response.items.pop();
            continue;
        }
''',
    '''        let encoded_bytes = planned_context_encoded_len(&response)?;
        if encoded_bytes > MAX_CONTEXT_JSON_BYTES {
            response.items.pop();
            cognitive_context_metrics::record_budget_rejection();
            continue;
        }
''',
)
replace_once(
    CONTEXT,
    '''    store
        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)
        .await?;
''',
    '''    store
        .revalidate_lane_c_snapshot(&access, &scope, &cut, now_seconds()?)
        .await
        .map_err(|error| {
            cognitive_context_metrics::record_stale_cut_rejection();
            error
        })?;
''',
)
replace_once(
    CONTEXT,
    '''    Ok(response)
}

#[cfg(test)]
pub(crate) async fn revalidate(
''',
    '''    cognitive_context_metrics::record_selected(response.items.len());
    cognitive_context_metrics::record_latency(started.elapsed().as_micros());
    Ok(response)
}

#[cfg(test)]
mod budget_tests {
    use super::*;

    #[test]
    fn planned_budget_accounts_for_the_complete_envelope() {
        let response = CognitiveContextSnapshot {
            snapshot_digest: Digest32::ZERO.to_string(),
            read_digest: Digest32::ZERO.to_string(),
            omitted_records: 0,
            items: vec![CognitiveContextItem {
                memory_id: "memory:budget".to_string(),
                revision: 1,
                content: "payload".to_string(),
                content_sha256: Digest32::of_bytes(b"payload").to_string(),
            }],
            plan: None,
        };
        let planned = planned_context_encoded_len(&response).expect("planned length");
        let zero = Digest32::ZERO.to_string();
        let actual = [false, true]
            .into_iter()
            .map(|read_allowed| {
                let mut candidate = response.clone();
                candidate.snapshot_digest = zero.clone();
                candidate.read_digest = zero.clone();
                candidate.plan = Some(CognitiveContextPlan {
                    evaluated_context_digest: zero.clone(),
                    plan_receipt_digest: zero.clone(),
                    read_allowed,
                });
                serde_json::to_vec(&candidate).expect("serialize").len()
            })
            .max()
            .expect("shape");
        assert_eq!(planned, actual);
        assert!(planned < MAX_CONTEXT_JSON_BYTES);
    }
}

#[cfg(test)]
pub(crate) async fn revalidate(
''',
)

print("cognitive.read Agentd hardening applied")
