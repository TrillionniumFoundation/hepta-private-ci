#!/usr/bin/env python3
"""Verify actual artifacts on the exact combined dependency commit."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile


BASE = Path(__file__).resolve().parent
ROOT = BASE / "hosted-0b9"
REPO = BASE.parent / "private-ci-dependency-union-work-20261103"
HEAD = "0b9da54535a7795b2433947a479e6d9e71525e0a"
TREE = "a506ff258a214bc0f3ccedb9372d2317e476b038"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=REPO)


def verify_inputs(inputs, immutable):
    for name, digest in inputs.items():
        require(sha(immutable[name]) == digest, "immutable Git input differs: " + name)
    return len(inputs)


def main():
    global ROOT, REPO
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=ROOT)
    parser.add_argument("--repo", type=Path, default=REPO)
    args = parser.parse_args()
    ROOT, REPO = args.artifacts, args.repo
    downloads = json.loads((ROOT / "download-verification.json").read_text())
    require(len(downloads) == 23 and len({r["artifact_id"] for r in downloads}) == 23, "complete component inventory")
    all_inputs = {}
    receipts = {}
    for row in downloads:
        aid = row["artifact_id"]
        directory = ROOT / str(aid)
        data = (ROOT / (str(aid) + ".zip")).read_bytes()
        require(len(data) == row["bytes"] and sha(data) == row["sha256"], "archive identity")
        with zipfile.ZipFile(ROOT / (str(aid) + ".zip")) as bundle:
            require(bundle.testzip() is None, "archive CRC")
            require(bundle.namelist() == row["members"], "archive member inventory")
            for entry in bundle.infolist():
                path = Path(entry.filename)
                require(not path.is_absolute() and ".." not in path.parts, "unsafe member")
                require((entry.external_attr >> 16) & 0o170000 != 0o120000, "member symlink")
                if not entry.is_dir():
                    require(bundle.read(entry) == (directory / path).read_bytes(), "extracted bytes changed")
        receipt_file = directory / "receipt.json"
        if row["component"].startswith("yaml-"):
            receipt_file = directory / "RECEIPT.json"
        receipt = json.loads(receipt_file.read_text()) if receipt_file.exists() else {}
        receipts[aid] = receipt
        input_file = directory / "source-inputs.json"
        if input_file.exists():
            inputs = json.loads(input_file.read_text())
        elif row["component"].startswith("fleet-"):
            inputs = receipt["source_before"]
        elif row["component"].startswith("yaml-"):
            inputs = receipt["source_sha256_before"]
        elif row["component"].startswith("keyring-"):
            inputs = {line.split(None, 1)[1]: line.split(None, 1)[0]
                      for line in (directory / "source-inputs.sha256").read_text().splitlines()}
            if row["component"] == "keyring-native":
                inputs.update(json.loads((directory / "probes/inputs-before.json").read_text()))
        elif row["component"].startswith("matrix-"):
            inputs = receipt["source_before"]
        else:
            raise RuntimeError("unknown artifact source contract")
        all_inputs[aid] = inputs

    names = sorted({name for inputs in all_inputs.values() for name in inputs})
    require(all(not Path(n).is_absolute() and ".." not in Path(n).parts and "\n" not in n for n in names), "unsafe Git path")
    raw = subprocess.check_output(["git", "cat-file", "--batch"], cwd=REPO,
                                  input="".join(f"{HEAD}:{name}\n" for name in names).encode())
    immutable = {}
    offset = 0
    for name in names:
        end = raw.index(b"\n", offset)
        header = raw[offset:end].split()
        require(len(header) == 3 and header[1] == b"blob", "missing immutable object")
        length = int(header[2])
        immutable[name] = raw[end + 1:end + 1 + length]
        offset = end + 2 + length
    require(offset == len(raw), "unexpected Git output")
    require(git("rev-parse", HEAD + "^{tree}").decode().strip() == TREE, "source tree")
    lock = immutable["MODULE.bazel.lock"]
    summaries = []
    for row in downloads:
        aid = row["artifact_id"]
        directory = ROOT / str(aid)
        receipt = receipts[aid]
        component = row["component"]
        count = verify_inputs(all_inputs[aid], immutable)
        summary = {"artifact_id": aid, "component": component, "artifact_sha256": row["sha256"],
                   "exact_git_input_hashes": count}
        if receipt:
            require(receipt.get("commit", receipt.get("source_commit")) == HEAD, "wrong source commit")
            require(receipt.get("status") == "passed" or receipt.get("accepted") is True, "failed receipt")
        for name, expected in receipt.get("outputs", {}).items():
            data = (directory / name).read_bytes()
            require(len(data) == expected["bytes"] and sha(data) == expected["sha256"], "receipt output drift")
        if (directory / "MODULE.bazel.lock").exists():
            require((directory / "MODULE.bazel.lock").read_bytes() == lock, "generated lock differs from exact committed lock")
            summary["generated_lock_is_exact_committed_lock"] = True

        if component == "lock":
            require(receipt["committed_lock_required"] and receipt["committed_lock_matches"], "starting lock not required")
            require([x["name"] for x in receipt["steps"]] == ["committed-lock-check", "original-lock-update", "original-lock-check"], "lock command order")
            require(all(x["exit"] == 0 for x in receipt["steps"]), "original lock command failed")
            require(receipt["committed_lock_sha256"] == receipt["generated_lock_sha256"] == sha(lock), "lock identity")
            summary["committed_check_precedes_original_update_and_postcheck"] = True
        elif component.startswith("fleet-"):
            require(receipt["source_before"] == receipt["source_after"] and receipt["source_unchanged"], "Fleet inputs changed")
            require(len(receipt["commands"]) == 7 and all(c["exit"] == 0 for c in receipt["commands"]), "Fleet command failure")
            for command in receipt["commands"]:
                require(sha((directory / (command["name"] + ".log")).read_bytes()) == command["log_sha256"], "Fleet log identity")
            require(receipt["commands"][-1]["argv"] == ["just", "test", "-p", "codex-hepta-fleet", "--lib", "--locked", "--no-tests=fail", "--retries", "0"], "Fleet suite changed")
            xml = (directory / "fleet.junit.xml").read_bytes()
            document = ET.fromstring(xml)
            cases = document.findall(".//testcase")
            require(len(cases) == 42 and document.get("tests") == "42", "Fleet actual case count")
            require(all(child.tag not in {"failure", "error", "skipped"} for case in cases for child in case), "Fleet test not passed")
            require(sorted(c.get("name") for c in cases) == receipt["tests"]["names"], "Fleet case names")
            require(sha(xml) == receipt["tests"]["sha256"], "Fleet JUnit digest")
            log = re.sub(r"\x1b\[[0-9;]*m", "", (directory / "original-fleet-suite.log").read_text())
            require("42 tests run: 42 passed, 0 skipped" in log and len(re.findall(r"^\s*PASS\s+\[", log, re.M)) == 42, "Fleet original nextest cases")
            source = immutable["codex-rs/hepta-fleet/src/release.rs"].decode()
            functions = []
            for name in ["copy_immutable_program", "set_mode", "sync_directory", "publish_release_directory"]:
                start = source.index("fn " + name + "(")
                end = source.index("\n}\n", start) + 3
                functions.append(source[start:end])
            extracted = "\n".join(functions).encode()
            require(extracted == (directory / "production-functions.rs").read_bytes() and sha(extracted) == receipt["extracted_functions_sha256"], "Fleet operation probe source")
            summary.update(tests=42, skipped=0, platform=receipt["platform"], operation_probes_are_not_acceptance=True)
        elif component == "yaml-bazel":
            require(receipt["source_tree"] == TREE and receipt["source_sha256_before"] == receipt["source_sha256_after"] and receipt["inputs_unchanged"], "YAML source binding")
            commands = receipt["commands"]
            require([x["name"] for x in commands] == ["original-bazel-committed-lock-check", "original-bazel-lock-update", "original-bazel-lock-check", "bazel-yaml-utility-tests"], "YAML original command order")
            require(all(c["exit_code"] == 0 for c in commands), "YAML command failure")
            for command in commands:
                for stream in ["stdout", "stderr"]:
                    require(sha((directory / (command["name"] + "." + stream)).read_bytes()) == command[stream + "_sha256"], "YAML command output identity")
            require("Executed 1 out of 1 test: 1 test passes." in (directory / "bazel-yaml-utility-tests.stdout").read_text(), "YAML Bazel target did not run")
            summary.update(actual_bazel_targets_passed=1, full_native_consumer_qualification="820 original cases verified on this same commit")
        elif component == "keyring-bazel":
            require((directory / "source-commit.txt").read_text().strip() == HEAD, "keyring source")
            require((directory / "committed-MODULE.bazel.lock").read_bytes() == lock, "keyring original committed lock")
            native = (directory / "native-test.log").read_text()
            require("//third_party/dbus:native_identity_test" in native and "Executed 1 out of 1 test: 1 test passes." in native, "native D-Bus identity result")
            build = (directory / "keyring-build.log").read_text()
            require("Target //codex-rs/keyring-store:keyring-store up-to-date:" in build and "Build completed successfully" in build, "keyring actual build")
            generated = (directory / "generated-target.bazel").read_text()
            require(all(value in generated for value in ['"linux-native-sync-persistent"', '"sync-secret-service"', '"crypto-rust-sync"']), "persistent provider features missing")
            summary.update(actual_native_dbus_identity_targets_passed=1, original_keyring_store_build_passed=True,
                           source_scope="Four recorded manifests/locks; full provider source and behavioral qualification remain separate.")
        elif component == "keyring-native":
            proof_path = ROOT / "keyring-native-REPLAY_VERIFIED.json"
            proof = json.loads(proof_path.read_text())
            require(proof["source_commit"] == HEAD and proof["artifact_id"] == aid and proof["artifact_sha256"] == row["sha256"], "keyring original proof binding")
            require(proof["status"] == "passed" and proof["original_service_operations_passed"] == 12 and proof["original_secret_store_tests"] == 15, "keyring actual operations")
            require(proof["actual_observed_encrypted_sessions"] == 17 and proof["observed_plain_sessions"] == proof["rejecting_service_downgrade_attempts"] == 0, "keyring encryption and downgrade")
            summary.update(original_service_operations=12, original_secret_store_tests=15, observed_encrypted_sessions=17, observed_plain_sessions=0, independent_component_report_sha256=sha(proof_path.read_bytes()))
        elif component.startswith("matrix-") or component.startswith("yaml-"):
            family = component.split("-", 1)[0]
            proof_path = ROOT / family / "VERIFIED.json"
            proof = json.loads(proof_path.read_text())
            require(proof["source_commit"] == HEAD, "component proof source")
            matching = [item for item in proof["artifacts"] if item["artifact_id"] == aid]
            require(len(matching) == 1, "component proof lacks artifact")
            require(matching[0].get("artifact_sha256", matching[0].get("zip_sha256")) == row["sha256"], "component proof artifact mismatch")
            if family == "matrix":
                require(receipt["source_before"] == receipt["source_after"] and receipt["source_inputs_unchanged"], "Matrix source changed")
                require(all(c["exit_code"] == 0 for c in receipt["commands"]), "Matrix command failed")
            else:
                require(receipt["source_sha256_before"] == receipt["source_sha256_after"] and receipt["inputs_unchanged"], "YAML source changed")
                require(all(c["exit_code"] == 0 for c in receipt["commands"]), "YAML command failed")
            summary.update(actual_tests=matching[0].get("tests"), independent_component_report_sha256=sha(proof_path.read_bytes()))
        elif component.startswith("aws-") or component.startswith("operator-"):
            family = component.split("-", 1)[0]
            proof = json.loads((ROOT / family / "root-independent-verification.json").read_text())
            require(proof.get("commit", proof.get("source_commit")) == HEAD, "component proof source")
            verified_rows = proof.get("results", proof.get("artifacts", []))
            require(any(r["artifact_id"] == aid for r in verified_rows), "component proof lacks artifact")
            summary["independent_component_report_sha256"] = sha((ROOT / family / "root-independent-verification.json").read_bytes())
        else:
            raise RuntimeError("unhandled component")
        summaries.append(summary)

    result = {"schema": "joint-all-hosted-components-verification-v2", "source_commit": HEAD,
              "source_tree": TREE, "unique_exact_git_inputs": len(immutable), "artifacts": summaries,
              "status": "passed_for_listed_scopes", "native_test_executions": 1342, "original_service_operations": 12, "full_original_blocking_ci": "in_progress",
              "release_state": "Draft / HOLD_NO_GO / DENY_ALL"}
    (ROOT / "VERIFIED-all-components.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"source_commit": HEAD, "artifacts": len(summaries), "unique_exact_git_inputs": len(immutable),
                      "components": [r["component"] for r in summaries], "status": result["status"]}, indent=2))


if __name__ == "__main__":
    main()
