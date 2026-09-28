#!/usr/bin/env python3
"""Apply the exact, reviewable prompt.registry product-lint closeout patch."""

from pathlib import Path


def prepend_inner_attribute(path: str, attribute: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if source.startswith(attribute):
        return
    if source.startswith("#!["):
        raise SystemExit(f"unexpected existing inner attribute in {target}")
    target.write_text(attribute + source, encoding="utf-8")


canonical = Path("codex-rs/hepta-intelligence/src/canonical.rs")
text = canonical.read_text(encoding="utf-8")
old = "#[derive(Clone, Debug, Eq, PartialEq)]\npub enum CanonicalRunOutcomeV1 {\n"
new = (
    "#[derive(Clone, Debug, Eq, PartialEq)]\n"
    "#[expect(\n"
    "    clippy::large_enum_variant,\n"
    "    reason = \"V1 is a public compatibility contract; boxing Ready would break existing Rust callers. Revisit indirection in a separately versioned outcome after measurement.\"\n"
    ")]\n"
    "pub enum CanonicalRunOutcomeV1 {\n"
)
if text.count(old) != 1:
    raise SystemExit("expected exactly one CanonicalRunOutcomeV1 declaration anchor")
canonical.write_text(text.replace(old, new), encoding="utf-8")

prepend_inner_attribute(
    "codex-rs/hepta-intelligence/examples/intuition_authenticated_fast_gate.rs",
    "#![allow(\n"
    "    clippy::expect_used,\n"
    "    reason = \"This qualification example uses fixed repository-owned fixtures; invalid fixtures must abort instead of emitting partial benchmark evidence.\"\n"
    ")]\n\n",
)
prepend_inner_attribute(
    "codex-rs/hepta-intelligence/src/ndu_stochastic_admission_tests.rs",
    "#![allow(\n"
    "    clippy::expect_used,\n"
    "    reason = \"These tests intentionally fail immediately when fixed repository-owned fixtures violate their declared invariants.\"\n"
    ")]\n\n",
)
prepend_inner_attribute(
    "codex-rs/hepta-intelligence/tests/intuition_frozen_qualification.rs",
    "#![allow(\n"
    "    clippy::unwrap_used,\n"
    "    reason = \"This qualification test parses fixed repository-owned model and dataset fixtures; malformed fixtures must fail the test immediately.\"\n"
    ")]\n\n",
)
