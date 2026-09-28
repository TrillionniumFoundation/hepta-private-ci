#!/usr/bin/env python3
"""Materialize the exact reviewed Agentd strict-lint source delta."""

from __future__ import annotations

import base64
import hashlib
import pathlib
import subprocess
import tempfile
import zlib

EXPECTED_SOURCE = "14ceaff8a398ef8bbb02ac8a98a8777fdd2fa3a2"
EXPECTED_TREE = "202224e6a820252edf49a69fd8eda1d1e401be44"
EXPECTED_PATCH_SHA256 = "1a757c1d174cff0d3f556be1088e1771efbe0f725fc23aaf4437e746f8ca30ff"
EXPECTED_FILES = {'codex-rs/hepta-agentd/src/automation_effect_host.rs': 'b03da24ce3a82b8dc41e741e2b3884dea1a088c8',
 'codex-rs/hepta-agentd/src/cognitive_context.rs': '7dd522c3b175243116192a21fbfa8a8a2d0eac52',
 'codex-rs/hepta-agentd/src/cognitive_context_hnmf_tests.rs': '30ec047a1ad6e7cc75ea47029044e638f70b1cb3',
 'codex-rs/hepta-agentd/src/cognitive_retrieval_learning.rs': 'fe78ad29258f0b578bb66e393616f9302115b6b6',
 'codex-rs/hepta-agentd/src/intelligence_durable_neuron.rs': 'ea18f41da1563df6aca18d7258f9cd8839e61ddc',
 'codex-rs/hepta-agentd/src/intelligence_product.rs': 'd2ed9bc10b0b0c217c91aac3f59d9eb9715941fc',
 'codex-rs/hepta-agentd/src/intelligence_product_runner.rs': '684273e7340f1d9f903951cfa3e4f664fa9fa565',
 'codex-rs/hepta-agentd/src/lib.rs': 'e5a425fe3422dece8c4915984bae67880346110d',
 'codex-rs/hepta-agentd/src/plasticity_host.rs': '79c7d2a07bd7984571deb815fbb1167b6d9b4907',
 'codex-rs/hepta-agentd/src/plasticity_learning_producer.rs': None,
 'codex-rs/hepta-agentd/src/plasticity_runtime.rs': '656d7564b23e4d4e266c4449b283e8aa336c6bf4',
 'codex-rs/hepta-agentd/src/state.rs': 'b8e6b35836475c94c8ed7c636bf00778a193a2ac',
 'codex-rs/hepta-agentd/src/state_control.rs': 'ae5674e6d811fe6cfb523e7bffff705bf9c44509'}
PATCH_ZLIB_B64 = """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
"""


def run(*args: str, input_bytes: bytes | None = None) -> str:
    completed = subprocess.run(
        args,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.decode("utf-8", errors="strict").strip()


def main() -> None:
    if run("git", "rev-parse", "HEAD") != EXPECTED_SOURCE:
        raise SystemExit("wrong source commit")
    if run("git", "rev-parse", "HEAD^{tree}") != EXPECTED_TREE:
        raise SystemExit("wrong source tree")
    if run("git", "status", "--porcelain=v1", "--untracked-files=all"):
        raise SystemExit("source checkout is not clean")

    patch = zlib.decompress(base64.b64decode("".join(PATCH_ZLIB_B64.split())))
    if hashlib.sha256(patch).hexdigest() != EXPECTED_PATCH_SHA256:
        raise SystemExit("embedded patch digest mismatch")

    with tempfile.NamedTemporaryFile(prefix="hepta-agentd-closeout-", suffix=".patch") as handle:
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
