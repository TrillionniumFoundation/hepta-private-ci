#!/usr/bin/env python3
"""Read the exact failed Tee builder evidence; never run archived source."""
import argparse
import base64
import json
from pathlib import Path

from verify import GitBytes, canonical, emit_raw, fetch_artifact, require, sha

FOLDER = "qualification/bazel9-output-backport-20261104"


def main():
    require(__debug__, "optimized Python execution is not accepted")
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selected = [item for item in json.loads(args.manifest.read_bytes()) if item["key"] == args.key]
    require(len(selected) == 1, "unknown artifact key")
    spec = selected[0]
    args.output.mkdir(parents=True, exist_ok=False)
    metadata, raw, members = fetch_artifact(spec)
    (args.output / "original.zip").write_bytes(raw)
    prefix = spec["receipt_path"].removesuffix("receipt.json")
    receipt = json.loads(members[spec["receipt_path"]])
    require(receipt["status"] == "failed" and receipt["product_commit"] == spec["source"],
            "wrong original failed source")
    require(receipt["gtest"] is None and receipt.get("built_wrapper") is None,
            "this is not the pre-build version failure")
    git = GitBytes(args.source, spec["source"])
    try:
        expected = {name for name, entry in git.tree.items()
                    if name.startswith(FOLDER + "/") and "/" not in name[len(FOLDER) + 1:]
                    and entry[1] == "blob"} | {".bazelrc"}
        inputs = receipt["qualification_inputs"]
        require(set(inputs) == expected, "original direct helper input snapshot is incomplete")
        for name, identity in inputs.items():
            content = git.read(name)
            require(identity == {"bytes": len(content), "sha256": sha(content)},
                    "helper input differs from exact Git bytes: " + name)
        binding = json.loads(git.read(FOLDER + "/source-binding.json"))
        require(receipt["upstream_base"] == binding["upstream_base_commit"] and
                receipt["fix_commit"] == binding["fix_commit"], "upstream identity mismatch")
        outputs = receipt["evidence_outputs"]
        actual = {name[len(prefix):] for name in members if name.startswith(prefix)}
        require(actual == set(outputs) | {"receipt.json"}, "unexpected or missing helper output")
        for name, identity in outputs.items():
            content = members[prefix + name]
            require(identity == {"bytes": len(content), "sha256": sha(content)},
                    "recorded output differs: " + name)
        steps = receipt["steps"]
        names = [step["name"] for step in steps]
        require(len(names) == len(set(names)), "duplicate helper step")
        require(names[-1] == "builder-version" and all(step["exit"] == 0 for step in steps),
                "original failure did not occur after successful version command")
        require("build-original-tw-target" not in names and "test-complete-original-tw-target" not in names,
                "unexpected C++ or GTest execution")
        version_step = steps[-1]
        command = version_step["command"]
        require(command[-2:] == ["version", "--gnu_format"] and
                any(value.startswith("--output_base=") for value in command) and
                any(value.startswith("--output_user_root=") for value in command),
                "original version invocation changed")
        require(command[0].lower().endswith((".exe", ".bat", ".cmd")), "missing actual Windows launcher path")
        for name, identity in binding["files"].items():
            content = members[prefix + Path(name).name]
            require(len(content) == identity["patched_bytes"] and sha(content) == identity["patched_sha256"],
                    "actual patched upstream source differs: " + name)
        exact_files = {}
        for relative in ("builder-version.stdout", "builder-version.stderr", "receipt.json"):
            name = prefix + relative
            content = members[name]
            exact_files[name] = {"bytes": len(content), "sha256": sha(content)}
            emit_raw(name, content)
            print("EXACT_ORIGINAL_FILE_BASE64=" + json.dumps({
                "path": name, **exact_files[name], "base64": base64.b64encode(content).decode()
            }, separators=(",", ":")), flush=True)
        report = {
            "schema": 1, "repository": spec["repository"], "source": spec["source"],
            "original_run": spec["run_id"], "artifact_id": spec["artifact_id"],
            "zip_bytes": len(raw), "zip_sha256": sha(raw), "all_member_crc": True,
            "original_qualification_status": "failed",
            "helper_inputs": {"count": len(inputs), "all_exact_git_bytes": True,
                              "map_sha256": sha(canonical(inputs))},
            "outputs": len(outputs), "actual_version_command": version_step,
            "exact_files": exact_files, "original_cpp_executions": 0,
            "original_gtest_executions": 0, "original_robrix_executions": 0,
            "evidence_verification": "passed",
            "scope": "Read-only original pre-build failure diagnosis, not product qualification.",
        }
        (args.output / "VERIFIED.json").write_bytes(json.dumps(report, indent=2).encode() + b"\n")
        (args.output / "receipt.json").write_bytes(members[spec["receipt_path"]])
        (args.output / "artifact-metadata.json").write_bytes(json.dumps(metadata, indent=2).encode() + b"\n")
        print("TEE_EVIDENCE_VERIFIED_JSON=" + json.dumps(report, separators=(",", ":")), flush=True)
    finally:
        git.close()


if __name__ == "__main__":
    main()
