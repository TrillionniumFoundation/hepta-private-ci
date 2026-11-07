"""Prepare source53 finalizer scope evidence from closed local bytes only."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent


def need(value, message):
    if not value:
        raise RuntimeError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def load(relative):
    raw = (WORK / relative).read_bytes()
    return json.loads(raw), {"path": relative, **pin(raw)}


def normalized(rows):
    result = {row["path"]: {key: row[key] for key in ("path", "bytes", "sha256", "git_blob", "mode")} for row in rows}
    need(len(result) == len(rows), "duplicate source paths")
    return result


def main():
    source, source_pin = load("source53-apply-preparation/derived/native-candidate-r30-source.json")
    parent, parent_pin = load("source53-apply-preparation/references/source52-actual-manifest.json")
    old_scope, scope_pin = load("source52-final-scope-preparation/EXPECTED-SELECTION.json")
    old_packages, packages_pin = load("source52-final-scope-preparation/PACKAGE-ARGS.json")
    primary, primary_pin = load("source52-finalize-preparation/input/PRIMARY-SOURCE-PINS.json")
    metadata_path = WORK / "native-validation-results/r29-archive-closed/original/evidence/native-workspace-r29-metadata.json"
    metadata_raw = metadata_path.read_bytes()
    need(pin(metadata_raw)["sha256"] == "b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d",
         "historical source52 metadata mismatch")
    metadata = json.loads(metadata_raw)
    need(source["source_commit"] == "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
         and source["source_tree"] == "440d4a8e09af4009e4d9ea067388826308da8803"
         and source["source_parent_commit"] == parent["source_commit"]
         and parent["source_commit"] == "1e0910becc37383e6d17ecf861ea844fd07d8862",
         "registered source53/parent identity differs")
    need(source["diagnostic_only"] is True and source["behavior_repair_claimed"] is False,
         "diagnostic source classification differs")
    files, prior = normalized(source["changed_files"]), normalized(parent["changed_files"])
    new_paths = {
        "codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs",
        "codex-rs/app-server/tests/suite/v2/bedrock_setup.rs",
    }
    need(len(files) == 197 and len(prior) == 195 and set(files) == set(prior) | new_paths
         and not new_paths & set(prior) and all(files[path] == row for path, row in prior.items()),
         "source53 must retain all195 rows and add only the two existing Bedrock leaves")
    need(all(files[path]["mode"] == "100644" for path in new_paths), "Bedrock source mode differs")
    for key in ("cargo_lock_sha256", "bazel_lock_sha256"):
        need(source[key] == parent[key], "dual lock identity differs")
    rust = sorted(path for path in files if path.endswith(".rs"))
    python = sorted(path for path in files if path.startswith("scripts/") and path.endswith(".py"))
    need(len(rust) == 183 and python == ["scripts/run-nextest.py", "scripts/test_run_nextest_helpers.py"],
         "expected default format selection differs")
    need(set(rust) == set(old_scope["rust_paths"]) | new_paths, "source52 Rust selection not retained exactly")
    members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
    need(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
         and set(members) == set(defaults), "historical default workspace scope differs")
    source_root = PurePosixPath("/home/alex/work/hepta-cell-unified-20261106-a/source")
    roots = {}
    for row in metadata["packages"]:
        if row["id"] not in members:
            continue
        manifest = PurePosixPath(row["manifest_path"]).relative_to(source_root).as_posix()
        directory = PurePosixPath(manifest).parent.as_posix()
        need(directory not in roots, "ambiguous package owner root")
        roots[directory] = {"package": row["name"], "package_id": row["id"],
                            "package_directory": directory, "manifest_path": manifest,
                            "edition": row["edition"], "default_workspace_member": row["id"] in defaults}
    owners = {}
    for path in rust:
        matches = [root for root in roots if path.startswith(root + "/")]
        need(matches, "unowned Rust leaf: " + path)
        root = max(matches, key=lambda value: len(PurePosixPath(value).parts))
        owner = owners.setdefault(roots[root]["package"], {**roots[root], "rust_paths": []})
        need(owner["package_directory"] == root, "ambiguous owner package name")
        owner["rust_paths"].append(path)
    for row in owners.values():
        row["rust_path_count"] = len(row["rust_paths"])
    names = sorted(owners)
    need(len(names) == 26 and names == old_packages["owners"], "26-owner scope changed")
    need(set(new_paths) <= set(owners["codex-app-server"]["rust_paths"]), "new leaves have wrong owner")
    need(all(row["edition"] == "2024" and row["default_workspace_member"] for row in owners.values()),
         "owning edition/default membership changed")
    primary_rows = []
    for row in primary:
        need(row["path"].startswith("original/"), "primary pin prefix differs")
        relative = row["path"][len("original/"):]
        raw = (WORK / "source51-final-scope-readonly/original" / relative).read_bytes()
        need(pin(raw) == {key: row[key] for key in ("bytes", "sha256", "git_blob")},
             "primary source pin mismatch: " + relative)
        need(relative not in new_paths, "source53 changed a primary formatter/dependency input")
        if relative in files:
            need({key: files[relative][key] for key in ("bytes", "sha256", "git_blob")} == pin(raw),
                 "primary input differs from actual source manifest")
        primary_rows.append({"path": relative, **pin(raw)})
    need(len(primary_rows) == 34, "primary input count differs")
    report = {
        "schema": "hepta.source53-finalizer-preliminary-scope-risk-audit.v1",
        "classification": "READ_ONLY_PREPARATION_NOT_FRESH_R31_SCOPE",
        "source53_manifest": source_pin, "source52_manifest": parent_pin,
        "source53_registered_commit": source["source_commit"], "source53_registered_tree": source["source_tree"],
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "source52_195_rows_preserved": True, "new_changed_manifest_leaves": sorted(new_paths),
        "source_paths": 197, "rust_paths_count": 183, "other_paths_count": 14,
        "python_paths": python, "python_paths_count": 2,
        "unchanged_owner_names": names, "owner_count": 26,
        "owners_from_historical_metadata": [owners[name] for name in names],
        "historical_metadata": {"path": str(metadata_path.relative_to(WORK)), **pin(metadata_raw)},
        "historical_metadata_observed_source_commit": parent["source_commit"],
        "historical_metadata_observed_source_tree": parent["source_tree"],
        "old_metadata_claimed_as_current_source53": False, "fresh_r31_metadata_received": False,
        "old_source52_selection": scope_pin, "old_source52_fix_packages": packages_pin,
        "primary_pins_file": primary_pin, "unchanged_primary_inputs": primary_rows,
        "expected_default_head": "bef6fa7645df9df12b69fda499e97eed25de6c75",
        "expected_fix_command": ["just", "fix", "--locked", *[v for n in names for v in ("-p", n)]],
        "expected_format_command": ["just", "fmt"],
        "expected_python_formatter": ["uv", "run", "--frozen", "--project", "scripts", "ruff", "format",
                                      "./scripts/run-nextest.py", "./scripts/test_run_nextest_helpers.py"],
        "all_flag_or_extra_allow_staged_authorized": False,
        "known_remaining_binding_risks": [
            "Future R30 nineteen originals plus natural outer0 must certify exact1345 IDs on source53.",
            "Future R31 eighteen originals plus natural outer0 must certify complete exact20228 IDs on source53; original R29 failed100 remains historical.",
            "Source52 R28 three-phase PASS is historical and cannot replace source53 R30/R31 qualification.",
            "Fresh R31 metadata and four newly frozen scope files are missing; this historical-metadata computation cannot populate their current-source verified fields.",
            "Actual tool inventory, environment, executable/venv/rustup-shim bytes must be bound and rechecked before commands; old source51 inventory is not a source53 observation.",
            "Default HEAD selection must be nonempty and exactly183 Rust+2 Python; no --all/--base/HEAD workaround.",
            "Original just fix scoped26 may fail, or modify out-of-scope files; retain raw return, patch and actual working bytes, stop before fmt, never add --allow-staged automatically.",
            "A post-fix/post-format tree is a new source artifact; no tests after those mutations and no automatic transfer of tested-tree qualification.",
            "Diagnostic-only passing gates do not prove a Bedrock behavior repair; the classification must survive final snapshots and reports.",
        ],
        "native_rust_git_metadata_formatter_executed": False,
        "runtime_tool_identity_queried": False,
    }
    path = ROOT / "SCOPE-DEPENDENCY-RISK-AUDIT.json"
    with path.open("xb") as output:
        output.write((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"report": pin(path.read_bytes()), "owners": names, "rust": len(rust), "python": len(python),
                      "source_rows": len(files), "qualification": report["classification"]}))


if __name__ == "__main__":
    main()
