#!/usr/bin/env python3
"""Read existing Git objects and freeze an independent review; run no gate."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
PRIOR = ROOT / "followup-final-gate-1"
REPO = PRIOR / "objects.git"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def oid(kind, data):
    return hashlib.sha1(kind.encode() + b" " + str(len(data)).encode() + b"\0" + data).hexdigest()


def write_json(name, value):
    path = OUT / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def state():
    result = {name: sha((REPO / name).read_bytes()) if (REPO / name).is_file() else None for name in ("HEAD", "config", "index", "packed-refs")}
    result["refs"] = {str(p.relative_to(REPO)): sha(p.read_bytes()) for p in (REPO / "refs").rglob("*") if p.is_file()}
    return result


def tree_bytes(api):
    rows = []
    for row in api["tree"]:
        name = row["path"].encode()
        mode = row["mode"].lstrip("0").encode()
        rows.append((name, mode, bytes.fromhex(row["sha"])))
    rows.sort(key=lambda item: item[0] + (b"/" if item[1] == b"40000" else b""))
    return b"".join(mode + b" " + name + b"\0" + digest for name, mode, digest in rows)


def main():
    pins = {
        "post824_blob_gate.py": "d46ea0a8266efafd0ac7cbf8301527b5eaaa62f9a1ea1fdcf0e0073dcf5e11f9",
        "checkpoint_blob_gate.py": "8d1a37bdde54509c2227834d7f129a21d4e2c7374753136e024ebf69d091558d",
        "followup-final-gate-1/RESULT.json": "17275ff00a228e38b789d0267e54f68bbd994c8eb2999b1e78ec8e080afb0e01",
        "followup-final-gate-1/EXACT_OBJECTS.json": "736d68f7a70cd9b2533b30c93118af6c568b253a726b14b4e044fbdf0496c37d",
        "824-extra-base-objects/MANIFEST.json": "48e0d8ff9725b6ef9fcc043974c3fd75839646643efcf3f86affbaa2deac5c08",
    }
    for name, pin in pins.items():
        assert sha((ROOT / name).read_bytes()) == pin, name
    for name in ["post824_blob_gate.py", "checkpoint_blob_gate.py"]:
        ast.parse((ROOT / name).read_bytes(), filename=name)
    unsafe_env = [key for key in os.environ if key.startswith("GIT_") and key != "GIT_PAGER"]
    assert not unsafe_env, unsafe_env
    assert not os.environ.get("PYTHONOPTIMIZE") and sys.flags.optimize == 0
    assert not os.environ.get("GITHUB_STEP_SUMMARY")
    env = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    before = state()
    rows = json.loads((PRIOR / "EXACT_OBJECTS.json").read_bytes())
    assert len(rows) == len({row["oid"] for row in rows}) == 240
    prior = json.loads((PRIOR / "RESULT.json").read_bytes())
    assert prior["head"] == "8240292307116aa4063f7c63d8cdf48a0e8ef773"
    assert prior["tree"] == "2ec6ba4ee575eba4daee656ccf3d218074efd65c"
    assert prior["status"] == "PASS" and prior["exit_code"] == 0 and prior["repository_identity_unchanged"] is True
    payload = "".join(row["oid"] + "\n" for row in rows).encode()
    child = subprocess.run(["git", "cat-file", "--batch"], input=payload, cwd=REPO, env=env, capture_output=True, timeout=30)
    assert child.returncode == 0 and not child.stderr, child.stderr
    index, observed = 0, []
    objects = {}
    for expected in rows:
        end = child.stdout.index(b"\n", index)
        actual_oid, kind, length = child.stdout[index:end].decode().split()
        length = int(length)
        raw = child.stdout[end + 1:end + 1 + length]
        assert child.stdout[end + 1 + length:end + 2 + length] == b"\n"
        index = end + 2 + length
        assert actual_oid == expected["oid"] and kind == expected["type"]
        assert length == expected["bytes"] and sha(raw) == expected["sha256"] and oid(kind, raw) == actual_oid
        objects[actual_oid] = raw
        observed.append({"oid": actual_oid, "type": kind, "bytes": length, "sha256": sha(raw), "exact_readback": True})
    assert index == len(child.stdout)
    extra = json.loads((ROOT / "824-extra-base-objects/MANIFEST.json").read_bytes())
    api_raw = (ROOT / "824_EXTRA_WORKFLOW_TREE_API.json").read_bytes()
    assert sha(api_raw) == extra["source_tree_api_sha256"]
    api = json.loads(api_raw)
    assert not api["truncated"] and api["sha"] == "ccb62df653e1c169a0eb4bdcb5469d2ef1b9941f"
    tree = tree_bytes(api)
    assert oid("tree", tree) == api["sha"]
    extra_observed = []
    for row in extra["objects"]:
        raw = Path(row["local_path"]).read_bytes()
        assert len(raw) == row["bytes"] and sha(raw) == row["sha256"] and oid(row["type"], raw) == row["oid"]
        if row["type"] == "tree":
            assert tree == raw
        extra_observed.append({**row, "exact_readback": True})
    assert len(extra_observed) == 2
    paths = {".github/workflows": "ccb62df653e1c169a0eb4bdcb5469d2ef1b9941f", "scripts/check_blob_size.py": "18bc6175c274abaeabe3ef0c32d82627d498bbe7", ".github/blob-size-allowlist.txt": "7d46f41aa8fa354ce459471ba590804259548a33"}
    for path, expected in paths.items():
        value = subprocess.check_output(["git", "rev-parse", prior["head"] + ":" + path], cwd=REPO, env=env, timeout=10).decode().strip()
        assert value == expected
    codespell = next(row for row in api["tree"] if row["path"] == "codespell.yml")
    assert codespell["sha"] == "ed434625e55ada0bc8678b554153daa4a8d3dbc5" and codespell["type"] == "blob"
    gate = objects[paths["scripts/check_blob_size.py"]]
    allow = objects[paths[".github/blob-size-allowlist.txt"]]
    assert sha(gate) == "eb7a9eab936b7c7948ed13fbd6d6aca09aa38997c20685a8ee12d72e388d52c3"
    assert sha(allow) == "56a9a1cd05a0d81bba73a43c19e1451b213443f631dabacfa5b4e8d145e43d1c"
    assert gate == (PRIOR / "check_blob_size.py").read_bytes()
    assert allow == (PRIOR / "blob-size-allowlist.txt").read_bytes()
    after = state()
    assert before == after
    result = {
        "status": "PASS",
        "scope": "source and existing-object review only; no new candidate gate executed",
        "pins": pins,
        "prior_object_count": len(observed),
        "prior_objects_unique": True,
        "prior_objects_readback": observed,
        "extra_objects": extra_observed,
        "workflow_tree_exact_api_reconstruction": True,
        "workflow_tree_api_sha256": sha(api_raw),
        "codespell_old_blob_linked_to_exact_base": True,
        "original_checker_sha256": sha(gate),
        "original_allowlist_sha256": sha(allow),
        "original_byte_limit": 512000,
        "original_gate_deadline_seconds": 120,
        "before": before,
        "after": after,
        "repository_identity_unchanged": before == after,
        "environment": {"git_override_names": [key for key in os.environ if key.startswith("GIT_")], "unsafe_git_override_names": unsafe_env, "assertions_enabled": True, "github_step_summary_unset": True},
        "source_review": [
            "Fixed direct parent 824 and fixed base tree; prior result hash and original controller hash checked before use",
            "Each imported object verifies bytes, SHA256, Git object identity and actual readback; extra workflow tree and old codespell blob anchored through exact base",
            "Manifest paths use original checked_file canonical relative path, byte/SHA/GitSHA rules; duplicate paths and unchanged paths rejected; only regular/executable file modes admitted",
            "Reconstructed full tree must equal actual head API tree; single parent must equal 824; unsigned commit raw serialization must reproduce exact head Git SHA",
            "Full actual AM diff equals whole manifest, while any deletion or type change rejects; original checker and allowlist are verified at candidate paths with exact OID and SHA256",
            "Original checker is invoked with unchanged512000 bytes and120 second child deadline; exact output/exit and repository state are retained",
            "Controller uses only a fresh output bare object store for writes and contains no update-ref, checkout, reset, fetch or push operation; prior repository access is read-only cat-file"
        ],
        "material_findings": [],
        "limits": [
            "PASS means this exact controller and current frozen input inventory passed independent review, not that an uncreated future head has passed the gate",
            "Prior EXACT_OBJECTS JSON is recorded by the controller rather than pinned as a constant; this peer review pins its actual SHA and verified all240 unique raw objects. Git object identity and base-tree bindings remain mandatory in the controller",
            "Normal assertion-enabled Python and the observed clean Git override environment are part of this review scope; this is not a general hermetic execution sandbox"
        ],
        "new_execution": {"blob_gate_runs": 0, "native_runs": 0, "cargo_runs": 0, "model_calls": 0, "training_updates": 0, "remote_host_jobs": 0, "ref_updates": 0}
    }
    write_json("READONLY_INPUT_VERIFICATION.json", result)
    print(json.dumps({"status": result["status"], "prior_object_count": len(observed), "extra_objects": len(extra_observed), "repository_identity_unchanged": True, "verification_sha256": sha((OUT / "READONLY_INPUT_VERIFICATION.json").read_bytes())}, indent=2))


if __name__ == "__main__":
    main()
