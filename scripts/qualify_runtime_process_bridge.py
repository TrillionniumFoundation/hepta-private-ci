"""Run the Cell worker through real runtime MCP/SSH, then cold-observe its job.

Explicitly restricted to a disposable runner because the existing runtime SSH
fixture creates a private localhost daemon and a temporary known-host entry.
No simulated tool result is admitted by this qualification.  A failed stage
retains FAIL, and source/binary build provenance remains a separate gate.
"""

import argparse
import importlib.util
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import traceback

from runtime_process_bridge import (
    RuntimeProcessBridge,
    StdioRuntime,
    canonical,
    digest,
    file_digest,
    require,
    strict_json,
)


def write(path, value):
    with path.open("wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "runtime-source",
        "runtime-binary",
        "cell-source",
        "candidate",
        "request",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--runtime-commit", required=True)
    parser.add_argument("--allow-disposable-sshd", action="store_true")
    parser.add_argument("--with-maintenance", action="store_true")
    parser.add_argument("--with-semantic-updates", action="store_true")
    args = parser.parse_args()
    require(args.allow_disposable_sshd, "the explicit disposable-sshd flag is required")
    require(
        os.environ.get("GITHUB_ACTIONS") == "true",
        "run this fixture only on a disposable Actions runner",
    )
    args.output = args.output.resolve()
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    runtime_root = args.runtime_source.resolve(strict=True)
    cell_root = args.cell_source.resolve(strict=True)
    candidate = args.candidate.resolve(strict=True)
    candidate_record = strict_json(candidate.read_bytes())
    request = strict_json(args.request.read_bytes())
    worker = cell_root / "scripts/hepta_cell_joint_worker.py"
    require(worker.is_file(), "the actual Cell worker is missing")
    actual = (
        subprocess.check_output(
            ["git", "-C", str(runtime_root), "rev-parse", "HEAD"], timeout=10
        )
        .decode()
        .strip()
    )
    require(actual == args.runtime_commit, "runtime source commit mismatch")
    require(
        actual == candidate_record["source_bases"]["runtime"],
        "runtime differs from the selected common source candidate",
    )
    # This is the existing runtime's real OpenSSH setup/cleanup owner, loaded
    # only from the frozen source.  Private keys remain outside the upload root.
    source = runtime_root / "tests/hia_native_helper_mcp_integration.py"
    spec = importlib.util.spec_from_file_location("frozen_runtime_ssh_fixture", source)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    # StrictModes checks authorized_keys parent directories; /tmp is writable.
    # Keep private SSH state outside the workflow's RUNNER_TEMP evidence upload.
    private = Path(
        tempfile.mkdtemp(
            prefix="cell-runtime-private-",
            dir=pwd.getpwuid(os.getuid()).pw_dir,
        )
    )
    os.chmod(private, 0o700)
    report = {
        "schema": "hepta.cell.runtime-bridge.qualification.v1",
        "status": "FAIL",
        "runtime_source_commit": actual,
        "runtime_binary_sha256": file_digest(args.runtime_binary),
        "candidate_sha256": file_digest(candidate),
        "worker_sha256": file_digest(worker),
        "ssh_fixture_sha256": file_digest(source),
        "request_sha256": digest(canonical(request)),
        "actual_runtime_transport": False,
        "controller_cold_restart_observed": False,
        "no_second_process_submission": False,
        "worker_domain_result_requires_independent_validation": True,
        "runtime_binary_build_provenance_verified": False,
        "final_use_capability_boundary_qualified": False,
        "sessions": [],
    }
    write(args.output / "result.json", report)
    ssh = helper.DisposableSSH(private, args.output, helper.clean_environment())
    client = bridge = None
    started = time.monotonic()

    def close_client():
        nonlocal client, bridge
        if bridge:
            bridge.close()
            bridge = None
        if client:
            report["sessions"].append(
                {"runtime": client.identity, "protocol": client.records}
            )
            client.close()
            client = None

    try:
        ssh.start()
        config = {
            "state_dir": str(private / "controller-state"),
            "controller_workspace_roots": [
                str(args.output),
                str(cell_root),
                str(runtime_root),
            ],
            "hosts": {
                "loopback": {
                    "execution_mode": "operator",
                    "ssh_target": ssh.target,
                    "platform": "linux",
                    "remote_state_dir": str(private / "owner-state"),
                    "allow_execute": True,
                    "allow_write": True,
                    # Operator mode uses the existing administrator authority;
                    # it cannot claim a network-isolated child process.
                    "allow_job_network": True,
                    "allow_detached_fallback": False,
                    "allowed_read_path_prefixes": [
                        str(cell_root),
                        candidate_record["hia_root"],
                        str(candidate.parent),
                        str(args.output),
                        str(private),
                        str(Path(sys.executable).parent),
                        "/usr/bin",
                    ],
                    "allowed_write_path_prefixes": [str(private), str(args.output)],
                }
            },
        }
        config_path = private / "runtime-config.json"
        write(config_path, config)
        config_path.chmod(0o600)
        runtime_identity = {
            "source_commit": actual,
            "source_tree": subprocess.check_output(
                ["git", "-C", str(runtime_root), "rev-parse", "HEAD^{tree}"], timeout=10
            )
            .decode()
            .strip(),
            "binary_sha256": report["runtime_binary_sha256"],
            "config_sha256": file_digest(config_path),
            "transport": "actual_mcp_stdio",
        }
        report["origin_candidate_sha256"] = report["candidate_sha256"]
        runtime_candidate = candidate.parent / (
            "runtime-candidate-" + runtime_identity["config_sha256"][:16] + ".json"
        )
        require(not runtime_candidate.exists(), "runtime candidate already exists")
        candidate_record = {
            **candidate_record,
            "runtime_identity": runtime_identity,
            "origin_candidate_sha256": report["origin_candidate_sha256"],
            "runtime_execution": "new runtime-bound candidate; actual execution required",
        }
        write(runtime_candidate, candidate_record)
        candidate = runtime_candidate
        report["candidate_sha256"] = file_digest(candidate)
        report["runtime_identity"] = runtime_identity
        write(args.output / "candidate.json", candidate_record)
        profile = {
            "schema": "hepta.cell.runtime-process-bridge.v1",
            "namespace": "joint-cell-" + report["candidate_sha256"],
            "candidate_sha256": report["candidate_sha256"],
            "max_output_bytes": 4 * 1024 * 1024,
            "runtime": {
                "source_root": str(runtime_root),
                "source_commit": actual,
                "binary": str(args.runtime_binary.resolve(strict=True)),
                "binary_sha256": report["runtime_binary_sha256"],
                "config": str(config_path),
                "config_sha256": file_digest(config_path),
            },
            "process": {
                "host": "loopback",
                "executable": str(Path(sys.executable).absolute()),
                "args": [
                    "-B",
                    str(worker),
                    "--candidate",
                    str(candidate),
                    "--database",
                    str(private / "cells.sqlite3"),
                ],
                "cwd": str(cell_root),
                "timeout_seconds": 120,
                "env": {
                    key: value
                    for key, value in candidate_record["device"][
                        "thread_settings"
                    ].items()
                    if value is not None
                },
                "cpu_quota_percent": 200,
                "memory_max_bytes": 1073741824,
            },
        }
        write(args.output / "profile.json", profile)
        client = StdioRuntime(profile["runtime"], environment=ssh.env)
        bridge = RuntimeProcessBridge(
            profile,
            private / "bridge.sqlite3",
            client.call,
            transport_identity=client.identity,
        )
        observed = bridge.execute(request)
        deadline = time.monotonic() + 150
        while (
            observed["state"] != "TERMINAL"
            and observed.get("job_id")
            and time.monotonic() < deadline
        ):
            time.sleep(0.1)
            observed = bridge.observe(request["request_id"])
        report["first_observation"] = observed
        require(
            observed["state"] == "TERMINAL",
            "original runtime job did not produce complete terminal output",
        )
        require(
            observed["runtime_state"] == "succeeded" and observed["exit_code"] == 0,
            "actual worker process did not succeed",
        )
        domain = strict_json(bytes.fromhex(observed["streams"]["stdout"]["bytes_hex"]))
        require(
            domain.get("status") == "observed"
            and domain.get("candidate_sha256") == report["candidate_sha256"],
            "worker did not return this exact candidate",
        )
        receipt = domain.get("result", {})
        native_result = receipt.get("output", {}).get("hia", {})
        require(
            receipt.get("status") == "committed"
            and receipt.get("request_id") == request["request_id"]
            and native_result.get("terminal_action") == "COMPLETE"
            and native_result.get("image_sha256")
            == candidate_record["native"]["image_sha256"]
            and native_result.get("candidate_sha256") == report["candidate_sha256"]
            and domain.get("continuation", {}).get("cell_result_retained") is True,
            "worker exit is not a retained native-HIA Cell receipt",
        )
        report["worker_domain_result_requires_independent_validation"] = False
        report["native_hia_cell_receipt_verified"] = True
        report["worker_result"] = domain
        close_client()
        client = StdioRuntime(profile["runtime"], environment=ssh.env)
        bridge = RuntimeProcessBridge(
            profile,
            private / "bridge.sqlite3",
            client.call,
            transport_identity=client.identity,
        )
        recovered = bridge.execute(request)
        report["recovered_observation"] = recovered
        require(
            recovered == observed,
            "cold observation changed the original result or job identity",
        )
        report["controller_cold_restart_observed"] = True
        second_starts = [
            r
            for r in client.records
            if r["request"].get("method") == "tools/call"
            and r["request"]["params"].get("name") == "process_start"
        ]
        require(not second_starts, "cold recovery resubmitted process_start")
        second_calls = [
            r["request"]["params"]["name"]
            for r in client.records
            if r["request"].get("method") == "tools/call"
        ]
        require(
            "process_status" in second_calls and "process_read" in second_calls,
            "cold recovery did not freshly read the original runtime job",
        )
        report["no_second_process_submission"] = True
        report["actual_runtime_transport"] = True
        if args.with_maintenance:
            from qualify_runtime_campaign import run_campaign

            close_client()
            report["maintenance"] = run_campaign(
                profile,
                candidate_record,
                args.output,
                private,
                ssh.env,
                request["request_id"],
            )
        if args.with_semantic_updates:
            from qualify_runtime_campaign import run_campaign

            close_client()
            report["semantic_updates"] = run_campaign(
                profile,
                candidate_record,
                args.output,
                private,
                ssh.env,
                request["request_id"],
                campaign="semantic_updates",
            )
        report["status"] = "PASS"
    except BaseException:
        report["error"] = traceback.format_exc()
        raise
    finally:
        close_client()
        report["cleanup_errors"] = ssh.close()
        if report["cleanup_errors"]:
            report["status"] = "FAIL"
        report["elapsed_seconds"] = time.monotonic() - started
        report["private_state_retained"] = True
        write(args.output / "result.json", report)
    print(
        canonical(
            {
                "status": report["status"],
                "result_sha256": file_digest(args.output / "result.json"),
            }
        ).decode()
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
