from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PURITY_DOCUMENT = (
    ROOT / "docs/modules/channel.matrix/SOURCE_PURITY_AND_CANDIDATE_FREEZE.md"
)
REVIEW_SLICES = ROOT / "docs/modules/channel.matrix/REVIEW_SLICES.json"

TRANSIENT_MUTATION_PATHS = (
    ".github/channel-matrix-repair.py",
    ".github/workflows/channel-matrix-bootstrap.yml",
    ".github/workflows/channel-matrix-closure-apply.yml",
    ".github/workflows/channel-matrix-hardening-apply.yml",
    ".github/workflows/channel-matrix-ops-evidence-finalize.yml",
    ".github/workflows/channel-matrix-source-export.yml",
    ".matrix-staging",
    "scripts/channel_matrix_full_patch.py.gz.b64",
    "scripts/channel_matrix_preserve_unknown_patch.py",
)

# These pre-existing workflows require repository write scope for CLA, release,
# or isolated integration-branch publication. The inventory is deliberately
# closed: a newly named write-capable workflow fails until it receives an
# explicit non-Matrix security review and is added here by an ordinary commit.
WRITE_PERMISSION_WORKFLOWS = frozenset(
    {
        ".github/workflows/cla.yml",
        ".github/workflows/rust-release-prepare.yml",
        ".github/workflows/rust-release-zsh.yml",
        ".github/workflows/rust-release.yml",
        ".github/workflows/rusty-v8-release.yml",
        ".github/workflows/single-main-consolidation.yml",
        ".github/workflows/single-main-foundation.yml",
    }
)
WRITE_PERMISSION_PATTERN = re.compile(
    r"(?m)^\s*(?:contents:\s*write|permissions:\s*write-all)\s*(?:#.*)?$"
)

MATRIX_QUALIFICATION_MARKERS = (
    "channel-matrix-",
    "channel.matrix repository qualification",
    "codex/channel-matrix-full-closure-",
    "scripts/channel_matrix_",
    "scripts/verify_channel_matrix_candidate.py",
)

MATRIX_SOURCE_MARKERS = (
    "codex-rs/hepta-matrix-",
    "codex-rs/hepta-supervisor/src/matrix.rs",
    "docs/modules/channel.matrix",
    "scripts/channel_matrix_",
    "scripts/verify_channel_matrix_candidate.py",
)

SOURCE_AUTHORING_PATTERNS = (
    re.compile(r"\bcontents:\s*write\b"),
    re.compile(r"\bwrite-all\b"),
    re.compile(r"\bgit\s+commit(?!-tree)\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bpush\s+origin\b"),
    re.compile(r"\bclippy\s+--fix\b"),
    re.compile(r"\bbase64\s+(?:--decode|-d)\b"),
    re.compile(r"\bgzip\s+-dc\b"),
    re.compile(r"\.matrix-staging"),
    re.compile(r"channel-matrix-repair\.py"),
    re.compile(r"channel_matrix_full_patch"),
)


def tracked_paths() -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    return tuple(
        value.decode("utf-8")
        for value in completed.stdout.split(b"\0")
        if value
    )


def source_authoring_matches(text: str) -> tuple[str, ...]:
    return tuple(
        pattern.pattern
        for pattern in SOURCE_AUTHORING_PATTERNS
        if pattern.search(text)
    )


