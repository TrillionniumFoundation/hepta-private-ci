#!/usr/bin/env python3
"""Read the original real-service artifact without executing archived code."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile

HEAD = "0b9da54535a7795b2433947a479e6d9e71525e0a"
ARTIFACT = 13265079243
DIGEST = "19836a487016d86fb90cede3ff1570e94342f2441412a245c3ee0eb864bab922"
ALGORITHM = "dh-ietf1024-sha256-aes128-cbc-pkcs7"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    directory = args.artifacts / str(ARTIFACT)
    archive = args.artifacts / (str(ARTIFACT) + ".zip")
    require(archive.stat().st_size == 40023 and sha(archive.read_bytes()) == DIGEST, "original ZIP identity")
    with zipfile.ZipFile(archive) as bundle:
        require(bundle.testzip() is None, "ZIP CRC")
        for entry in bundle.infolist():
            name = Path(entry.filename)
            require(not name.is_absolute() and ".." not in name.parts, "unsafe member")
            if not entry.is_dir():
                require(bundle.read(entry) == (directory / name).read_bytes(), "extracted artifact differs")
    require((directory / "source-commit.txt").read_text().strip() == HEAD, "source commit")
    inputs = {line.split(None, 1)[1]: line.split(None, 1)[0]
              for line in (directory / "source-inputs.sha256").read_text().splitlines()}
    require(len(inputs) == 11, "original manifest/DBus input count")
    probes = json.loads((directory / "probes/inputs-before.json").read_text())
    require(len(probes) == 50 and not inputs.keys() & probes.keys(), "provider input count")
    inputs.update(probes)
    for path, digest in inputs.items():
        data = subprocess.check_output(["git", "show", HEAD + ":" + path], cwd=args.repo)
        require(sha(data) == digest, "immutable source differs: " + path)

    native = json.loads((directory / "native/receipt.json").read_text())
    require(native["status"] == "PASS" and len(native["commands"]) == 52, "native build receipt")
    require(all(command["exit"] == 0 for command in native["commands"]), "native command failed")
    require(native["archive"] == {"url": "https://dbus.freedesktop.org/releases/dbus/dbus-1.16.2.tar.xz",
                                  "bytes": 1115644,
                                  "sha256": "0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2"}, "upstream identity")
    require(len(native["inputs"]) == 7, "DBus input inventory")
    for path, digest in native["inputs"].items():
        require(inputs["third_party/dbus/" + path] == digest, "DBus input mismatch")
    require(native["commands"][-1]["stdout"] ==
            "PASS: D-Bus 1.16.2, wire ABI, pidfd identity, non-pidfd rejection, peer UID/PID, high-fd closure\n",
            "original native identity test")

    service = json.loads((directory / "service/receipt.json").read_text())
    require(service["status"] == "PASS" and service["source_inputs_unchanged"] is True, "service acceptance")
    expected = [("baseline", "save", "main", False), ("baseline", "save", "separate", False),
                ("candidate", "load", "main", False), ("candidate", "load", "main", True),
                ("candidate", "save", "main", False), ("baseline", "load", "main", False),
                ("candidate", "delete", "main", False), ("baseline", "missing", "main", False),
                ("candidate", "delete-missing", "main", False), ("candidate", "load", "separate", False),
                ("candidate", "delete", "separate", False), ("candidate", "reject-dh", "rejected", False)]
    actual = [(s["provider"], s["operation"], s["account"], s["discover_address"]) for s in service["steps"]]
    require(actual == expected, "original operation order or identity changed")
    for step in service["steps"]:
        require(step["exit"] == 0 and step["stdout"] == "PASS: " + step["operation"] + "\n", "service operation failed")
    monitor = (directory / "service/session-monitor.log").read_text()
    sessions = re.findall(r'member=OpenSession\s*\n\s*string "([^"]+)"', monitor)
    require(sessions == [ALGORITHM] * 17, "real observed encrypted sessions or downgrade")
    rejected = [json.loads(line) for line in (directory / "service/rejected-sessions.jsonl").read_text().splitlines()]
    require(rejected == [{"algorithm": ALGORITHM}] == service["rejected_sessions"], "rejecting service fallback")
    require(service["real_service_sessions"] == {"dh": 17, "plain": 0}, "session receipt")
    for name in ["baseline", "candidate"]:
        require("Finished `dev` profile" in (directory / (name + "-build.log")).read_text(), "probe build missing")
        require(re.fullmatch(r"[0-9a-f]{64}", service["binaries"][name]["sha256"]), "binary identity")
    linkage = (directory / "candidate-linkage.txt").read_text()
    require(not any(name in linkage for name in ["libdbus", "libssl", "libcrypto"]), "unexpected dynamic native dependency")

    document = ET.fromstring((directory / "secrets.junit.xml").read_bytes())
    cases = document.findall(".//testcase")
    require(len(cases) == 15 and document.get("tests") == "15", "original secret-store case count")
    require(all(child.tag not in {"failure", "error", "skipped"} for case in cases for child in case), "secret-store non-pass")
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", (directory / "secrets-test.log").read_text())
    require("15 tests run: 15 passed, 0 skipped" in log and len(re.findall(r"^\s*PASS\s+\[", log, re.M)) == 15,
            "original secret-store raw results")
    result = {"schema": "keyring-native-joint-source-replay-v1", "source_commit": HEAD,
              "workflow_run": 41701057061, "job": 126144123622, "artifact_id": ARTIFACT,
              "artifact_bytes": 40023, "artifact_sha256": DIGEST, "exact_git_inputs_verified": 61,
              "native_dbus_build_and_identity_commands": 52, "original_service_operations_passed": 12,
              "actual_observed_encrypted_sessions": 17, "observed_plain_sessions": 0,
              "rejecting_service_downgrade_attempts": 0, "original_secret_store_tests": 15,
              "failed_or_skipped": 0, "binaries": service["binaries"], "status": "passed",
              "limits": "Exact combined 0b9 provider scope. Provider after-state is recorded by the original driver; no separate after-hash file is present. No full blocking CI or scientific acceptance."}
    output = args.artifacts / "keyring-native-REPLAY_VERIFIED.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"path": str(output), "sha256": sha(output.read_bytes()), "status": "passed"}))


if __name__ == "__main__":
    main()
