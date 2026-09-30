#!/usr/bin/env python3
"""Apply reviewed cognitive.read qualification-governance changes once.

This is an authoring helper, not a qualification program. The one-time workflow
that invokes it deletes this file before publishing the final source candidate.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
QUALIFICATION_WORKFLOW = ROOT / ".github/workflows/cognitive-read-qualification.yml"
PROPOSAL_WORKFLOW = ROOT / ".github/workflows/cognitive-read-lock-refresh.yml"
QUALIFICATION_RUNNER = ROOT / "scripts/run-cognitive-read-qualification.sh"
EVIDENCE = ROOT / "scripts/cognitive_read_evidence.py"
READ_ONLY_TEST = ROOT / "scripts/test_cognitive_read_qualification_read_only.py"
CLOSURE = ROOT / "docs/modules/cognitive.read/QUALIFICATION_CLOSURE.md"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text()
    if body.count(old) != 1:
        raise ValueError(f"authoring shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1))


def make_qualification_read_only() -> None:
    body = QUALIFICATION_WORKFLOW.read_text()
    marker = "\n  source-proposal:\n"
    if body.count(marker) != 1:
        raise ValueError("qualification source-proposal job shape drift")
    QUALIFICATION_WORKFLOW.write_text(body.split(marker, 1)[0].rstrip() + "\n")

    QUALIFICATION_RUNNER.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exec python3 scripts/cognitive_read_full_evidence.py \"$@\"\n"
    )


def make_proposal_manual_only() -> None:
    body = PROPOSAL_WORKFLOW.read_text()
    boundary = body.find("\n# Mutable repair is deliberately separated")
    if boundary < 0:
        raise ValueError("local proposal workflow boundary drift")

    # Replace the event surface as one block rather than matching the previous
    # push/pull-request spelling. Repair authoring may legitimately rename the
    # proposal job, but qualification governance must still force manual-only,
    # credential-free execution.
    body = (
        "name: Cognitive read local source proposal\n\n"
        "on:\n"
        "  workflow_dispatch:\n"
        + body[boundary:]
    )

    jobs_marker = "\njobs:\n"
    if body.count(jobs_marker) != 1:
        raise ValueError("local proposal jobs shape drift")
    jobs_start = body.index(jobs_marker) + len(jobs_marker)
    runs_start = body.find("    runs-on:", jobs_start)
    if runs_start < 0:
        raise ValueError("local proposal runner shape drift")
    condition_start = body.find("    if:", jobs_start, runs_start)
    new_if = (
        "    if: >-\n"
        "      github.repository == 'TrillionniumFoundation/hepta-private-ci' &&\n"
        "      github.event_name == 'workflow_dispatch'\n"
    )
    if condition_start < 0:
        body = body[:runs_start] + new_if + body[runs_start:]
    else:
        body = body[:condition_start] + new_if + body[runs_start:]

    forbidden = ("\n  push:\n", "\n  pull_request:\n", "contents: write", "git push")
    for token in forbidden:
        if token in body:
            raise ValueError(f"local proposal retained forbidden capability: {token!r}")
    if "persist-credentials: false" not in body or "contents: read" not in body:
        raise ValueError("local proposal lost its credential-free read-only boundary")
    PROPOSAL_WORKFLOW.write_text(body)


def bind_receipt_inputs() -> None:
    old = '''        "implementation_map": {"source_base": mapping.get("sourceBase"), "observed_at_head": mapping.get("observedAtHead")},
        "workflow": {key: os.environ.get(key) for key in (
'''
    new = '''        "implementation_map": {"source_base": mapping.get("sourceBase"), "observed_at_head": mapping.get("observedAtHead")},
        "source_inputs": {
            "cargo_lock": {
                "path": "codex-rs/Cargo.lock",
                "sha256": digest(root / "codex-rs/Cargo.lock"),
            },
            "toolchain": (evidence / "toolchain.txt").read_text().splitlines(),
            "nextest": (evidence / "test-runner.log").read_text(errors="replace").splitlines(),
        },
        "workflow": {key: os.environ.get(key) for key in (
'''
    replace_once(EVIDENCE, old, new)


def write_governance_test() -> None:
    READ_ONLY_TEST.write_text(
        '''#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CognitiveReadQualificationReadOnlyTests(unittest.TestCase):
    def test_qualification_workflow_is_read_only(self) -> None:
        body = (ROOT / ".github/workflows/cognitive-read-qualification.yml").read_text()
        self.assertIn("permissions:\\n  contents: read", body)
        self.assertNotIn("source-proposal:", body)
        self.assertNotIn("contents: write", body)
        self.assertNotIn("pull-requests: write", body)
        self.assertNotIn("git commit", body)
        self.assertNotIn("git push", body)
        self.assertNotIn("gh pr", body)

    def test_qualification_entry_point_has_no_repair_sidecar(self) -> None:
        body = (ROOT / "scripts/run-cognitive-read-qualification.sh").read_text()
        self.assertIn("cognitive_read_full_evidence.py", body)
        self.assertNotIn("qualification_with_proposal", body)
        self.assertNotIn("source_proposal", body)

    def test_local_proposal_is_manual_and_credential_free(self) -> None:
        body = (ROOT / ".github/workflows/cognitive-read-lock-refresh.yml").read_text()
        self.assertIn("workflow_dispatch:", body)
        self.assertNotIn("pull_request:", body)
        self.assertNotIn("  push:", body)
        self.assertIn("contents: read", body)
        self.assertIn("persist-credentials: false", body)
        self.assertNotIn("git push", body)

    def test_receipt_binds_lockfile_and_toolchain(self) -> None:
        body = (ROOT / "scripts/cognitive_read_evidence.py").read_text()
        self.assertIn('"cargo_lock"', body)
        self.assertIn('digest(root / "codex-rs/Cargo.lock")', body)
        self.assertIn('"toolchain"', body)
        self.assertIn('"nextest"', body)


if __name__ == "__main__":
    unittest.main()
'''
    )


def update_docs() -> None:
    heading = "## Immutable qualification boundary"
    body = CLOSURE.read_text()
    if heading in body:
        raise ValueError("immutable qualification boundary is already documented")
    CLOSURE.write_text(
        body.rstrip()
        + "\n\n"
        + heading
        + "\n\n"
        + "Exact-head and synthetic-merge qualification are read-only over one checked-out "
          "commit. They do not create commits, push refs, edit the pull request, or generate "
          "a mutable repair tree. The optional source-proposal workflow is manual, "
          "credential-free, and produces only a non-qualification artifact. Each "
          "qualification receipt binds the exact commit and tree, Cargo.lock SHA-256, "
          "Rust/Cargo/just versions, the pinned nextest identity, and the immutable evidence "
          "inventory.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None:
        raise ValueError("expected SHA must be lowercase hexadecimal")
    if git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("qualification-governance authoring requires the exact source")
    if git("status", "--porcelain"):
        raise ValueError("qualification-governance authoring requires a clean checkout")

    make_qualification_read_only()
    make_proposal_manual_only()
    bind_receipt_inputs()
    write_governance_test()
    update_docs()
    subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
