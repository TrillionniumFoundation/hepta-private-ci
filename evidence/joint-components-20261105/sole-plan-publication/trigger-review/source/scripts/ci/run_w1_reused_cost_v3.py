#!/usr/bin/env python3
"""Explicit V3 release observation; leave every original V2/default gate intact.

Reuse the original native cost command owner, compiler contract and time limits.
Local mode never satisfies hosted cross-architecture or work-hardness acceptance.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from ci_observation import ROOT, digest, receipt_root, source
from check_cross_arch_cost import (ARCHITECTURES, COST_BUILD_TIMEOUT_SECONDS,
    COST_CAMPAIGN_TIMEOUT_SECONDS, COST_IDENTITY_TIMEOUT_SECONDS, elf_machine)
from run_cross_arch_cost import (build_environment_overrides, capture,
    cargo_configuration_snapshot, require_cargo_configuration)

sys.path.insert(0, str(ROOT / "scripts"))
from pon_w1_reused_cost_reader_v3 import FALSE_FLAGS, SELECTOR, analyze

EXAMPLE = "pon_w1_reused_cost_v3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=sorted(ARCHITECTURES), required=True)
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    spec = ARCHITECTURES[args.arch]
    output = receipt_root("w1-actual-reuse-v3")
    observations = []
    report = {"schema": "trnm-w1-actual-reuse-execution-v4", "result": "FAIL",
        "execution_context": "local-native-preflight" if args.local else "github-hosted",
        "architecture": args.arch, "build_profile": "release", "compiler_channel": "1.95.0",
        "target": spec["target"], "observations": observations, "source_before": None,
        "cargo_configuration_before": None, "cargo_configuration_after": None,
        "cargo_configuration_changed": False, "default_release_configuration_checked": False,
        "runner_context": {key: os.environ.get(key) for key in (
            "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_REPOSITORY",
            "GITHUB_EVENT_NAME", "RUNNER_ARCH", "RUNNER_OS", "RUNNER_NAME", "ImageOS", "ImageVersion",
            "TRNM_COST_RUNNER_LABEL")}, **FALSE_FLAGS}

    def checked(command, name, timeout=COST_IDENTITY_TIMEOUT_SECONDS):
        result = capture(command, output, name, timeout=timeout, cwd=ROOT)
        observations.append(result)
        if result["exit_code"] != 0 or result["timed_out"]:
            raise ValueError(name + " failed; retain original stdout/stderr and status")

    try:
        report["source_before"] = source()
        if report["source_before"]["source_state"] != "committed-clean":
            raise ValueError("actual complete committed source bytes required")
        if platform.system() != "Linux" or platform.machine() != spec["machine"]:
            raise ValueError("actual native Linux architecture required")
        if not args.local and (os.environ.get("TRNM_COST_RUNNER_LABEL") != spec["runner"]
                or os.environ.get("RUNNER_ARCH") != spec["runner_arch"]
                or os.environ.get("GITHUB_ACTIONS") != "true"
                or not os.environ.get("GITHUB_RUN_ID", "").isdigit()
                or not os.environ.get("GITHUB_RUN_ATTEMPT", "").isdigit()):
            raise ValueError("actual hosted runner context required; use --local for preflight")
        overrides = build_environment_overrides(dict(os.environ))
        report["build_environment_overrides"] = overrides
        if overrides:
            raise ValueError("original release compiler/target contract forbids overrides")
        report["cargo_configuration_before"] = cargo_configuration_snapshot(ROOT, dict(os.environ))
        require_cargo_configuration(report["cargo_configuration_before"])
        checked(["uname", "-a"], "uname")
        checked(["rustc", "+1.95.0", "-vV"], "rustc")
        checked(["cargo", "+1.95.0", "--version"], "cargo")
        compiler = (output / "rustc.stdout").read_text()
        if "\nrelease: 1.95.0\n" not in compiler or "\nhost: " + spec["target"] + "\n" not in compiler:
            raise ValueError("actual compiler differs from original native 1.95.0 contract")
        shutil.copyfile("/proc/cpuinfo", output / "cpuinfo.txt")
        checked(["cargo", "+1.95.0", "build", "--locked", "--release", "--manifest-path",
            "trillionnium/Cargo.toml", "--target", spec["target"], "-p", "trnm-pon-node",
            "--example", EXAMPLE], "build", COST_BUILD_TIMEOUT_SECONDS)
        binary = Path(os.environ["CARGO_TARGET_DIR"]) / spec["target"] / "release/examples" / EXAMPLE
        report["binary_elf_machine"] = elf_machine(binary)
        if report["binary_elf_machine"] != spec["elf_machine"]:
            raise ValueError("actual ELF architecture mismatch")
        report["binary_sha256_before"] = digest(binary)
        shutil.copyfile(binary, output / EXAMPLE)
        checked([str(binary), SELECTOR], "campaign", COST_CAMPAIGN_TIMEOUT_SECONDS)
        report["reader"] = analyze(output / "campaign.stdout")
        if report["reader"]["semantic_alerts"]:
            raise ValueError("retained native verifier disagreement")
        report["binary_sha256_after"] = digest(binary)
        if report["binary_sha256_before"] != report["binary_sha256_after"]:
            raise ValueError("measured binary changed")
        report["result"] = "PASS"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        if report["cargo_configuration_before"] is not None:
            try:
                report["cargo_configuration_after"] = cargo_configuration_snapshot(ROOT, dict(os.environ))
                require_cargo_configuration(report["cargo_configuration_after"])
                report["cargo_configuration_changed"] = (
                    report["cargo_configuration_before"] != report["cargo_configuration_after"])
                if report["cargo_configuration_changed"]:
                    raise ValueError("Cargo configuration changed during execution")
                report["default_release_configuration_checked"] = True
            except (OSError, ValueError) as error:
                report["cargo_configuration_error"] = str(error)
                report["result"] = "FAIL"
        try:
            report["source_after"] = source()
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report["source_after"] = {"error": str(error)}
        report["source_changed"] = report["source_before"] != report["source_after"]
        if report["source_changed"]:
            report["result"] = "FAIL"
        report["artifact_sha256"] = {path.relative_to(output).as_posix(): digest(path)
            for path in sorted(output.rglob("*")) if path.is_file()}
        (output / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": report["result"], "receipt": str(output)}, sort_keys=True))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
