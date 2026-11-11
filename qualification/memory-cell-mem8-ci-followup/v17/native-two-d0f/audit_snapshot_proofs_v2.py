"""Read raw source snapshots; never execute archived code or native commands."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


HEAD = "d0f6507e08f7f5c5855f5164d07c049a34d1a6d9"
TREE = "658fa040046285116b1fd81b94ff8c96444072ad"
PARENT = "408226fc670bfa8c1736e2b264750b549237b7c4"
JUNIT = "codex-rs/target/nextest/local/junit.xml"
ROOT = Path(__file__).resolve().parent


def digest(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    files = args.files.resolve()
    plan = json.loads((ROOT / "FROZEN_PLAN.json").read_text())
    locks = {path: {key: plan["files"][path][key] for key in ("bytes", "sha256")}
             for path in ("codex-rs/Cargo.lock", "MODULE.bazel.lock")}
    checks, snapshots = [], {}

    def check(name, condition, detail=None):
        checks.append({"name": name, "passed": bool(condition), "detail": detail})
        return bool(condition)

    for identity_path in sorted(files.glob("*/identity.json")):
        directory = identity_path.parent
        name = directory.name
        identity = json.loads(identity_path.read_text())
        status = (directory / "git-status.raw").read_bytes()
        untracked = (directory / "untracked-including-ignored.raw").read_bytes()
        patches = {path: (directory / path).read_bytes() for path in
                   ("working-tree.patch", "index.patch", "combined.patch", "qualified-source.patch")}
        postimages = json.loads((directory / "postimages.json").read_text())
        check(name + ":raw_dirty_agrees", identity.get("dirty") is bool(status or untracked))
        check(name + ":exact_source_locks", identity.get("commit") == HEAD and identity.get("tree") == TREE
              and identity.get("parents") == [] and identity.get("locks") == locks)
        check(name + ":postimage_unique_paths", isinstance(postimages, list)
              and len({row["path"] for row in postimages}) == len(postimages))
        for row in postimages:
            path = PurePosixPath(row["path"])
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe source postimage path")
            actual = directory / "postimages" / path
            if row["state"] == "file":
                check(name + ":postimage:" + row["path"], actual.is_file() and not actual.is_symlink()
                      and digest(actual.read_bytes()) == {key: row[key] for key in ("bytes", "sha256")})
            else:
                check(name + ":nonfile_postimage:" + row["path"], row["state"] in {"deleted", "symlink"}
                      and not actual.exists())
        if identity.get("dirty") is False:
            check(name + ":clean_has_no_raw_rewrite", not status and not untracked
                  and all(not raw for raw in patches.values()) and postimages == [])
        snapshots[name] = {"identity": identity, "status": digest(status), "untracked": digest(untracked),
                           "patches": {key: digest(value) for key, value in patches.items()}, "postimages": postimages}

    baseline = snapshots.get("source-before", {}).get("identity")
    check("baseline_exists_clean", isinstance(baseline, dict) and baseline.get("dirty") is False)
    phases = []
    for path in sorted(files.glob("phase-*.json")):
        if path.name.endswith((".intent.json", ".not-run.json")):
            continue
        phase = json.loads(path.read_text())
        prefix = path.stem
        if "kind" not in phase:
            continue
        proof = {"phase": prefix, "kind": phase["kind"], "status": phase.get("status"),
                 "original_exit": phase.get("command_exit_code")}
        for field, suffix in (("before", "-source-before"), ("after", "-source-after"),
                              ("source_immediately_after_command", "-observed-source")):
            if field in phase:
                check(prefix + ":bound_raw_snapshot:" + field,
                      snapshots.get(prefix + suffix, {}).get("identity") == phase[field])
            elif phase.get("status") == "passed_clean":
                check(prefix + ":required_snapshot:" + field, False)
        if phase.get("status") == "passed_clean":
            check(prefix + ":passed_known_zero_exit", phase.get("command_exit_code") == 0)
            check(prefix + ":passed_before_after_clean", phase.get("before") == phase.get("after") == baseline)
            immediate = phase.get("source_immediately_after_command")
            if phase["kind"] in {"helpers", "fix"}:
                check(prefix + ":no_intermediate_source_drift", immediate == baseline)
            elif phase["kind"] == "native":
                observed = snapshots.get(prefix + "-observed-source", {})
                original = phase.get("junit_artifact", {})
                junit_row = {key: original.get(key) for key in ("bytes", "sha256")}
                postimages = observed.get("postimages", [])
                check(prefix + ":only_current_junit_untracked",
                      (files / (prefix + "-observed-source") / "untracked-including-ignored.raw").read_bytes() == JUNIT.encode() + b"\0")
                check(prefix + ":native_no_tracked_source_rewrite",
                      all(row["bytes"] == 0 for row in observed.get("patches", {}).values())
                      and len(observed.get("patches", {})) == 4)
                check(prefix + ":native_single_junit_postimage",
                      len(postimages) == 1 and postimages[0].get("path") == JUNIT
                      and postimages[0].get("state") == "file"
                      and {key: postimages[0].get(key) for key in ("bytes", "sha256")} == junit_row)
                check(prefix + ":exact_retained_junit_bytes",
                      original.get("original_path") == JUNIT
                      and (files / original.get("retained_path", "__MISSING__")).is_file()
                      and digest((files / original["retained_path"]).read_bytes()) == junit_row
                      and (files / original["retained_path"]).read_bytes()
                      == (files / (prefix + "-observed-source") / "postimages" / JUNIT).read_bytes())
                check(prefix + ":native_immediate_identity_only_dirty",
                      isinstance(immediate, dict) and {**immediate, "dirty": False} == baseline
                      and immediate.get("dirty") is True)
        phases.append(proof)

    result = json.loads((files / "RESULT.json").read_text())
    collection = json.loads((files / "COLLECTION.json").read_text()) if (files / "COLLECTION.json").exists() else None
    for field, name in (("before", "source-before"), ("after", "source-after")):
        if field in result:
            check("result:" + field, snapshots.get(name, {}).get("identity") == result[field])
    if collection and "source" in collection:
        check("collection_raw_snapshot_bound", snapshots.get("source-at-collection", {}).get("identity") == collection["source"])
    output = {"schema_version": 1, "scope": "Supplementary independent raw-snapshot proof only; does not convert incomplete native/lint qualification into success",
              "source_head": HEAD, "source_tree": TREE, "checks": checks, "snapshots": snapshots, "phases": phases,
              "all_observed_raw_proofs_consistent": all(row["passed"] for row in checks),
              "original_driver_status": result.get("status"), "original_collection_status": (collection or {}).get("status"),
              "parent_view_boundary": {"frozen_source_checkout_fetch_depth": 1, "observed_git_show_parent_view": [], "actual_full_commit_parent_from_source_binding": PARENT, "meaning": "The shallow Git walk view is empty; it is not a claim that the underlying immutable commit has no parent."},
              "native_or_model_executions_started": 0}
    with args.output.open("x") as stream:
        json.dump(output, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"all_observed_raw_proofs_consistent": output["all_observed_raw_proofs_consistent"],
                      "snapshots": len(snapshots), "phases": len(phases), "checks": len(checks)}))
    return 0 if output["all_observed_raw_proofs_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
