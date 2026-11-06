#!/usr/bin/env python3
"""Additional ordinary NPQ6 gates. Original paired gates run separately unchanged.

Both builds precede every exported signed fixture. Each exact ignored test gets
its own new output root and environment; no expiry renewal or cached material.
"""

import argparse
import json
import os
from pathlib import Path
import sys

import hepta_ci_exec as original
from hepta_ci_ordinary_npq6_support_v1 import (
    CHAIN_CASES,
    EXISTING_CASES,
    EXPORT,
    PAIRED,
    PROFILE,
    PROFILE_CASES,
    artifact,
    digest_file,
    list_exact,
    passed_names,
    provider,
    record,
    require,
    retain,
    save,
)


def run(args):
    hepta = Path.cwd().resolve()
    chain = args.chain.resolve(strict=True)
    out = args.output
    target = args.target
    require(
        out.is_absolute() and target.is_absolute(),
        "absolute private output/target paths",
    )
    require(
        not out.is_relative_to(hepta)
        and not out.is_relative_to(chain)
        and not target.is_relative_to(hepta)
        and not target.is_relative_to(chain),
        "outputs and build products must stay outside both source trees",
    )
    require(
        out.parent.resolve(strict=True) == out.parent
        and target.parent.resolve(strict=True) == target.parent,
        "output and target parents must be existing canonical paths",
    )
    require(
        not target.exists()
        and not target.with_name(target.name + "-feature-off").exists(),
        "new private targets required; retained original targets stay unchanged",
    )
    require(
        args.profile == PROFILE,
        "explicit versioned ordinary NPQ6 source profile required",
    )
    out.mkdir(mode=0o700)
    require(os.environ.get("CARGO_BUILD_JOBS") == "2", "original jobs=2 required")
    chain_before = original.identity(repository=chain)
    require(
        not chain_before["dirty"]
        and chain_before["commit"] == args.chain_source
        and chain_before["tree"] == args.chain_tree,
        "exact clean actual Chain source required",
    )
    hepta_before = original.identity(repository=hepta)
    require(not hepta_before["dirty"], "clean actual Hepta source required")
    save(
        out / "before.json",
        {
            "chain": chain_before,
            "hepta": hepta_before,
            "provider": provider(args.provider_receipt, chain),
            "claim": "started; no test qualification",
        },
    )
    manifest = chain / "trillionnium/Cargo.toml"
    cargo = [
        "cargo",
        "+1.95.0",
        "test",
        "--locked",
        "--release",
        "--manifest-path",
        manifest,
        "-p",
        "trnm-pon-node",
    ]
    chain_env = {"CARGO_TARGET_DIR": target, "RUST_TEST_THREADS": "1"}
    # Separate feature-off output cannot overwrite the PQ executable later used.
    _, feature_off_log = record(
        out,
        "feature-off",
        cargo
        + [
            "--no-default-features",
            "--test",
            "pq_application_local_feature_off",
            "ordinary_npq6_explicit_configuration_has_no_feature_or_platform_fallback",
            "--",
            "--exact",
            "--show-output",
            "--test-threads=1",
        ],
        minimum=1,
        changes={
            "CARGO_TARGET_DIR": target.with_name(target.name + "-feature-off"),
            "RUST_TEST_THREADS": "1",
        },
    )
    passed_names(
        feature_off_log,
        ("ordinary_npq6_explicit_configuration_has_no_feature_or_platform_fallback",),
    )
    _, binary_log = record(
        out,
        "chain-binary-build",
        [
            "cargo",
            "+1.95.0",
            "build",
            "--locked",
            "--release",
            "--manifest-path",
            manifest,
            "-p",
            "trnm-pon-node",
            "--features",
            "pq-native-openssl",
            "--bin",
            "trnm-pon-node",
            "--message-format=json",
        ],
        changes=chain_env,
    )
    _, build_log = record(
        out,
        "chain-exporter-build",
        cargo
        + [
            "--features",
            "pq-native-openssl",
            "--test",
            "pq_application_local_cli",
            "--no-run",
            "--message-format=json",
        ],
        changes=chain_env,
    )
    exporter = artifact(build_log, "pq_application_local_cli", "test", True)
    binary_original = artifact(binary_log, "trnm-pon-node", "bin", False)
    binary = binary_original
    exporter_original = exporter
    (out / "retained").mkdir(mode=0o700)
    binary_meta = retain(out / "retained", binary, "trnm-pon-node")
    exporter_meta = retain(out / "retained", exporter, "pq_application_local_cli")
    binary = Path(binary_meta["path"])
    exporter = Path(exporter_meta["path"])
    list_exact(out, exporter)
    # Original nextest wrapper handles compile-only separately from execution.
    record(
        out,
        "hepta-build",
        ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib", "--no-run"],
    )
    _, existing_log = record(
        out,
        "existing-owner-six",
        cargo
        + [
            "--features",
            "pq-native-openssl",
            "--lib",
            "store::pq_existing_owner_tests::",
            "--",
            "--show-output",
            "--test-threads=1",
        ],
        minimum=6,
        changes=chain_env,
    )
    passed_names(existing_log, EXISTING_CASES)
    _, ordinary_log = record(
        out,
        "ordinary-binary-four",
        [exporter, "--show-output", "--test-threads=1"],
        minimum=len(CHAIN_CASES),
    )
    passed_names(ordinary_log, CHAIN_CASES)
    record(
        out,
        "normal-library-production-refusal",
        [
            "just",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--test",
            "automation_effect_provider_production",
            "-E",
            "test(=ordinary_production_loader_refuses_classical_pon_provider_after_pq_evidence_recovery)",
            "--no-capture",
        ],
        minimum=1,
    )
    profile = " | ".join(f"test(={name})" for name in PROFILE_CASES)
    record(
        out,
        "strict-readback-four",
        [
            "just",
            "test",
            "--locked",
            "-p",
            "codex-hepta-agentd",
            "--lib",
            "-E",
            profile,
            "--no-capture",
        ],
        minimum=len(PROFILE_CASES),
    )
    require(
        digest_file(binary_original, single_link=False)["sha256"]
        == binary_meta["sha256"]
        and digest_file(exporter_original, single_link=False)["sha256"]
        == exporter_meta["sha256"],
        "build artifacts changed",
    )
    cases = []
    for index, name in enumerate(PAIRED):
        case = out / f"case-{index}"
        case.mkdir(mode=0o700)
        material = case / "fresh-material"
        changes = {
            "HEPTA_PON_CHAIN_SOURCE": args.chain_source,
            "HEPTA_PON_CHAIN_BINARY": binary,
            "HEPTA_PON_CHAIN_SHA256": binary_meta["sha256"],
            "HEPTA_PON_NPQ6_FIXTURE_OUT": material,
            "RUST_TEST_THREADS": "1",
        }
        # This original real libtest helper only prepares public test material.
        _, preparation_log = record(
            case,
            "prepare-only",
            [
                exporter,
                EXPORT,
                "--exact",
                "--ignored",
                "--show-output",
                "--test-threads=1",
            ],
            minimum=1,
            changes=changes,
        )
        passed_names(preparation_log, (EXPORT,))
        material_meta = digest_file(material / "manifest.json")
        prepared = json.loads((material / "manifest.json").read_text())
        require(
            prepared["chain_source"] == args.chain_source
            and prepared["target_admitted"] is False
            and prepared["production_activation"] is False,
            "fresh exact public material required",
        )
        changes["HEPTA_PON_NPQ6_MATERIAL_SHA256"] = material_meta["sha256"]
        result, log = record(
            case,
            "paired-exact",
            [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-agentd",
                "--lib",
                "-E",
                f"test(={name})",
                "--run-ignored",
                "only",
                "--no-capture",
            ],
            minimum=1,
            changes=changes,
        )
        require(
            "FLAKY" not in log.read_text(), "paired control must pass its first attempt"
        )
        require(
            digest_file(binary) == binary_meta
            and digest_file(exporter) == exporter_meta,
            "prepared executables changed",
        )
        cases.append(
            {
                "name": name,
                "material": material_meta,
                "preparation_only": True,
                "preparation_receipt": "case-" + str(index) + "/prepare-only.json",
                "execution_receipt": "case-" + str(index) + "/paired-exact.json",
                "execution_status": result["status"],
                "account_expiry_renewed": False,
                "provider_timeout_ms": 30000,
                "control_owner_release_timeout_ms": 2000,
            }
        )
    chain_after = original.identity(repository=chain)
    hepta_after = original.identity(repository=hepta)
    require(
        chain_before == chain_after and hepta_before == hepta_after, "source changed"
    )
    save(
        out / "result.json",
        {
            "schema": "ordinary-npq6-additional-paired-v1",
            "status": "passed",
            "profile": PROFILE,
            "chain": chain_after,
            "hepta": hepta_after,
            "cases": cases,
            "retained_executables": [binary_meta, exporter_meta],
            "preparation_is_business_pass": False,
            "old_paired_gates_replaced": False,
            "whole_chain_qualified": False,
            "independent_trust_deployment_qualified": False,
            "production_activation": False,
        },
    )
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("--chain-source", required=True)
    parser.add_argument("--chain-tree", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--provider-receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as error:
        if args.output.is_dir():
            save(
                args.output / "failure.json",
                {
                    "status": "failed",
                    "error": str(error),
                    "production_activation": False,
                    "old_gates_replaced": False,
                },
            )
        print(f"ordinary NPQ6 additional scope failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
