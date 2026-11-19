#!/usr/bin/env python3
"""Unadmitted, read-only fresh-runner observations; no apt/package/source operation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time
from urllib.parse import urlsplit

DOMAINS = ("azure.archive.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com", "ports.ubuntu.com", "packages.microsoft.com")
SOURCE = "c89540598693697577cda8cba31cb07f6ce65317"
TREE = "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def utc():
    return datetime.now(timezone.utc).isoformat()


def safe_uri(text):
    parsed = urlsplit(text)
    return {"scheme": parsed.scheme, "hostname": parsed.hostname,
            "port": parsed.port,
            "known_public_path": parsed.path if parsed.path in ("/ubuntu", "/ubuntu/", "/ubuntu-ports", "/ubuntu-ports/", "/ubuntu/24.04/prod") else None,
            "path_sha256": hashlib.sha256(parsed.path.encode()).hexdigest(),
            "userinfo_omitted": parsed.username is not None or parsed.password is not None,
            "query_omitted": bool(parsed.query), "fragment_omitted": bool(parsed.fragment)}


def configuration():
    sources = [Path("/etc/apt/sources.list"), Path("/etc/apt/apt-mirrors.txt")]
    parts = Path("/etc/apt/sources.list.d")
    children = sorted(p for p in parts.iterdir() if p.suffix in (".list", ".sources")) if parts.is_dir() else []
    if len(children) > 32:
        raise RuntimeError("source configuration inventory exceeds fixed 32-file bound")
    sources += children
    selected = sources + [Path("/etc/resolv.conf"), Path("/etc/nsswitch.conf")]
    result = []
    for path in selected:
        record = {"path": str(path)}
        try:
            if not path.exists():
                record["state"] = "absent"
                result.append(record)
                continue
            physical = path.resolve(strict=True)
            if path == Path("/etc/resolv.conf"):
                permitted = {path, Path("/run/systemd/resolve/stub-resolv.conf"), Path("/run/systemd/resolve/resolv.conf")}
                if physical not in permitted:
                    raise RuntimeError("resolver link outside exact public configuration allowlist")
            elif physical != path:
                raise RuntimeError("unexpected redirected public configuration")
            with physical.open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise RuntimeError("configuration exceeds fixed 64 KiB bound")
            record.update(state="read", physical_path=str(physical), **pin(raw))
            lines = raw.decode("utf-8").splitlines()
            if path == Path("/etc/resolv.conf"):
                record["projection"] = [line for line in lines if re.match(r"^\s*(nameserver|options)\s", line)]
            elif path == Path("/etc/nsswitch.conf"):
                record["projection"] = [line for line in lines if re.match(r"^\s*hosts\s*:", line)]
            else:
                # Do not retain comments, auth configuration, URI credentials/query or embedded keys.
                projection = []
                for line in lines:
                    value = line.strip()
                    if not value or value.startswith("#"):
                        continue
                    uris = re.findall(r"(?:https?|mirror\+https?|mirror\+file|file)://?[^\s\]]+", value)
                    if uris:
                        projection.append({"uris": [safe_uri(uri) for uri in uris]})
                    elif re.match(r"^(Types|Suites|Components|Enabled):", value):
                        projection.append({"field": value})
                record["projection"] = projection
        except Exception as error:
            record.update(state="unavailable", error_type=type(error).__name__)
        result.append(record)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--budget-seconds", type=int, required=True)
    args = parser.parse_args()
    if args.budget_seconds != 120:
        raise RuntimeError("independent observation budget differs from frozen 120 seconds")
    output = Path(args.output).resolve()
    expected = Path(os.environ["RUNNER_TEMP"]).resolve() / "mem8-apt-dns-c895-observe"
    if output != expected:
        raise RuntimeError("unexpected diagnostic output directory")
    output.mkdir(mode=0o700)
    start = time.monotonic()
    deadline = start + 120
    result = {"schema": "mem.c895.apt-dns.fresh-observation.v1", "started_at": utc(),
              "original_source": SOURCE, "original_tree": TREE, "diagnostic_budget_seconds": 120,
              "current_job_identity": {k: os.environ.get(k) for k in ("GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")},
              "queries": [], "original_failure_reproduced": "NOT_ASSERTED_FRESH_DIFFERENT_RUNNER",
              "packages_installed": 0, "dns_or_network_policy_changed": False,
              "native_tests": 0, "model_calls": 0}
    code = 1
    try:
        result["configuration_before"] = configuration()
        getent = shutil.which("getent")
        if getent is None:
            raise RuntimeError("existing getent unavailable; no installation or fallback")
        result["getent_path"] = getent
        for domain in DOMAINS:
            remaining = min(10, deadline - time.monotonic() - 3)
            if remaining <= 0:
                raise TimeoutError("original observation deadline exhausted")
            argv = [getent, "ahosts", domain]
            phase = {"domain": domain, "command": argv, "started_at": utc(), "attempt": 1}
            child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = child.communicate(timeout=remaining)
                phase["timed_out"] = False
            except subprocess.TimeoutExpired:
                phase["timed_out"] = True
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stdout, stderr = child.communicate(timeout=max(0.1, min(2, deadline - time.monotonic())))
            if len(stdout) + len(stderr) > 65536:
                raise RuntimeError("resolver output exceeds fixed observation bound")
            for suffix, raw in (("stdout", stdout), ("stderr", stderr)):
                name = domain + "." + suffix
                with (output / name).open("xb") as stream:
                    stream.write(raw)
                phase[suffix] = {"path": name, **pin(raw)}
            phase.update(exit_code=child.returncode, finished_at=utc())
            result["queries"].append(phase)
        result["configuration_after"] = configuration()
        result["configuration_unchanged"] = result["configuration_before"] == result["configuration_after"]
        by_path = {row["path"]: row for row in result["configuration_after"]}
        result["configuration_complete"] = (all(row["state"] != "unavailable" for row in by_path.values())
            and all(by_path[name]["state"] == "read" for name in ("/etc/resolv.conf", "/etc/nsswitch.conf"))
            and any(row["state"] == "read" for path, row in by_path.items() if path.startswith("/etc/apt/")))
        if time.monotonic() >= deadline:
            raise TimeoutError("observation exceeded original 120-second deadline")
        result["capture_complete"] = True
        result["all_queries_returned_zero"] = all(q["exit_code"] == 0 and not q["timed_out"] for q in result["queries"])
        # A complete record is not apt/package readiness; a resolver failure remains nonzero.
        code = 0 if result["all_queries_returned_zero"] and result["configuration_unchanged"] and result["configuration_complete"] else 1
    except Exception as error:
        result.update(capture_complete=False, error_type=type(error).__name__)
    finally:
        result.update(finished_at=utc(), elapsed_seconds=time.monotonic() - start,
                      exit_code=code, apt_or_original_CI_qualification="NOT_EVALUATED")
        with (output / "OBSERVATIONS.json").open("x") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
