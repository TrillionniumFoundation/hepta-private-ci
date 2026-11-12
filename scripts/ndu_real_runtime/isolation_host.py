"""Read-only host evidence around the unchanged strict MEM namespace launcher.

Missing policy files and inaccessible kernel labels remain unknown. This does
not collect AppArmor audit logs or establish why a kernel operation was denied.
No host policy, namespace flag, or required isolation test is changed.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import time

from .episodic_isolation import run_isolated_actor


MAX_FILE_BYTES = 65536
POLICY_PATHS = (
    "/proc/self/attr/current",
    "/sys/kernel/security/lsm",
    "/sys/module/apparmor/parameters/enabled",
    "/proc/sys/kernel/apparmor_restrict_unprivileged_userns",
    "/proc/sys/kernel/apparmor_restrict_unprivileged_unconfined",
    "/proc/sys/kernel/unprivileged_userns_clone",
    "/proc/sys/user/max_user_namespaces",
)
STATUS_FIELDS = {
    "Uid",
    "Gid",
    "CapInh",
    "CapPrm",
    "CapEff",
    "CapBnd",
    "CapAmb",
    "NoNewPrivs",
    "Seccomp",
    "Seccomp_filters",
}


def _pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read(path):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        return {
            "state": "UNAVAILABLE",
            "error": type(error).__name__,
            "errno": error.errno,
        }
    truncated = len(raw) > MAX_FILE_BYTES
    raw = raw[:MAX_FILE_BYTES]
    return {
        "state": "TRUNCATED" if truncated else "OBSERVED",
        "raw_base64": base64.b64encode(raw).decode("ascii"),
        **_pin(raw),
    }


def _snapshot():
    status = _read("/proc/self/status")
    if status["state"] == "OBSERVED":
        status = {
            "state": "OBSERVED",
            "fields": {
                key: value.strip()
                for line in base64.b64decode(status["raw_base64"]).decode().splitlines()
                for key, separator, value in [line.partition(":")]
                if separator and key in STATUS_FIELDS
            },
        }
    return {
        "policy_files": {path: _read(path) for path in POLICY_PATHS},
        "process_status": status,
    }


def record_host(output):
    """Retain one diagnostic probe; never convert its result into a test pass.

    The launcher uses the same namespaces, sealed memfd inputs, caps, runtime
    mounts, environment, and no-network boundary as the eight required tests.
    A separate probe outcome cannot replace those tests. Output is exclusive;
    repeating this operation requires a new output path and remains a new probe.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    started = time.time_ns()
    before = _snapshot()
    bubblewrap = shutil.which("bwrap")
    tool = {"state": "UNAVAILABLE"}
    if bubblewrap is not None:
        path = Path(bubblewrap)
        try:
            info = path.stat()
            raw = (
                path.read_bytes()
                if info.st_size <= 16777216 and stat.S_ISREG(info.st_mode)
                else None
            )
            tool = {
                "state": "OBSERVED" if raw is not None else "UNAVAILABLE",
                "path": str(path),
                "resolved_path": str(path.resolve()),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
                "binary": _pin(raw) if raw is not None else None,
            }
            version = subprocess.run(
                [str(path), "--version"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=5,
                check=False,
            )
            tool["version"] = {
                "returncode": version.returncode,
                "stdout": version.stdout[:4096].decode("utf-8", errors="replace"),
                "stderr": version.stderr[:4096].decode("utf-8", errors="replace"),
                "truncated": len(version.stdout) > 4096 or len(version.stderr) > 4096,
            }
        except (OSError, subprocess.TimeoutExpired) as error:
            tool["observation_error"] = type(error).__name__
    probe = run_isolated_actor(
        output / "probe",
        b'print("namespace-setup-diagnostic-only")\n',
        {"diagnostic": "strict-namespace-setup-only"},
        mode="off",
        timeout_seconds=5,
    )
    report = {
        "schema": "hepta.mem11.isolation-host-observation.v1",
        "started_at_unix_ns": started,
        "ended_at_unix_ns": time.time_ns(),
        "platform": platform.platform(),
        "kernel": platform.release(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "python": platform.python_version(),
        "bubblewrap": tool,
        "before": before,
        "after": _snapshot(),
        "probe": {
            "status": probe["status"],
            "receipt": _pin((output / "probe" / "RECEIPT.json").read_bytes()),
        },
        "probe_counts_as_required_test": False,
        "host_policy_mutation_requested": False,
        "apparmor_audit_attribution": "UNKNOWN",
        "scientific_acceptance": "HOLD",
        "model_calls_observed": 0,
    }
    (output / "HOST.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = record_host(args.output)
    print(
        json.dumps(
            {
                "probe_status": report["probe"]["status"],
                "apparmor_audit_attribution": "UNKNOWN",
            }
        )
    )


if __name__ == "__main__":
    main()
