#!/usr/bin/env python3
"""Admit actual string/template Cargo fix compilers, without executing compilers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib

OWNERS = {"codex-utils-string": "utils/string", "codex-utils-template": "utils/template"}
FEATURES = ",".join(name + "/hia-native" for name in OWNERS)
FIX_ARGUMENTS = ["--locked", "--all-targets", "-p", "codex-utils-string",
                 "-p", "codex-utils-template", "--features", FEATURES]


def options(arguments, name):
    result = []
    for index, value in enumerate(arguments):
        if value == name:
            require(index + 1 < len(arguments), "missing compiler option value")
            result.append(arguments[index + 1])
        elif value.startswith(name + "="):
            result.append(value[len(name) + 1:])
    return result


def bound_json(row):
    common.verify(row)
    return json.loads(Path(row["path"]).read_bytes())


def checkout(repo):
    require(not common.git(repo, "ls-files", "--others", "-z"),
            "untracked or ignored files appeared inside the producer")
    return {"producer": str(repo), "identity": common.clean_identity(repo),
            "refs": common.git(repo, "for-each-ref", "--format=%(refname) %(objectname)").decode(),
            "index_entries_sha256": hashlib.sha256(common.git(repo, "ls-files", "--stage", "-z")).hexdigest(),
            "files": common.producer_files(repo)}


def unchanged(repo, before):
    value = json.loads(before.read_bytes())
    require(value["schema"] == "codex.hia.scoped-owner-fix-source.v1" and value["passed"],
            "source snapshot was not completed")
    require(value["observer"] == common.binding(__file__), "source observer changed")
    require(checkout(repo) == value["checkout"], "source, mode, HEAD, index, refs or file set changed")
    return {"before": common.binding(before), "source_files": len(value["checkout"]["files"]),
            "complete_source_unchanged": True, "head_index_refs_unchanged": True}


def paired_compilers(report, run, context, repo):
    expected = {"bridge_starts": sorted(run.glob("bridge-*.begin.json")),
                "bridge_completions": sorted(run.glob("bridge-*.end.json"))}
    for key, paths in expected.items():
        require(report[key] == [common.binding(path) for path in paths], "bridge inventory differs")
    starts = {p.name.removesuffix(".begin.json"): p for p in expected["bridge_starts"]}
    ends = {p.name.removesuffix(".end.json"): p for p in expected["bridge_completions"]}
    require(starts and starts.keys() == ends.keys(), "missing or unpaired compiler record")
    rustc, clippy = context["rustc"], context["clippy"]
    helper, workspace = str(repo / "hia/similar_policy.py"), str(repo / fix.WORKSPACE)
    events = []
    for key, path in sorted(starts.items()):
        begin, end = json.loads(path.read_bytes()), json.loads(ends[key].read_bytes())
        require(begin["schema"] == "codex.hia.fix-bridge-start.v1"
                and end["start"] == common.binding(path), "compiler begin/completion binding differs")
        require(end["returncode"] == 0 and "exception" not in end, "a real compiler bridge failed")
        event = end["result"]
        kind, arguments = begin["kind"], begin["arguments"]
        require(kind in ("outer", "workspace") and arguments, "unknown compiler entry")
        require(event["arguments"] == arguments and event["kind"] == kind
                and event["returncode"] == 0 and event["context"] == report["context"],
                "compiler event or context differs")
        nested = kind == "outer" and arguments[0] == workspace
        if nested:
            require(len(arguments) > 1 and arguments[1] == rustc, "unknown nested compiler")
            command = arguments
        else:
            require(arguments[0] == rustc, "compiler is not the pinned rustc")
            prefix = [clippy, rustc] if kind == "workspace" else [rustc]
            require(Path(event["command"][0]).resolve(strict=True) == Path(sys.executable).resolve(),
                    "compiler bridge used a different Python interpreter")
            command = [event["command"][0], helper, *prefix, *arguments[1:]]
        require(event["delegates_helper"] is (not nested) and event["command"] == command,
                "compiler bypassed or duplicated the admitted helper")
        native_apply_patch = (options(arguments, "--crate-name") == ["codex_apply_patch"]
                              and 'feature="hia-native"' in options(arguments, "--cfg"))
        require(event["native_owner"] is native_apply_patch, "legacy apply-patch counter scope changed")
        events.append({"event": event, "begin": common.binding(path), "end": common.binding(ends[key])})
    require(report["actual_native_helper_calls"] == sum(
        row["event"]["native_owner"] and row["event"]["delegates_helper"] for row in events),
        "apply-patch-only compiler count differs")
    return events


def actual_metadata(path, repo):
    value = json.loads(path.read_bytes())
    require(value["version"] == 1 and value["workspace_root"] == str(repo / "codex-rs"),
            "metadata workspace differs")
    target_dir = Path(value["target_directory"]).resolve(strict=True)
    require(target_dir == Path(os.environ["CARGO_TARGET_DIR"]).resolve(strict=True)
            and not target_dir.is_relative_to(repo), "metadata target differs or enters the source")
    packages = {row["id"]: row for row in value["packages"]}
    require(len(packages) == len(value["packages"])
            and set(packages) == set(value["workspace_members"]), "metadata is not the full no-deps workspace")
    selected = {}
    workspace = tomllib.loads((repo / "codex-rs/Cargo.toml").read_text())
    for name, relative in OWNERS.items():
        manifest = repo / "codex-rs" / relative / "Cargo.toml"
        source = manifest.parent / "src/lib.rs"
        declared = tomllib.loads(manifest.read_text())
        require(declared["package"]["name"] == name and declared["lints"] == {"workspace": True},
                "owner package or inherited lint configuration differs")
        rows = [row for row in packages.values() if row["manifest_path"] == str(manifest)]
        require(len(rows) == 1, "owner metadata is missing or ambiguous")
        package = rows[0]
        require(package["id"] == "path+" + manifest.parent.as_uri() + "#" + name + "@" + package["version"]
                and package["name"] == name and package["source"] is None
                and package["version"] == workspace["workspace"]["package"]["version"]
                and package["features"] == declared["features"] == {"hia-native": []},
                "owner source, identity or feature inventory differs")
        targets = [row for row in package["targets"] if row["kind"] == ["lib"]]
        require(len(targets) == 1 and targets[0]["name"] == name.replace("-", "_")
                and targets[0]["crate_types"] == ["lib"] and targets[0]["src_path"] == str(source),
                "owner metadata target differs")
        selected[name] = {"package": package, "target": targets[0]}
    return selected, target_dir, workspace["workspace"]["lints"]["clippy"]


def owner_compilers(row, events, target_dir, repo, lint_levels):
    target, test = row["target"], row["profile"]["test"]
    selected = []
    for pair in events:
        event, arguments = pair["event"], pair["event"]["arguments"]
        if event["kind"] != "workspace" or options(arguments, "--crate-name") != [target["name"]]:
            continue
        if ("--test" in arguments) != test:
            continue
        require(event["delegates_helper"] is True, "owner compilation did not invoke the helper")
        sources = [arg for arg in arguments[1:] if not arg.startswith("-") and arg.endswith(".rs")]
        require(len(sources) == 1 and (repo / "codex-rs" / sources[0]).resolve() == Path(target["src_path"]),
                "compiler used a different owner source")
        require(options(arguments, "--edition") == [target["edition"]]
                and [arg for arg in options(arguments, "--cfg") if arg.startswith("feature=")] == ['feature="hia-native"'],
                "owner compiler edition or features differ")
        require(options(arguments, "--cap-lints") == ["warn"], "unexpected pinned Cargo fix lint cap")
        for lint, entry in lint_levels.items():
            level = entry["level"] if isinstance(entry, dict) else entry
            actual = [name for name in ("allow", "warn", "deny", "forbid")
                      for value in options(arguments, "--" + name) if value == "clippy::" + lint]
            require(actual == [level], "workspace lint was changed or omitted: " + lint)
        out_dirs = options(arguments, "--out-dir")
        suffixes = [value.split("=", 1)[1] for value in options(arguments, "-C")
                    if value.startswith("extra-filename=")]
        require(len(out_dirs) == len(suffixes) == 1 and suffixes[0].startswith("-"),
                "compiler artifact coordinates are missing or ambiguous")
        out_dir = Path(out_dirs[0]).resolve(strict=True)
        require(out_dir.is_relative_to(target_dir), "compiler output escaped the actual Cargo target")
        artifact = out_dir / ("lib" + target["name"] + suffixes[0] + ".rmeta")
        require(row["filenames"] == [str(artifact)] and options(arguments, "--emit") == ["dep-info,metadata"],
                "Cargo row is not the exact metadata artifact emitted by this compiler")
        # A successfully checked test target can emit zero bytes of metadata.
        require(artifact.is_file() and not artifact.is_symlink()
                and (test or artifact.stat().st_size > 0),
                "actual compiler artifact is missing or not regular")
        selected.append({"begin": pair["begin"], "end": pair["end"], "artifact": common.binding(artifact),
                         "workspace_clippy_lints": len(lint_levels), "cap_lints": "warn"})
    require(selected, "no actual successful Clippy workspace compilation for the requested owner unit")
    return selected


def verify_fix(args, repo, report):
    report.update(unchanged(repo, args.before))
    fixed = json.loads(args.fix_report.read_bytes())
    require(fixed["schema"] == "codex.hia.actual-policy-fix.v1" and fixed["passed"] is True
            and fixed["require_native"] is False and fixed["returncode"] == 0
            and fixed["all_subcompilers_succeeded"] is True and fixed["source_inputs_unchanged"] is True,
            "the separate actual Cargo fix did not pass")
    require(fixed["arguments"] == FIX_ARGUMENTS, "unexpected scoped fix package/feature selection")
    context = bound_json(fixed["context"])
    require(context["schema"] == "codex.hia.fix-compiler-context.v1" and context["repo"] == str(repo),
            "fix compiler context differs")
    rustc = Path(context["rustc"]).resolve(strict=True)
    require(rustc == Path(os.environ["RUSTC"]).resolve(strict=True), "fix rustc differs from this workflow")
    config, admitted = ci.validate_configuration(repo, rustc, fixed["configuration"]["config"]["path"])
    admitted["wrapper"] = ci.binding(repo / "hia/similar_policy.py")
    require(admitted == fixed["configuration"], "fix configuration was not the exact admitted wrapper")
    cargo, clippy = rustc.parent / "cargo", rustc.parent / "clippy-driver"
    require(ci.binding(cargo)["sha256"] == fix.CARGO_SHA and ci.binding(clippy)["sha256"] == ci.CLIPPY_SHA
            and context["clippy"] == str(clippy), "Cargo or Clippy compiler identity differs")
    expected_inputs = admitted["source_inputs"] + [ci.binding(rustc), ci.binding(cargo), ci.binding(clippy), admitted["config"]]
    require(context["inputs"] == expected_inputs, "compiler input inventory differs")
    for value in expected_inputs:
        common.verify(value)
    cargo_args, clippy_args = fix.split_arguments(FIX_ARGUMENTS)
    require(fixed["command"] == [str(cargo), "fix", *cargo_args]
            and fixed["clippy_args"] == context["clippy_args"] == clippy_args == "--no-deps__CLIPPY_HACKERY__",
            "actual Cargo/Clippy invocation differs")
    run = args.fix_report.with_suffix("").resolve(strict=True)
    require(fixed["context"]["path"] == str(run / "context.json")
            and fixed["stdout"]["path"] == str(run / "cargo.jsonl")
            and fixed["stderr"]["path"] == str(run / "cargo.stderr"), "fix output paths differ")
    events = paired_compilers(fixed, run, context, repo)
    common.verify(fixed["stdout"])
    common.verify(fixed["stderr"])
    require(not any(line.startswith(("error:", "error[")) for line in Path(fixed["stderr"]["path"]).read_text().splitlines()),
            "Cargo fix emitted a failure despite its return code")
    records = [json.loads(line) for line in Path(fixed["stdout"]["path"]).read_text().splitlines()]
    require(records and records[-1] == {"reason": "build-finished", "success": True}
            and sum(row.get("reason") == "build-finished" for row in records) == 1,
            "actual Cargo fix has no unique successful terminal record")
    require(not any(row.get("reason") == "compiler-message" and row["message"]["level"] == "error" for row in records),
            "Cargo JSON contains a compiler error")
    owners, target_dir, levels = actual_metadata(args.metadata, repo)
    results = {}
    for name, owner in owners.items():
        package, target = owner["package"], owner["target"]
        rows = [row for row in records if row.get("reason") == "compiler-artifact"
                and row["package_id"] == package["id"] and row["target"] == target]
        require(len(rows) == 2 and {row["profile"]["test"] for row in rows} == {False, True},
                "actual fix must include both the ordinary library and its test target: " + name)
        results[name] = []
        for row in rows:
            require(row["manifest_path"] == package["manifest_path"] and row["features"] == ["hia-native"]
                    and row["fresh"] is False and row["executable"] is None
                    and type(row["profile"]["test"]) is bool, "owner Cargo unit is stale or has different features")
            compilers = owner_compilers(row, events, target_dir, repo, levels)
            results[name].append({"cargo_artifact": row, "actual_clippy_compilers": compilers})
    for value in expected_inputs:
        common.verify(value)
    report.update(unchanged(repo, args.before))
    report.update(fix_report=common.binding(args.fix_report), metadata=common.binding(args.metadata), owners=results,
                  complete_bridge_pairs=len(events), actual_apply_patch_helper_calls=fixed["actual_native_helper_calls"],
                  legacy_counter_scope="codex_apply_patch only; it is not used to qualify string/template",
                  actual_requested_owner_compilers=sum(len(unit["actual_clippy_compilers"]) for units in results.values() for unit in units),
                  cargo_fix_cap_lints="warn", uncapped_strict_lint_claimed=False, new_native_execution_claimed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("snapshot", "verify", "unchanged"))
    parser.add_argument("--producer", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--fix-report", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repo = args.producer.resolve(strict=True)
    sys.path[:0] = [str(repo / "hia"), str(repo / "hia/tests")]
    global ci, fix, common, require
    import unified_policy_ci as ci
    import unified_policy_fix as fix
    from template_parse_oracle import common
    require = common.require
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    output = common.outside(args.report, [repo])
    require(not output.exists(), "refusing to replace a scoped fix report")
    report = {"schema": "codex.hia.scoped-owner-fix-" + ("source" if args.mode == "snapshot" else args.mode) + ".v1",
              "passed": False, "observer": common.binding(__file__)}
    try:
        require(Path(__file__).resolve() == repo / "hia/tests/verify_scoped_owner_fix.py", "observer is outside its producer")
        if args.mode == "snapshot":
            report["checkout"] = checkout(repo)
        else:
            require(args.before is not None, "source snapshot is required")
            if args.mode == "verify":
                require(args.fix_report is not None and args.metadata is not None, "actual fix and metadata are required")
                verify_fix(args, repo, report)
            else:
                report.update(unchanged(repo, args.before))
        report["passed"] = True
    except Exception as error:
        report["exception"] = str(error)
    common.save(output, report)
    print(json.dumps({"passed": report["passed"], "report": common.binding(output)}))
    return 0 if report["passed"] else 74


if __name__ == "__main__":
    raise SystemExit(main())
