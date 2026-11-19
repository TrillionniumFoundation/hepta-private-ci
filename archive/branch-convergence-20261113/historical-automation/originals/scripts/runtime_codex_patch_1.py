from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one replacement, found {count}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def insert_before(path: str, marker: str, addition: str) -> None:
    text = read(path)
    count = text.count(marker)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one insertion marker, found {count}: {marker[:100]!r}")
    write(path, text.replace(marker, addition + marker, 1))


def append_once(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    if not text.endswith("\n"):
        text += "\n"
    write(path, text + addition)


# ---------------------------------------------------------------------------
# Native durable control: add an unpersisted random nonce to the one-shot
# pre-effect proof, and expose only a domain-separated witness digest.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-infer-core/Cargo.toml",
    "serde_json = { workspace = true }\n",
    "rand = { workspace = true }\nserde_json = { workspace = true }\nsha2 = { workspace = true }\n",
)

replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "use std::collections::BTreeMap;\n\nuse serde::Deserialize;\n",
    "use std::collections::BTreeMap;\n\nuse rand::RngCore;\nuse serde::Deserialize;\nuse sha2::Digest;\nuse sha2::Sha256;\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    dispatch_revision: u64,\n}\n",
    "pub struct NativePreEffectAbortToken {\n    request_id: String,\n    dispatch_revision: u64,\n    /// Process-local entropy. It is never persisted, cloned or serialized, so\n    /// restart cannot recreate an abort authority for a possibly sent effect.\n    nonce: [u8; 32],\n}\n",
)
insert_before(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]\n#[serde(rename_all = \"snake_case\")]\npub enum NativeDispatchRejectionStatus",
    "impl NativePreEffectAbortToken {\n    /// Return an opaque witness for a caller-supplied exact effect binding.\n    /// The random nonce is deliberately absent from durable state.\n    pub fn witness_sha256(&self, binding: &[u8]) -> [u8; 32] {\n        let mut digest = Sha256::new();\n        digest.update(b\"hepta.native.pre-effect-abort.v1\");\n        digest.update((self.request_id.len() as u64).to_be_bytes());\n        digest.update(self.request_id.as_bytes());\n        digest.update(self.dispatch_revision.to_be_bytes());\n        digest.update(self.nonce);\n        digest.update((binding.len() as u64).to_be_bytes());\n        digest.update(binding);\n        digest.finalize().into()\n    }\n}\n\n",
)
replace_once(
    "codex-rs/hepta-infer-core/src/native_control.rs",
    "        Ok((\n            record.clone(),\n            NativePreEffectAbortToken {\n                request_id: request_id.to_string(),\n                dispatch_revision: record.revision,\n            },\n        ))\n",
    "        let mut nonce = [0_u8; 32];\n        rand::rng().fill_bytes(&mut nonce);\n        Ok((\n            record.clone(),\n            NativePreEffectAbortToken {\n                request_id: request_id.to_string(),\n                dispatch_revision: record.revision,\n                nonce,\n            },\n        ))\n",
)
append_once(
    "codex-rs/hepta-infer-core/src/native_control_tests.rs",
    "pre_effect_abort_witness_is_process_local_and_binding_specific",
    r'''

#[test]
fn pre_effect_abort_witness_is_process_local_and_binding_specific() {
    let path = path("abort-witness");
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(request("r1"), 1).unwrap();
    let (_, first) = control
        .dispatch_native_with_pre_effect_abort("r1", dispatch())
        .unwrap();
    let a = first.witness_sha256(b"binding-a");
    let b = first.witness_sha256(b"binding-b");
    assert_ne!(a, b);

    control
        .abort_native_before_effect(first, "local proof consumed".to_string())
        .unwrap();
    drop(control);

    // Reopen can observe the released result but cannot recreate the token or
    // derive either witness from durable state.
    let reopened = DurableInferenceControl::open(&path, 8).unwrap();
    assert_eq!(
        reopened.native_record("r1").unwrap().state,
        NativeReservationState::Released
    );
    drop(reopened);
    std::fs::remove_file(path).unwrap();
}
''',
)

# ---------------------------------------------------------------------------
# Agentd wire protocol: exact dispatch permit, effect entry, and pre-effect
# abort operations. Existing RunMarkDispatched remains for compatibility but
# cannot mint an abort permit.
# ---------------------------------------------------------------------------
replace_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 1;\n",
    "pub const AGENTD_RUN_LIFECYCLE_CAPABILITY_MINOR: u16 = 2;\n",
)
insert_before(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    pub fn run_cancel(\n",
    r'''    pub fn run_mark_dispatched_with_abort(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunMarkDispatchedWithAbort {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            },
        }
    }

    pub fn run_enter_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunEnterEffect {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
            },
        }
    }

    pub fn run_abort_before_effect(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAbortBeforeEffect {
                run_id,
                expected_revision,
                pre_effect_abort_digest,
                reason,
            },
        }
    }

''',
)
insert_before(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "    RunCancel {\n",
    r'''    RunMarkDispatchedWithAbort {
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    },
    RunEnterEffect {
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
    },
    RunAbortBeforeEffect {
        run_id: String,
        expected_revision: u64,
        pre_effect_abort_digest: String,
        reason: String,
    },
''',
)
append_once(
    "codex-rs/hepta-agent-protocol/src/lib.rs",
    "runtime_codex_pre_effect_protocol_round_trips",
    r'''

#[cfg(test)]
mod runtime_codex_pre_effect_protocol_tests {
    use super::*;

    #[test]
    fn runtime_codex_pre_effect_protocol_round_trips() {
        let digest = "a".repeat(64);
        for request in [
            AgentdRequest::run_mark_dispatched_with_abort(
                1,
                2,
                "run.1".to_string(),
                3,
                digest.clone(),
            ),
            AgentdRequest::run_enter_effect(
                2,
                2,
                "run.1".to_string(),
                4,
                digest.clone(),
            ),
            AgentdRequest::run_abort_before_effect(
                3,
                2,
                "run.1".to_string(),
                4,
                digest,
                "final fence changed".to_string(),
            ),
        ] {
            let encoded = serde_json::to_vec(&request).unwrap();
            let decoded: AgentdRequest = serde_json::from_slice(&encoded).unwrap();
            assert_eq!(decoded, request);
        }
    }
}
''',
)
