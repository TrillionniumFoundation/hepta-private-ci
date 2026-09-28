#!/usr/bin/env python3
"""Materialize the exact reviewed unified-evolution closeout source delta."""

from __future__ import annotations

import argparse
import base64
import hashlib
import pathlib
import subprocess
import tempfile
import zlib

EXPECTED_SOURCE = "14ceaff8a398ef8bbb02ac8a98a8777fdd2fa3a2"
EXPECTED_TREE = "202224e6a820252edf49a69fd8eda1d1e401be44"
EXPECTED_PATCH_SHA256 = "47ba60aab89186a380eb5b6169a9b908f48d6888883b1ce5c03b6250a7d60ffd"
EXPECTED_FILES = {'.github/workflows/hepta-architecture-convergence.yml': '8df636cad4fea545645a33ea9ea2cd3251b1036a',
 'codex-rs/hepta-agentd/src/automation_effect_host.rs': '9d917973eec800de54f8ab5717a56cbbd06a3c67',
 'codex-rs/hepta-agentd/src/cognitive_context.rs': '9ae9ba8f395fccac0f45f0a185d8ac6c5d6378c3',
 'codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs': '30ec047a1ad6e7cc75ea47029044e638f70b1cb3',
 'codex-rs/hepta-agentd/src/cognitive_retrieval_learning.rs': 'fe78ad29258f0b578bb66e393616f9302115b6b6',
 'codex-rs/hepta-agentd/src/intelligence_durable_neuron.rs': 'ea18f41da1563df6aca18d7258f9cd8839e61ddc',
 'codex-rs/hepta-agentd/src/intelligence_product.rs': 'd2ed9bc10b0b0c217c91aac3f59d9eb9715941fc',
 'codex-rs/hepta-agentd/src/intelligence_product_runner.rs': 'c0ab66dfd6f8e7537edc5340034a72ddcb669dc4',
 'codex-rs/hepta-agentd/src/lib.rs': 'e5a425fe3422dece8c4915984bae67880346110d',
 'codex-rs/hepta-agentd/src/plasticity_host.rs': '79c7d2a07bd7984571deb815fbb1167b6d9b4907',
 'codex-rs/hepta-agentd/src/plasticity_learning_producer.rs': None,
 'codex-rs/hepta-agentd/src/plasticity_runtime.rs': '656d7564b23e4d4e266c4449b283e8aa336c6bf4',
 'codex-rs/hepta-agentd/src/state.rs': 'b8e6b35836475c94c8ed7c636bf00778a193a2ac',
 'codex-rs/hepta-agentd/src/state_control.rs': 'ae5674e6d811fe6cfb523e7bffff705bf9c44509',
 'codex-rs/hepta-operations/src/durable_store.rs': 'f775fe19a1a34ae3be9c47e941207dda256377b0',
 'codex-rs/hepta-operations/src/durable_store_tests.rs': '5208957f6b04264f13905f17da5ddff459502c96',
 'scripts/hepta_repository_controls.py': '0519a228baaf81b9056cc62232d3502dfb54ab8d',
 'scripts/tests/test_hepta_repository_controls.py': 'a5521675e31a1cbdb31e2fe132dddcac62a550b6'}


def run(*args: str) -> str:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.decode("utf-8", errors="strict").strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True, type=pathlib.Path)
    args = parser.parse_args()

    if run("git", "rev-parse", "HEAD") != EXPECTED_SOURCE:
        raise SystemExit("wrong source commit")
    if run("git", "rev-parse", "HEAD^{tree}") != EXPECTED_TREE:
        raise SystemExit("wrong source tree")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all"):
        raise SystemExit("source checkout is not clean")

    try:
        patch = zlib.decompress(
            base64.b64decode("".join(args.payload.read_text().split()), validate=True)
        )
    except (OSError, ValueError, zlib.error) as error:
        raise SystemExit("invalid exact patch payload") from error
    if hashlib.sha256(patch).hexdigest() != EXPECTED_PATCH_SHA256:
        raise SystemExit("patch payload digest mismatch")

    with tempfile.NamedTemporaryFile(prefix="hepta-evolution-closeout-", suffix=".patch") as handle:
        handle.write(patch)
        handle.flush()
        subprocess.run(
            ["git", "apply", "--check", "--whitespace=error-all", handle.name],
            check=True,
        )
        subprocess.run(
            ["git", "apply", "--whitespace=error-all", handle.name],
            check=True,
        )

    subprocess.run(["git", "diff", "--check"], check=True)
    changed = set(run("git", "diff", "--name-only", "--diff-filter=ACDMRTUXB").splitlines())
    if changed != set(EXPECTED_FILES):
        raise SystemExit(f"unexpected changed paths: {sorted(changed)}")

    for path, expected_blob in EXPECTED_FILES.items():
        candidate = pathlib.Path(path)
        if expected_blob is None:
            if candidate.exists():
                raise SystemExit(f"deleted path still exists: {path}")
            continue
        if not candidate.is_file() or candidate.is_symlink():
            raise SystemExit(f"invalid materialized path: {path}")
        actual_blob = run("git", "hash-object", path)
        if actual_blob != expected_blob:
            raise SystemExit(f"blob mismatch for {path}: {actual_blob}")

    print(EXPECTED_PATCH_SHA256)


if __name__ == "__main__":
    main()
