#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().parents[1] / "codex-rs/hepta-ndu/src/evaluator_tests.rs"
text = path.read_text(encoding="utf-8")
start_marker = "fn missing_uncertainty_axis_is_unavailable() {"
next_marker = "\n#[test]\nfn candidate_support_digest_binds_organ_and_contribution_semantics()"
if text.count(start_marker) != 1 or text.count(next_marker) != 1:
    raise SystemExit("NDU uncertainty test anchors are not unique")
start = text.index(start_marker)
end = text.index(next_marker, start)
block = text[start:end]
old = 'assert_eq!(error.code(), "NDU-E003");'
new = 'assert_eq!(error.code(), "NDU-E004");'
if block.count(old) != 1:
    raise SystemExit("NDU uncertainty error assertion did not match exactly once")
text = text[:start] + block.replace(old, new) + text[end:]
path.write_text(text, encoding="utf-8")
print("LANE_D_NDU_ERROR_TAXONOMY_FIX_APPLIED")
