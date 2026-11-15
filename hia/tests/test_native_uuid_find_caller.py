#!/usr/bin/env python3
"""Complete original UUID owner versus the current real Cargo native library."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
from uuid_find_oracle import admission, artifacts, cargo, compiling, corpus, fingerprints, original, public, registry
from uuid_find_oracle.common import Commands, binding, clean_identity, outside, producer_files, require, save, verify


def run(args, report, work):
    producer, original_repo = args.producer, args.original_repo
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    require(Path(__file__).resolve() == producer / "hia/tests/test_native_uuid_find_caller.py",
            "the complete public runner must be part of its clean producing checkout")
    report["producer_identity"] = clean_identity(producer)
    report["original_identity"] = clean_identity(original_repo)
    before = producer_files(producer)
    source_map = work / "producing-source-inputs.json"
    save(source_map, before)
    report["whole_producing_source_inputs"] = binding(source_map)
    report["whole_producing_source_file_count"] = len(before)
    build, _, native_inputs = admission.admit(producer, args.library_dir)
    report["native_inputs"] = native_inputs
    report["formal_module_count"] = len(build["modules"])
    commands = Commands(work / "commands")
    report["command_records"] = str(commands.output / "commands.json")
    sys.path.insert(0, str(producer / "hia/tests"))
    from file_update_oracle.cargo import compiler
    rustc, actual_cargo, env, toolchain = compiler(args.rustc, commands, producer)
    require(not env.get("RUSTFLAGS") and not env.get("CARGO_ENCODED_RUSTFLAGS"),
            "this qualification does not admit external rustc flag overrides")
    env["CODEX_HIA_NATIVE_LIB_DIR"] = str(args.library_dir)
    target = Path(env.get("CARGO_TARGET_DIR", work / "target")).resolve()
    require(not target.is_relative_to(producer) and not target.is_relative_to(original_repo),
            "actual Cargo artifacts must be outside source checkouts")
    env["CARGO_TARGET_DIR"] = str(target)
    report["toolchain"] = toolchain
    report["toolchain_files"] = [binding(rustc), binding(actual_cargo)]
    report["actual_target_dir"] = str(target)
    original_dir = work / "complete-original-utils-string"
    report["original_source"] = original.snapshot(original_repo, original_dir)
    report["whole_library_routing_inverse"] = original.producing_source(producer, original_dir)
    metadata, packages, owner, dependencies = cargo.metadata(actual_cargo, producer, env, commands)
    require(Path(metadata["target_directory"]).resolve() == target, "metadata selected another actual target directory")
    report["metadata_package_sources"] = {key: {"name": value["name"], "version": value["version"],
        "source": value["source"], "manifest": binding(value["manifest_path"])} for key, value in packages.items()}
    graphs, consumed = {}, {}
    for name, native in (("default", False), ("native", True)):
        path = cargo.capture(actual_cargo, producer, env, native, commands)
        graphs[name] = cargo.admit(path, packages, owner, dependencies, target, work / (name + "-graph"), native=native)
        consumed[name] = fingerprints.owner_dependencies(graphs[name], packages)
        save(work / (name + "-graph.json"), graphs[name])
        save(work / (name + "-consumed-units.json"), consumed[name])
    report["cargo_graphs"] = {name: binding(work / (name + "-graph.json")) for name in graphs}
    report["actual_consumed_unit_records"] = {name: binding(work / (name + "-consumed-units.json")) for name in consumed}
    for name in cargo.REQUIRED:
        left, right = (graphs[mode]["direct"][name]["unit"] for mode in ("default", "native"))
        require({key: left[key] for key in ("package_id", "target", "features", "profile", "files")}
                == {key: right[key] for key in ("package_id", "target", "features", "profile", "files")},
                "the default/native direct dependency identity differs: " + name)
    report["actual_cargo_default_and_native_graphs_admitted"] = True
    registry_record = registry.sources(producer, original_repo, packages, graphs)
    registry_path = work / "complete-registry-source-bindings.json"
    save(registry_path, registry_record)
    report["registry_sources"] = binding(registry_path)
    regex_record = original.registry_source(producer, packages[dependencies["regex_lite"]], work / "complete-regex-lite")
    report["complete_regex_source"] = regex_record
    compiled = compiling.whole_original(rustc, original_dir, graphs["default"], work / "original-build", commands, env)
    report["whole_original_execution"] = compiled
    observations = compiling.observers(rustc, compiled, graphs, work / "original-build", commands, env)
    report["compiled_observers"] = observations
    fixtures = corpus.generate(work / "fixtures")
    report["corpus"] = binding(work / "fixtures/report.json")
    fixture = Path(fixtures["fixture"]["path"])
    report["fixture"] = binding(fixture)
    report["semantic_case_categories"] = fixtures["categories"]
    observed = public.observe(observations, fixture, fixtures, work / "public", commands, env)
    report.update(observed)
    public.compare_spans(producer, args.library_dir, fixture, observed["original_regex_spans"],
                         fixtures["cases"], work / "public", report)
    require(report["complete_regex_matches"] == report["observations"]["original"]["matches"],
            "whole original regex offsets and public results disagree")
    for graph in graphs.values():
        cargo.verify_graph(graph)
    report["last_actual_cargo_publication_aliases"] = artifacts.verify_final_aliases(graphs)
    for record in consumed.values():
        fingerprints.verify_fingerprints(record)
    registry.verify_sources(registry_record)
    original.verify_tree(original_dir, original.catalog()["original_files"])
    original.verify_tree(Path(regex_record["root"]), original.catalog()["regex_files"])
    for record in (regex_record["archive"], *regex_record["actual_source_bindings"]):
        verify(record)
    for record in (compiled["library"], compiled["test_binary"], observations["source"], report["fixture"],
                   *report["public_transcripts"].values(), report["original_regex_spans"]):
        verify(record)
    for observer in observations["observers"].values():
        verify(observer["binary"])
        verify(observer["owner_library"])
    for package in report["metadata_package_sources"].values():
        verify(package["manifest"])
    for record in report["toolchain_files"]:
        verify(record)
    for path, record in native_inputs.items():
        require(binding(path) == {"path": path, **record}, "a formally admitted native input changed")
    require(producer_files(producer) == before and clean_identity(producer) == report["producer_identity"]
            and clean_identity(original_repo) == report["original_identity"], "a whole producing/original source changed")
    report["actual_command_log"] = commands.verify()
    report["source_and_dependency_artifacts_unchanged"] = True
    report["current_cargo_owner_public_qualified"] = True
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--producer", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--original-repo", type=Path, required=True)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--rustc", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path)
    args = parser.parse_args()
    for name in ("producer", "original_repo", "library_dir", "rustc"):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    roots = (args.producer, args.original_repo, args.library_dir)
    report_path = outside(args.report, roots)
    work = outside(args.work_dir or report_path.with_name(report_path.stem + "-files"), roots)
    require(not report_path.exists(), "report exists; historical execution records cannot be overwritten")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.uuid-complete-original-cargo-public.v1", "passed": False,
        "controller": binding(Path(__file__)), "started_unix": time.time(),
        "scope": "Complete unchanged a201 15-file utils/string crate and its entire original test suite; actual current Cargo native public API; exact complete locked regex-lite find_iter offsets. No source fragments, dependency substitutes or value normalization.",
        "work_dir": str(work), "tests_skipped": 0, "current_cargo_owner_public_qualified": False,
        "current_native_full_suite_claimed": False, "concurrent_execution": False,
        "performance_qualified": False, "whole_codex_rewritten": False, "legacy_retirement": False}
    try:
        run(args, report, work)
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        report["finished_unix"] = time.time()
        save(report_path, report)
        print(json.dumps({"passed": report["passed"], "report": binding(report_path)}), flush=True)


if __name__ == "__main__":
    main()
