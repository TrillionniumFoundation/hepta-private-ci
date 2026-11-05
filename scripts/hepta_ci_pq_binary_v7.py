#!/usr/bin/env python3
"""Observe the current PQ lib-test build before and after the exact controls.

Reuse the paired Chain's bounded file and ELF readers. These two observations
do not attest every exec or transient replacement between observations.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


BUILD_COMMAND = [
    "cargo",
    "+1.95.0",
    "test",
    "--locked",
    "--release",
    "--manifest-path",
    "trillionnium/Cargo.toml",
    "-p",
    "trnm-pon-node",
    "--lib",
    "--all-features",
    "--no-run",
    "--message-format=json",
]


class BinaryObservation:
    def __init__(self, chain, output, runner_arch):
        self.chain = chain.resolve(strict=True)
        self.output = output.resolve(strict=True)
        sys.path.insert(0, str(self.chain / "scripts/ci"))
        import run_history_native as history
        from check_cross_arch_cost import elf_machine
        from public_host_ci_observation import write_new
        from replay_pinned_native import json_load, require

        self.history, self.elf_machine = history, elf_machine
        self.write_new, self.json_load, self.require = write_new, json_load, require
        require(
            not self.output.is_relative_to(self.chain),
            "PQ_BINARY_OUTPUT_OUTSIDE_SOURCE",
        )
        require(runner_arch in {"X64", "ARM64"}, "PQ_BINARY_RUNNER_ARCH_REQUIRED")
        self.machine = {"X64": 62, "ARM64": 183}[runner_arch]

    def observe(self, path):
        value, _ = self.history.file_observation(path, self.history.BINARY_LIMIT)
        value["elf_machine"] = self.elf_machine(path)
        after = path.stat()
        self.require(
            all(
                value[key] == getattr(after, field)
                for key, field in (
                    ("device", "st_dev"),
                    ("inode", "st_ino"),
                    ("size_bytes", "st_size"),
                    ("mtime_ns", "st_mtime_ns"),
                    ("ctime_ns", "st_ctime_ns"),
                )
            ),
            "PQ_BINARY_CHANGED_DURING_OBSERVATION",
        )
        self.require(os.access(path, os.X_OK), "PQ_BINARY_EXECUTABLE_REQUIRED")
        self.require(
            value["elf_machine"] == self.machine, "PQ_BINARY_RUNNER_ARCH_MISMATCH"
        )
        return value

    def before(self):
        log, raw = self.history.file_observation(
            self.output / "build.log", self.history.LOG_LIMIT, retain=True
        )
        receipt = self.json_load((self.output / "build.json").read_bytes())
        self.require(
            receipt["status"] == "command_succeeded"
            and receipt["exit_code"] == 0
            and receipt["argv"] == BUILD_COMMAND
            and receipt["log_sha256"] == log["sha256"],
            "PQ_BINARY_CURRENT_BUILD_REQUIRED",
        )
        selected, finished = [], False
        for line in raw.decode("utf-8").splitlines():
            if not line.startswith("{"):
                continue
            row = self.json_load(line)
            self.require(
                type(row) is dict and not finished, "PQ_BINARY_BUILD_RECORD_ORDER"
            )
            if row.get("reason") == "build-finished":
                self.require(
                    row.get("success") is True, "PQ_BINARY_BUILD_FINISH_REQUIRED"
                )
                finished = True
            elif row.get("reason") == "compiler-artifact":
                target, profile = row.get("target", {}), row.get("profile", {})
                if (
                    target.get("name") != "trnm_pon_node"
                    or profile.get("test") is not True
                ):
                    continue
                crate = self.chain / "trillionnium/crates/trnm-pon-node"
                self.require(
                    row.get("manifest_path") == str(crate / "Cargo.toml")
                    and target.get("src_path") == str(crate / "src/lib.rs")
                    and target.get("kind") == target.get("crate_types") == ["lib"]
                    and target.get("test") is True,
                    "PQ_BINARY_LIB_SOURCE_REQUIRED",
                )
                self.require(
                    profile.get("opt_level") == "3"
                    and "pq-native-openssl" in row.get("features", []),
                    "PQ_BINARY_RELEASE_PQ_PROFILE_REQUIRED",
                )
                executable = row.get("executable")
                self.require(
                    type(executable) is str and executable in row.get("filenames", []),
                    "PQ_BINARY_EXECUTABLE_BINDING",
                )
                selected.append(row)
        self.require(
            finished and len(selected) == 1,
            "PQ_BINARY_UNIQUE_FINISHED_ARTIFACT_REQUIRED",
        )
        artifact = selected[0]
        value = dict(
            schema="hepta-v7-current-pq-binary-before-v1",
            build_log=log,
            build_receipt_sha256=hashlib.sha256(
                (self.output / "build.json").read_bytes()
            ).hexdigest(),
            compiler_artifact=artifact,
            binary=self.observe(Path(artifact["executable"])),
            every_exec_observed=False,
            whole_chain_quantum_security_qualified=False,
            installation_authorized=False,
        )
        self.write_new(self.output / "binary-inventory-before.json", value)
        return value

    def after(self):
        prior = self.json_load(
            (self.output / "binary-inventory-before.json").read_bytes()
        )
        self.require(
            prior["schema"] == "hepta-v7-current-pq-binary-before-v1",
            "PQ_BINARY_BEFORE_RECEIPT_REQUIRED",
        )
        observed = self.observe(Path(prior["binary"]["path"]))
        value = dict(
            schema="hepta-v7-current-pq-binary-after-v1",
            before=prior["binary"],
            after=observed,
            unchanged=prior["binary"] == observed,
            every_exec_observed=False,
            whole_chain_quantum_security_qualified=False,
            installation_authorized=False,
        )
        self.write_new(self.output / "binary-inventory-after.json", value)
        self.require(value["unchanged"], "PQ_BINARY_CHANGED_BETWEEN_OBSERVATIONS")
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--chain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runner-arch", required=True)
    args = parser.parse_args()
    reader = BinaryObservation(args.chain, args.output, args.runner_arch)
    try:
        value = getattr(reader, args.phase)()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
