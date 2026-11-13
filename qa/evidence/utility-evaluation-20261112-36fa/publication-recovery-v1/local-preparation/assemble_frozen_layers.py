#!/usr/bin/env python3
"""Assemble immutable reviewed source layers, without activation or qualification."""
import base64
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = json.loads((ROOT / "SOURCE_BASE_TREE.json").read_text())
ORIGINALS = json.loads((ROOT / "input/actual-git-originals.json").read_text())
before = {}
current = {}
history = []

def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }

def body(change, side):
    pin = change.get(side)
    if pin is None:
        return None
    if side + "_base64" in change:
        data = base64.b64decode(change[side + "_base64"], validate=True)
    elif side + "_content" in change:
        data = change[side + "_content"].encode()
    elif side + "_text" in change:
        data = change[side + "_text"].encode()
    elif "content" in pin:
        data = pin["content"].encode()
    else:
        data = ORIGINALS[pin["git_blob"]].encode()
    actual = identity(data)
    assert all(actual[k] == pin[k] for k in actual), (change["path"], side, actual, pin)
    return data

def install(label, changes, production_fixed=None):
    for change in changes:
        path = change["path"]
        assert change.get("mode", "100644") == "100644"
        prior, post = body(change, "before"), body(change, "after")
        if path not in current:
            if prior is None:
                assert path not in BASE["files"], (label, path, "new path already exists")
                before[path] = None
            else:
                assert identity(prior)["git_blob"] == BASE["files"].get(path), (label, path, "not cc57 first image")
                before[path] = prior
            current[path] = prior
        observed = current[path]
        operation = "exact declared predecessor"
        if observed != prior:
            assert label == "shared-production-v2-plus-linux-export-correction" and path.endswith("/lib.rs"), (label, path, "layer mismatch")
            assert prior == before[path]
            guarded_old = b'#[cfg(target_os = "linux")]\npub use circuit_feature_current::OriginalCircuitRetainedArtifactCheckpointV1;\n'
            guarded_new = b'#[cfg(target_os = "linux")]\npub use circuit_feature_current::OriginalCircuitPublishedEvidenceReadbackV1;\n'
            assert prior.count(guarded_old) == 1
            assert production_fixed == prior.replace(guarded_old, guarded_new + guarded_old)
            assert observed.count(guarded_old) == 1 and guarded_new not in observed
            post = observed.replace(guarded_old, guarded_new + guarded_old)
            assert post.replace(guarded_new, b"") == observed
            operation = "explicit non-overlapping guarded export insertion on Root-provider lib; corrected production delta only"
        elif production_fixed is not None and path.endswith("/lib.rs"):
            post = production_fixed
            operation = "exact production postimage followed by reviewed Linux guard correction"
        current[path] = post
        history.append({
            "layer": label, "path": path, "operation": operation,
            "declared_before": None if prior is None else identity(prior),
            "actual_before": None if observed is None else identity(observed),
            "actual_after": identity(post),
        })

def load(name):
    return json.loads((ROOT / "input" / name).read_text())

install("root-provider-v1", load("layer-01.json")["changes"])
install("root-provider-v2-public-idle-transport", load("idle-v2-manifest.json")["changes"])
install("fresh-training-B-component-v1", load("layer-02.json")["changes"])
install("actual-training-completion-observer-v1", load("layer-03.json")["changes"])
install("single-original-B-training-readback-v1", load("layer-04.json")["changes"])
linux = load("linux-export-increment.json")
assert len(linux["changes"]) == 1
correction = linux["changes"][0]
production = load("production-v2.json")
prod_lib = next(c for c in production["changes"] if c["path"].endswith("/lib.rs"))
ORIGINALS[prod_lib["after"]["git_blob"]] = body(prod_lib, "after").decode()
assert body(correction, "before") == body(prod_lib, "after")
fixed = body(correction, "after")
install("shared-production-v2-plus-linux-export-correction", production["changes"], fixed)

out = ROOT / "assembled-v1"
out.mkdir(exist_ok=False)
changes = []
patch = []
for path in sorted(current):
    old, new = before[path], current[path]
    assert new is not None
    target = out / "after" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as f:
        f.write(new)
    if old is not None:
        original = out / "before" / path
        original.parent.mkdir(parents=True, exist_ok=True)
        with original.open("xb") as f:
            f.write(old)
    changes.append({
        "path": path, "mode": "100644",
        "before": None if old is None else identity(old),
        "before_text": None if old is None else old.decode(),
        "after": identity(new), "after_text": new.decode(),
    })
    patch.extend(difflib.unified_diff(
        [] if old is None else old.decode().splitlines(keepends=True),
        new.decode().splitlines(keepends=True),
        fromfile="/dev/null" if old is None else "a/" + path,
        tofile="b/" + path,
    ))
with (out / "changes.patch").open("x") as f:
    f.writelines(patch)

shards = []
pending = []
for change in changes:
    proposed = pending + [change]
    size = len(json.dumps(proposed, ensure_ascii=False, sort_keys=True).encode())
    if pending and size > 400_000:
        shards.append(pending)
        pending = [change]
    else:
        pending = proposed
if pending:
    shards.append(pending)

packets = []
for number, shard in enumerate(shards, 1):
    name = f"SOURCE_PACKET.part-{number:02d}.json"
    content = (json.dumps({
        "format": "hepta.combined_source_preparation.part.v1",
        "base_commit": BASE["commit"], "source_src_tree": BASE["src_tree"],
        "status": "HOLD_UNFORMATTED_UNCOMPILED_UNEXECUTED_AND_FRESH_COMPANION_MISSING",
        "part": number, "parts": len(shards), "changes": shard,
    }, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    with (out / name).open("xb") as f:
        f.write(content)
    packets.append({"path": name, **identity(content), "source_files": len(shard)})

review = {
    "format": "hepta.combined_source_preparation.v1",
    "base_source": BASE["commit"], "source_src_tree": BASE["src_tree"],
    "status": "HOLD_UNFORMATTED_UNCOMPILED_UNEXECUTED_AND_FRESH_COMPANION_MISSING",
    "source_paths": len(changes),
    "modified_original_paths": sum(c["before"] is not None for c in changes),
    "new_paths": sum(c["before"] is None for c in changes),
    "layers": list(dict.fromkeys(h["layer"] for h in history)),
    "exact_operations": history,
    "source_packets": packets,
    "changes": [{k: v for k, v in c.items() if k not in ("before_text", "after_text")} for c in changes],
    "still_required": [
        "circuit_resident_candidate_provider_material_support_tests.rs actual new Fresh material builder",
        "full Fresh ten-owner normal and cold-recovery fixture",
        "new transport/attenuation/export tests and explicit test-only observation mounts",
        "complete CALLERS, protected/allowlist, QA and Root workflow registration",
        "original just fix/fmt/test and exact source/native qualification",
        "legitimate external A/owner authorities, independent B and complete frozen cost contract",
    ],
    "source_ref_moved": False, "h_calls": 0, "cargo_or_tests_executed": False,
    "real_qualified_task_chains": 0,
}
with (out / "MANIFEST.json").open("x") as f:
    json.dump(review, f, ensure_ascii=False, sort_keys=True, indent=2)
    f.write("\n")
print(json.dumps({
    "source_paths": review["source_paths"],
    "modified_original_paths": review["modified_original_paths"],
    "new_paths": review["new_paths"],
    "source_packets": packets,
    "merged_lib": identity(current["codex-rs/hepta-agentd/src/lib.rs"]),
    "manifest": identity((out / "MANIFEST.json").read_bytes()),
    "status": review["status"],
}, sort_keys=True))
