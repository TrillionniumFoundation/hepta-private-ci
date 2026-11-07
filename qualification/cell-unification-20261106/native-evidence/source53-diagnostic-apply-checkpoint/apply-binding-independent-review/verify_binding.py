#!/usr/bin/env python3
"""Verify literal-only application binding without importing or running it."""
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(__file__).resolve().parent
PREP = ROOT / "source53-apply-preparation"
BINDING = ROOT / "source53-apply-binding"
NAMES = ["EXPECTED_COMMIT", "EXPECTED_TREE", "EXPECTED_CHANGED_COUNT", "INPUT_BYTES", "INPUT_SHA256",
         "SOURCE53_MANIFEST_PIN", "DELTA_MANIFEST_PIN", "CANDIDATE_PINS"]


def need(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def parse(raw):
    tree = ast.parse(raw)
    assignments = {n.targets[0].id: n for n in tree.body if isinstance(n, ast.Assign)
                   and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
    return tree, assignments


def put(name, raw):
    p = DEST / name
    if p.exists():
        need(p.read_bytes() == raw, "refuse overwrite: " + name)
    else:
        with p.open("xb") as stream:
            stream.write(raw)
    return pin(raw)


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def main():
    template = (PREP / "native-source53-apply-template.py").read_bytes()
    bound = (BINDING / "native-source53-apply-bound.py").read_bytes()
    final = (BINDING / "native-source53-apply.py").read_bytes()
    need(pin(template)["sha256"] == "cf5b74eaa8532166fe8a29386982aeaaca4a579cf37fa227c2d3f31ba04fab2d", "template differs")
    need(pin(bound) == {"bytes": 39811, "sha256": "58bc626c713a437faf969a96aaf7e5302f096bbc6d36fd849fdc1bbf0761aa72",
                        "git_blob": "f076e846ac50a94aa12a4b0eea27dad8f559b12d"}, "bound differs")
    need(pin(final) == {"bytes": 39810, "sha256": "5265e05a75c1aa4ba4eb36257a704306c17dc66ef78c2f7386a5beeb990b9168",
                        "git_blob": "236972ca6403d06b1222770a61afc045274b8f8b"}, "final differs")
    _, old_nodes = parse(template)
    _, new_nodes = parse(bound)
    parse(final)
    bindings = json.loads((BINDING / "BINDINGS.json").read_bytes())
    need(set(bindings) == set(NAMES), "eight bindings differ")
    old_lines = template.decode().splitlines(keepends=True)
    new_lines = bound.decode().splitlines(keepends=True)
    for name in NAMES:
        need(ast.literal_eval(old_nodes[name].value) is None, "reference literal was not None")
        need(ast.literal_eval(new_nodes[name].value) == bindings[name], "bound literal differs")
    for name in sorted(NAMES, key=lambda n: new_nodes[n].lineno, reverse=True):
        old, new = old_nodes[name], new_nodes[name]
        new_lines[new.lineno - 1:new.end_lineno] = old_lines[old.lineno - 1:old.end_lineno]
    need("".join(new_lines).encode() == template, "whole-file inverse to original template differs")
    need(bound.count(b"FROZEN = False\n") == 1
         and bound.replace(b"FROZEN = False\n", b"FROZEN = True\n", 1) == final, "final is not only the frozen flag")
    need(bindings["EXPECTED_COMMIT"] == "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
         and bindings["EXPECTED_TREE"] == "440d4a8e09af4009e4d9ea067388826308da8803"
         and bindings["EXPECTED_CHANGED_COUNT"] == 197, "actual source53 identity differs")
    archive = (PREP / "derived/source53-apply-input.tar.gz").read_bytes()
    need(len(archive) == bindings["INPUT_BYTES"] and pin(archive)["sha256"] == bindings["INPUT_SHA256"], "archive binding differs")
    expected_members = {"source53-manifest.json", "delta-manifest.json", "candidate.patch"}
    expected_members |= {side + "/" + path for side in ("before", "after") for path in bindings["CANDIDATE_PINS"]}
    members = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for item in tar.getmembers():
            path = PurePosixPath(item.name)
            need(item.isfile() and not item.issym() and not item.islnk()
                 and not path.is_absolute() and ".." not in path.parts, "unsafe input member")
            need(item.name in expected_members and item.name not in members and item.mode == 0o600, "member set or transport mode differs")
            raw = tar.extractfile(item).read()
            need(len(raw) == item.size, "truncated member")
            members[item.name] = raw
    need(set(members) == expected_members and len(members) == 7, "seven-member exact set differs")
    for name, key in (("source53-manifest.json", "SOURCE53_MANIFEST_PIN"), ("delta-manifest.json", "DELTA_MANIFEST_PIN")):
        need(pin(members[name]) == bindings[key], "manifest/delta pin differs")
    manifest = json.loads(members["source53-manifest.json"])
    delta = json.loads(members["delta-manifest.json"])
    need(manifest["source_tree"] == delta["source_tree"] == bindings["EXPECTED_TREE"]
         and manifest["source_commit"] == delta["source_commit"] == bindings["EXPECTED_COMMIT"], "input source identity differs")
    need(manifest["source_parent_commit"] == delta["source_before_commit"] == "1e0910becc37383e6d17ecf861ea844fd07d8862", "parent differs")
    need(manifest["diagnostic_only"] is True and delta["diagnostic_only"] is True
         and manifest["behavior_repair_claimed"] is False and delta["behavior_repair_claimed"] is False, "diagnostic classification changed")
    need(delta["patch"] == {"path": "candidate.patch", **pin(members["candidate.patch"])}, "patch pin differs")
    need({r["path"]: {"before": r["before"], "after": r["after"]} for r in delta["files"]} == bindings["CANDIDATE_PINS"], "delta/candidate binding differs")
    for path, pair in bindings["CANDIDATE_PINS"].items():
        for side in ("before", "after"):
            need(pair[side] == {"mode": "100644", **pin(members[side + "/" + path])}, "source member pin differs")
    report = {"schema": "hepta.source53-apply-independent-binding-review.v1", "status": "STATIC_BINDING_CLEAR_NOT_EXECUTED",
              "template": pin(template), "bound": pin(bound), "final": pin(final),
              "AST_parsed": True, "runner_imported_or_executed": False,
              "exact_bound_literal_count": 8, "bound_literal_names": NAMES,
              "eight_literal_inverse_restores_entire_original_template": True,
              "final_changes_only_FROZEN_false_to_true": True,
              "source_commit": bindings["EXPECTED_COMMIT"], "source_tree": bindings["EXPECTED_TREE"],
              "source_parent_commit": manifest["source_parent_commit"], "actual_changed_count": 197,
              "input_archive": pin(archive), "members": [{"path": p, **pin(b)} for p, b in sorted(members.items())],
              "all_before_after_Git_modes_100644": True,
              "original_failure_and_fullsource_guards_unchanged": True,
              "diagnostic_only": True, "behavior_repair_claimed": False,
              "native_application_performed_by_reviewer": False, "Rust_or_gates_executed": False,
              "root_exact_launch_authorization_still_required": True}
    put("INDEPENDENT-REVIEW.json", jb(report))
    files = [{"path": p.name, **pin(p.read_bytes())} for p in sorted(DEST.iterdir())
             if p.is_file() and p.name != "HANDOFF-MANIFEST.json"]
    handoff = {"schema": "hepta.source53-apply-binding-review-handoff.v1", "files": files,
               "file_count": len(files), "total_bytes": sum(r["bytes"] for r in files)}
    put("HANDOFF-MANIFEST.json", jb(handoff))
    print(json.dumps({"status": "CLEAR", "final": pin(final), "review": pin(jb(report)), "handoff": pin(jb(handoff))}, indent=2))


if __name__ == "__main__":
    main()
