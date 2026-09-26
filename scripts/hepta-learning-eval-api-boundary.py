#!/usr/bin/env python3
"""Verify and compile-test the learning.eval public API boundary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX = ROOT / "codex-rs"
EVAL_ROOT = CODEX / "hepta-intelligence-eval"
LIB = EVAL_ROOT / "src/lib.rs"
FIXTURE = ROOT / "qualification/compile-fail/learning-eval-private-api.rs"
AGENTD = CODEX / "hepta-agentd/src/intelligence_evaluation.rs"
PLASTICITY = CODEX / "hepta-intelligence/src/plasticity_product.rs"
FORBIDDEN = (
    "decide_with_signed_evidence_v2",
    "decide_with_signed_longitudinal_evidence_v3",
)


def fail(message: str) -> None:
    raise SystemExit(f"learning.eval API boundary: {message}")


def read(path: Path) -> str:
    if not path.is_file():
        fail(f"missing required file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def verify() -> None:
    lib = read(LIB)
    required_lib = (
        "mod repository_admission;",
        "pub use repository_admission::admit_repository_evaluation_v1;",
        "pub use repository_admission::RepositoryEvaluationAdmissionV1;",
        "pub use repository_admission::RepositoryEvaluationConsumerV1;",
        "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;",
        "pub(crate) use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;",
    )
    for token in required_lib:
        if token not in lib:
            fail(f"missing lib boundary token: {token}")
    for token in (
        "pub use signed_evaluation::decide_with_signed_evidence_v2;",
        "pub use longitudinal_time::decide_with_signed_longitudinal_evidence_v3;",
    ):
        if token in lib:
            fail(f"raw decision primitive remains public: {token}")

    expected_consumers = {
        AGENTD: (
            "admit_repository_evaluation_v1",
            "RepositoryEvaluationConsumerV1::Agentd",
        ),
        PLASTICITY: (
            "admit_repository_evaluation_v1",
            "RepositoryEvaluationConsumerV1::Plasticity",
        ),
    }
    for path, tokens in expected_consumers.items():
        text = read(path)
        for token in tokens:
            if token not in text:
                fail(f"{path.relative_to(ROOT)} is missing {token}")

    violations: list[str] = []
    for path in CODEX.rglob("*.rs"):
        if path.is_relative_to(EVAL_ROOT):
            continue
        text = path.read_text(encoding="utf-8")
        for symbol in FORBIDDEN:
            if re.search(rf"\b{re.escape(symbol)}\b", text):
                violations.append(f"{path.relative_to(ROOT)}:{symbol}")
    if violations:
        fail("external raw-decision references remain: " + ", ".join(sorted(violations)))

    fixture = read(FIXTURE)
    for symbol in FORBIDDEN:
        if symbol not in fixture:
            fail(f"compile-fail fixture does not reference {symbol}")

    print(
        json.dumps(
            {
                "schema": "hepta.learning-eval.api-boundary.v1",
                "rawDecisionPrimitives": "crate_private",
                "repositoryConsumers": ["agentd", "plasticity"],
                "externalRawReferences": 0,
                "compileFailFixture": str(FIXTURE.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )


def compile_fail() -> None:
    verify()
    subprocess.run(
        [
            "cargo",
            "build",
            "--locked",
            "-p",
            "codex-hepta-intelligence-eval",
        ],
        cwd=CODEX,
        check=True,
    )
    metadata = subprocess.run(
        ["cargo", "metadata", "--no-deps", "--format-version", "1"],
        cwd=CODEX,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    target = Path(json.loads(metadata.stdout)["target_directory"])
    deps = target / "debug/deps"
    libraries = sorted(
        deps.glob("libcodex_hepta_intelligence_eval-*.rlib"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not libraries:
        fail(f"compiled learning.eval rlib missing under {deps}")

    evidence = ROOT / ".hepta-evidence/learning-eval"
    evidence.mkdir(parents=True, exist_ok=True)
    stderr_path = evidence / "private-api-compile-fail.stderr"
    output_path = evidence / "private-api-compile-fail.rmeta"
    command = [
        "rustc",
        str(FIXTURE),
        "--edition=2024",
        "--crate-name=learning_eval_private_api_compile_fail",
        f"--extern=codex_hepta_intelligence_eval={libraries[0]}",
        "-L",
        f"dependency={deps}",
        "--emit=metadata",
        "-o",
        str(output_path),
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stderr_path.write_text(result.stderr, encoding="utf-8")
    if result.returncode == 0:
        fail("external private-API fixture compiled successfully")
    if not any(symbol in result.stderr for symbol in FORBIDDEN):
        fail("compile-fail stderr does not identify the forbidden decision API")
    if not re.search(r"unresolved import|private (function|item)|no .* in the root", result.stderr):
        fail("fixture failed for an unexpected reason")
    output_path.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "schema": "hepta.learning-eval.private-api-compile-fail.v1",
                "status": "expected_failure",
                "returnCode": result.returncode,
                "stderr": str(stderr_path.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "compile-fail"))
    args = parser.parse_args()
    if args.command == "verify":
        verify()
    else:
        compile_fail()


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(f"command failed: {error}", file=sys.stderr)
        raise SystemExit(error.returncode) from error
