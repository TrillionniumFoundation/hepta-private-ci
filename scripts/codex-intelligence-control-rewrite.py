#!/usr/bin/env python3
"""One-shot exact rewrite for the intelligence.control closure branch.

Every replacement is asserted to occur exactly once. This is intentionally not
an approximate source rewriter: source drift must fail the job rather than
silently editing another control path.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != 1:
        raise SystemExit(f"{path}: expected one rewrite target, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    tests = "codex-rs/hepta-agentd/src/intelligence_product_tests.rs"
    replace_once(
        tests,
        '        supervisor_generation: 1,\n        agentd_generation: 1,',
        '        supervisor_generation: 1,\n        agentd_generation: 2,',
    )
    replace_once(
        tests,
        '        body_generation: generation(7),',
        '        body_generation: generation(2),',
    )
    replace_once(
        tests,
        '    Fixture {\n        request: CanonicalIntelligenceRunRequestV1 {',
        '''    let run_identity = crate::AgentdIntelligenceRunIdentityV1 {
        run_id: id("run:agentd-intelligence"),
        request_digest: digest("durable-run-start-identity"),
        objective_digest,
        body_digest: digest("body"),
        artifact_set_digest: digest("artifact-set"),
        authority_epoch: 11,
        generation: 2,
        fence_digest: crate::objective_run_fence_digest_v1("agent.product", 1, 2),
        deadline_ms: u64::MAX - 1,
    };

    Fixture {
        request: CanonicalIntelligenceRunRequestV1 {''',
    )
    replace_once(
        tests,
        '        inputs: AgentdIntelligenceOwnerInputsV1 {\n            objective_envelope: envelope,',
        '        inputs: AgentdIntelligenceOwnerInputsV1 {\n            run_identity: Some(run_identity),\n            objective_envelope: envelope,',
    )

    replace_once(
        "codex-rs/hepta-agentd/src/state.rs",
        '                let admitted = runs\n                    .start_run(',
        '                let admitted = runs\n                    .start_bound_run(',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/state.rs",
        '''pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    let mut bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}''',
        '''pub(crate) fn objective_run_fence(identity: &AgentdIdentity, current_generation: u64) -> String {
    crate::objective_run_fence_digest_v1(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        current_generation,
    )
    .to_string()
}''',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/objective_runtime.rs",
        '''fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    let mut bytes = b"hepta:agentd:objective-fence:v1\\0".to_vec();
    bytes.extend_from_slice(identity.agent_id.as_str().as_bytes());
    bytes.extend_from_slice(&identity.spawn_generation.to_be_bytes());
    bytes.extend_from_slice(&current_generation.to_be_bytes());
    Digest32::of_bytes(&bytes)
}''',
        '''fn objective_fence(identity: &AgentdIdentity, current_generation: u64) -> Digest32 {
    crate::objective_run_fence_digest_v1(
        identity.agent_id.as_str(),
        identity.spawn_generation,
        current_generation,
    )
}''',
    )
    replace_once(
        "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
        '        self.start_run(\n            now_ms,\n            RunSnapshot {',
        '        self.start_bound_run(\n            now_ms,\n            RunSnapshot {',
    )


if __name__ == "__main__":
    main()
