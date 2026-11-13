#!/usr/bin/env python3
"""Deterministic fixups around the temporary runtime.codex bootstrap.

The main bootstrap is generated against an exact source snapshot.  These small
fixups keep that patch readable while preserving legacy journal compatibility
and covering source-shape differences found by validation.  Both scripts are
removed by the workflow after the resulting source passes focused tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    value = path.read_text(encoding="utf-8")
    count = value.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one occurrence, found {count}")
    path.write_text(value.replace(old, new, 1), encoding="utf-8")


def pre() -> None:
    path = ROOT / "scripts/bootstrap_runtime_codex_hardening.py"
    value = path.read_text(encoding="utf-8")
    replacements = (
        (
            '"use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\\n",',
            '"pub use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\\n",',
        ),
        (
            '"use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\\nuse codex_hepta_infer_core',
            '"pub use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;\\nuse codex_hepta_infer_core',
        ),
        (
            "\n    6,\n)\n# Two branches use a temporary `stopped` result",
            "\n    7,\n)\n# Two branches use a temporary `stopped` result",
        ),
        (
            'codex_authority_witness_sha256: Some(\\"f\\".repeat(64)),',
            'codex_authority_witness_sha256: Some(\\"1\\".repeat(64)),',
        ),
    )
    for old, new in replacements:
        count = value.count(old)
        if count != 1:
            raise RuntimeError(f"pre-fixup anchor mismatch ({count}): {old[:96]!r}")
        value = value.replace(old, new, 1)
    path.write_text(value, encoding="utf-8")


def post() -> None:
    native = ROOT / "codex-rs/hepta-infer-core/src/native_control.rs"
    replace_once(
        native,
        "        proof: NativePreEffectAbortProof,\n    },\n    Observe {",
        "        #[serde(default)]\n        proof: Option<NativePreEffectAbortProof>,\n    },\n    Observe {",
        "legacy event proof field",
    )
    replace_once(
        native,
        "                proof: proof.clone(),\n            },",
        "                proof: Some(proof.clone()),\n            },",
        "new abort event proof",
    )
    replace_once(
        native,
        """                validate_pre_effect_abort_proof(record, &proof)?;
                record.pre_dispatch_stop = Some(reason);
                record.pre_effect_abort_proof = Some(proof);
                record.state = NativeReservationState::Released;""",
        """                if let Some(proof) = proof {
                    validate_pre_effect_abort_proof(record, &proof)?;
                    record.pre_effect_abort_proof = Some(proof);
                }
                record.pre_dispatch_stop = Some(reason);
                record.state = NativeReservationState::Released;""",
        "legacy abort replay",
    )

    tests = ROOT / "codex-rs/hepta-infer-worker-host/src/native_run_control_tests.rs"
    replace_once(
        tests,
        """                codex_authority_witness_sha256: None,
            },""",
        """                codex_authority_witness_sha256: None,
                pre_effect_abort_commitment_sha256: None,
            },""",
        "legacy dispatch fixture",
    )

    caller = ROOT / "codex-rs/hepta-infer-worker-host/src/native_app_server.rs"
    replace_once(
        caller,
        ") -> bool {\n    receipt.phase == AgentRunPhase::Cancelled",
        ") -> bool {\n    let proof_sha256 = proof.proof_sha256();\n    receipt.phase == AgentRunPhase::Cancelled",
        "abort receipt proof lifetime",
    )
    replace_once(
        caller,
        "== Some(proof.proof_sha256().as_str())",
        "== Some(proof_sha256.as_str())",
        "abort receipt proof comparison",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("pre", "post"))
    args = parser.parse_args()
    if args.phase == "pre":
        pre()
    else:
        post()


if __name__ == "__main__":
    main()