def workflow_sources() -> dict[str, str]:
    workflow_root = ROOT / ".github/workflows"
    workflows = sorted([*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")])
    return {
        workflow.relative_to(ROOT).as_posix(): workflow.read_text(encoding="utf-8")
        for workflow in workflows
    }


class ChannelMatrixSourcePurityTests(unittest.TestCase):
    def test_transient_mutation_paths_are_absent(self) -> None:
        for relative in TRANSIENT_MUTATION_PATHS:
            with self.subTest(path=relative):
                self.assertFalse(
                    (ROOT / relative).exists(),
                    f"transient Matrix source mutation path returned: {relative}",
                )

    def test_tracked_matrix_patch_bundles_are_absent(self) -> None:
        forbidden = []
        for path in tracked_paths():
            lowered = path.lower()
            if path == ".matrix-staging" or path.startswith(".matrix-staging/"):
                forbidden.append(path)
                continue
            if "channel_matrix" not in lowered and "channel-matrix" not in lowered:
                continue
            if (
                lowered.endswith(".gz.b64")
                or re.search(r"\.part[0-9]+$", lowered)
                or "full_patch" in lowered
                or "preserve_unknown_patch" in lowered
                or lowered.endswith("-repair.py")
            ):
                forbidden.append(path)
        self.assertEqual(
            forbidden,
            [],
            f"tracked Matrix patch/staging payloads are forbidden: {forbidden}",
        )

    def test_authoritative_matrix_workflows_are_read_only(self) -> None:
        workflow_root = ROOT / ".github/workflows"
        workflows = sorted(workflow_root.glob("channel-matrix-*.yml"))
        self.assertTrue(workflows, "no authoritative Matrix workflow was found")
        for workflow in workflows:
            with self.subTest(path=workflow.relative_to(ROOT).as_posix()):
                text = workflow.read_text(encoding="utf-8")
                self.assertIn("permissions:\n  contents: read", text)
                self.assertNotIn("contents: write", text)
                self.assertNotIn("git commit", text)
                self.assertNotIn("push origin", text)
                self.assertNotIn("--allow-dirty", text)

    def test_filename_independent_matrix_workflow_closure(self) -> None:
        workflows = workflow_sources()
        qualification_workflows = 0
        source_touching_workflows = 0
        for relative, text in workflows.items():
            identity = f"{Path(relative).name}\n{text}"
            qualification = any(
                marker in identity for marker in MATRIX_QUALIFICATION_MARKERS
            )
            source_touch = any(marker in text for marker in MATRIX_SOURCE_MARKERS)
            if qualification:
                qualification_workflows += 1
                with self.subTest(kind="qualification", path=relative):
                    self.assertIn("permissions:\n  contents: read", text)
                    self.assertEqual(
                        source_authoring_matches(text),
                        (),
                        "a Matrix qualification workflow may not author source",
                    )
                    self.assertNotIn("pull_request_target:", text)
                    if "uses: actions/checkout@" in text:
                        self.assertIn("persist-credentials: false", text)
            if source_touch:
                source_touching_workflows += 1
                with self.subTest(kind="source-touch", path=relative):
                    self.assertEqual(
                        source_authoring_matches(text),
                        (),
                        "a workflow touching Matrix source may not contain "
                        "source-authoring machinery",
                    )
                    self.assertNotIn("pull_request_target:", text)
        self.assertGreaterEqual(
            qualification_workflows,
            2,
            "the closed-world scan did not find both Matrix qualification workflows",
        )
        self.assertGreaterEqual(
            source_touching_workflows,
            2,
            "the closed-world scan did not find both Matrix source-touching workflows",
        )

    def test_repository_write_permission_inventory_is_closed_and_matrix_disjoint(self) -> None:
        workflows = workflow_sources()
        observed = {
            relative
            for relative, text in workflows.items()
            if WRITE_PERMISSION_PATTERN.search(text)
        }
        self.assertEqual(
            observed,
            WRITE_PERMISSION_WORKFLOWS,
            "repository write permission workflow inventory changed without review",
        )
        forbidden_markers = tuple(
            dict.fromkeys(
                (
                    *MATRIX_QUALIFICATION_MARKERS,
                    *MATRIX_SOURCE_MARKERS,
                    ".matrix-staging",
                    "channel_matrix_",
                )
            )
        )
        for relative in sorted(observed):
            text = workflows[relative]
            for marker in forbidden_markers:
                with self.subTest(path=relative, marker=marker):
                    self.assertNotIn(
                        marker,
                        text,
                        "a write-capable repository workflow may not target Matrix "
                        "qualification or source roots",
                    )

    def test_source_purity_contract_is_executable(self) -> None:
        self.assertTrue(SOURCE_PURITY_DOCUMENT.is_file())
        text = SOURCE_PURITY_DOCUMENT.read_text(encoding="utf-8")
        markers = (
            "Filename-independent classification",
            "closed writable-workflow allowlist",
            "`contents: read`",
            "`persist-credentials: false`",
            "branch alias is navigation only",
            "real merge SHA",
            "production qualification remains external",
            "scripts/tests/test_channel_matrix_closure_workflow.py",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_source_purity_files_are_in_qualification_review_slice(self) -> None:
        registry = json.loads(REVIEW_SLICES.read_text(encoding="utf-8"))
        rows = {
            row["id"]: row
            for row in registry.get("slices", [])
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        qualification = rows["06-qualification-evidence"]
        self.assertIn(
            "docs/modules/channel.matrix/SOURCE_PURITY_AND_CANDIDATE_FREEZE.md",
            qualification["paths"],
        )
        self.assertIn(
            "scripts/tests/test_channel_matrix_closure_workflow.py",
            qualification["paths"],
        )
        self.assertIn(
            "workflow_source_authoring_is_closed",
            qualification["invariants"],
        )

    def test_repository_qualification_binds_provenance_and_readiness(self) -> None:
        workflow = ROOT / ".github/workflows/channel-matrix-preserve-unknown.yml"
        text = workflow.read_text(encoding="utf-8")
        labels = "compile api-compile-fail focused-tests clippy format"
        policy = (ROOT / "scripts/channel_matrix_evidence_v2.py").read_text(
            encoding="utf-8"
        )
        focused_gate = ROOT / "scripts/channel_matrix_focused_gate.py"
        self.assertIn("name: channel.matrix repository qualification", text)
        self.assertEqual(text.count(f"for label in {labels}; do"), 2)
        self.assertIn("scripts/channel_matrix_evidence_v2.py", text)
        self.assertIn("scripts/channel_matrix_pair_acceptance_v2.py", text)
        self.assertIn('"focused-tests": FOCUSED_GATE_COMMAND', policy)
        self.assertIn("channel_matrix_focused_gate.py", policy)
        self.assertTrue(focused_gate.is_file())
        self.assertEqual(text.count("channel_matrix_source_provenance.py"), 2)
        self.assertIn("channel_matrix_readiness.py", text)
        self.assertIn(
            "channel-matrix-readiness-${{ github.run_id }}-${{ github.run_attempt }}",
            text,
        )
        self.assertIn("READINESS_RESULT", text)
        self.assertIn("GITHUB_MERGE_SHA", text)
        self.assertIn("FINAL_MERGE_SHA", text)
        self.assertNotIn(
            "$RUNNER_TEMP/matrix-source-head/api-compile-fail.log",
            text,
        )
        self.assertNotIn(
            "$RUNNER_TEMP/matrix-base-merge/api-compile-fail.log",
            text,
        )
        self.assertNotIn(
            "python3 -m unittest discover -s scripts/tests",
            text,
        )
        self.assertNotIn(
            "cargo test --locked -p codex-hepta-matrix-sdk --doc 2>&1 | tee",
            text,
        )


if __name__ == "__main__":
    unittest.main()
