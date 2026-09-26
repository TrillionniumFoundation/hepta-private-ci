#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{relative}: expected one match, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))


def replace_exact_count(relative: str, old: str, new: str, expected: int) -> None:
    path = ROOT / relative
    text = path.read_text()
    count = text.count(old)
    if count != expected:
        raise RuntimeError(f"{relative}: expected {expected} matches, found {count}: {old!r}")
    path.write_text(text.replace(old, new))


# Existing lifecycle tests must use the same canonical fence now enforced by
# the coordinator.
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "fn composition() -> RuntimeComposition {",
    "fn expected_fence() -> String {\n    composition().expected_run_fence_digest()\n}\n\nfn composition() -> RuntimeComposition {",
)
replace_exact_count(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "fence_digest: digest('9'),",
    "fence_digest: expected_fence(),",
    2,
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "assert_eq!(receipt.fence_digest, digest('9'));",
    "assert_eq!(receipt.fence_digest, expected_fence());",
)
replace_exact_count(
    "codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs",
    "fence_digest: d(\"fence\"),",
    "fence_digest: expected_fence().parse().expect(\"canonical run fence\"),",
    2,
)
replace_once(
    "codex-rs/hepta-agentd/src/lane_b_runtime.rs",
    "#[cfg(test)]\n#[path = \"lane_b_runtime_tests.rs\"]\nmod tests;",
    "#[cfg(test)]\n#[path = \"lane_b_runtime_tests.rs\"]\nmod tests;\n\n#[cfg(test)]\n#[path = \"lane_b_identity_tests.rs\"]\nmod identity_tests;",
)

# Make the malicious-owner case configurable without copying the whole fixture.
replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    "    wrong_owner: Option<CanonicalStageV1>,\n}",
    "    wrong_owner: Option<CanonicalStageV1>,\n    selected_candidate: StableId,\n}",
)
replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    "            wrong_owner: None,\n        }",
    "            wrong_owner: None,\n            selected_candidate: id(\"action:one\"),\n        }",
)
replace_once(
    "codex-rs/hepta-intelligence/src/canonical_tests.rs",
    "candidate_id: id(\"action:one\"),\n                propensity: ProbabilityQ32::ONE,",
    "candidate_id: self.selected_candidate.clone(),\n                propensity: ProbabilityQ32::ONE,",
)
path = ROOT / "codex-rs/hepta-intelligence/src/canonical_tests.rs"
text = path.read_text()
addition = r'''

#[test]
fn malicious_intuition_cannot_select_outside_the_legal_candidate_set() {
    let request = request();
    let mut oracle = Oracle::new(&request.snapshot);
    let mut ports = Ports::new();
    ports.selected_candidate = id("action:not-legal");
    assert_eq!(
        prepare_intelligence_run(request, &mut ports, &mut oracle)
            .expect_err("out-of-set selection must fail closed"),
        CanonicalIntelligenceError::SelectedCandidateNotLegal(id("action:not-legal"))
    );
}
'''
if "malicious_intuition_cannot_select_outside_the_legal_candidate_set" not in text:
    path.write_text(text + addition)
