#!/usr/bin/env python3
"""Whole original template crate versus the real Cargo parse18+render19 owner."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback

sys.dont_write_bytecode = True
from template_parse_oracle import artifacts, cargo, compiling, corpus, fingerprints, original, public, registry
from template_parse_oracle.common import Commands, Resources, binding, clean_identity, outside, producer_files, require, save, verify


NATIVE_MODULES = ('template_parse', 'template_render', 'template_index')


def run(args, report, work):
    from template_render_oracle import admission

    producer, original_repo = args.producer, args.original_repo
    require(sys.flags.optimize == 0, "qualification cannot disable assertions")
    require(Path(__file__).resolve() == producer / "hia/tests/test_native_template_parse_caller.py",
            "the complete public runner must belong to its clean producing checkout")
    resources = Resources(work)
    report["resources_before"] = resources.check("start complete public qualification")
    report["producer_identity"] = clean_identity(producer)
    report["original_identity"] = clean_identity(original_repo)
    before = producer_files(producer)
    original_before = producer_files(original_repo)
    for name, records in (("producing-source-inputs", before), ("original-checkout-inputs", original_before)):
        path = work / (name + ".json")
        save(path, records)
        report[name] = binding(path)
    report["whole_producing_source_file_count"] = len(before)
    report["whole_original_checkout_file_count"] = len(original_before)
    build, _, native_inputs = admission.admit(producer, args.library_dir)
    report["native_inputs"] = native_inputs
    report["formal_module_count"] = len(build["modules"])
    commands = Commands(work / "commands", resources)
    report["command_records"] = str(commands.output / "commands.json")
    sys.path.insert(0, str(producer / "hia/tests"))
    from file_update_oracle.cargo import compiler, policy_environment

    rustc, actual_cargo, env, toolchain = compiler(args.rustc, commands, producer)
    require(not env.get("RUSTFLAGS") and not env.get("CARGO_ENCODED_RUSTFLAGS"),
            "this gate does not admit external rustc flag overrides")
    env["CODEX_HIA_NATIVE_LIB_DIR"] = str(args.library_dir)
    env["CARGO_BUILD_JOBS"] = "1"
    target = Path(env.get("CARGO_TARGET_DIR", work.with_name(work.name + "-target"))).resolve()
    require(not any(target == root or target.is_relative_to(root)
                    for root in (producer, original_repo, args.library_dir, work)),
            "actual target artifacts must be separate from all source/evidence/build directories")
    env["CARGO_TARGET_DIR"] = str(target)
    report["toolchain"] = toolchain
    report["toolchain_files"] = [binding(rustc), binding(actual_cargo)]
    report["actual_target_dir"] = str(target)
    report["target_growth_in_evidence_budget"] = False
    original_dir = work / "complete-original-template"
    report["original_source"] = original.snapshot(original_repo, original_dir)
    report["whole_library_routing_inverse"] = original.producing_source(producer, original_dir)
    metadata, packages, owner, dependencies = cargo.metadata(actual_cargo, producer, env, commands)
    require(Path(metadata["target_directory"]).resolve() == target, "metadata selected another target directory")
    metadata_sources = {key: {"name": value["name"], "version": value["version"],
        "source": value["source"], "manifest": binding(value["manifest_path"])} for key, value in packages.items()}
    save(work / "metadata-package-sources.json", metadata_sources)
    report["metadata_package_sources"] = binding(work / "metadata-package-sources.json")
    graphs, consumed = {}, {}
    for name, native in (("default", False), ("native", True)):
        path = cargo.capture(actual_cargo, producer, env, native, commands)
        graphs[name] = cargo.admit(path, packages, owner, dependencies, target,
                                  work / (name + "-graph"), native=native)
        modules = NATIVE_MODULES if native else ()
        graphs[name]["native_linkage"] = artifacts.native_linkage(
            graphs[name], target, args.library_dir, build, native_inputs, modules)
        consumed[name] = fingerprints.owner_dependencies(graphs[name], packages)
        save(work / (name + "-graph.json"), graphs[name])
        save(work / (name + "-consumed-units.json"), consumed[name])
    report["cargo_graphs"] = {name: binding(work / (name + "-graph.json")) for name in graphs}
    report["actual_consumed_test_units"] = {name: binding(work / (name + "-consumed-units.json")) for name in consumed}
    for name in cargo.REQUIRED:
        left, right = (graphs[mode]["direct"][name]["unit"] for mode in ("default", "native"))
        keys = ("package_id", "target", "features", "profile", "files", "fingerprint")
        require({key: left[key] for key in keys} == {key: right[key] for key in keys},
                "actual default/native assertion dependency identities differ: " + name)
    report["actual_cargo_default_native_library_and_test_graphs_admitted"] = True
    registry_record = registry.sources(producer, original_repo, packages, graphs)
    save(work / "complete-registry-source-bindings.json", registry_record)
    report["registry_sources"] = binding(work / "complete-registry-source-bindings.json")
    compiled = compiling.whole_original(rustc, original_dir, graphs["default"],
                                       work / "original-build", commands, env)
    report["whole_original_execution"] = compiled
    observers = compiling.observers(rustc, compiled, graphs, work / "original-build", commands, env)
    report["compiled_observers"] = observers
    fixtures = corpus.generate(work / "fixtures", resources)
    report["corpus"] = binding(work / "fixtures/report.json")
    observed = public.observe(observers, fixtures, work / "public", env, resources)
    report["public_results"] = binding(work / "public/report.json")
    report["case_pairs"] = observed["case_pairs"]
    report["constructor_values_compared"] = observed["constructor_values_compared"]
    report["actual_native_calls"] = observed["actual_native_calls"]
    report["actual_native_operations"] = observed["actual_native_operations"]
    report["public_payloads_sha256"] = observed["public_payloads_sha256"]
    for name, graph in graphs.items():
        cargo.verify_graph(graph)
        modules = NATIVE_MODULES if name == "native" else ()
        require(artifacts.native_linkage(graph, target, args.library_dir, build,
                                        native_inputs, modules) == graph["native_linkage"],
                "the actual Cargo OUT_DIR or staged native archives changed")
    report["last_actual_cargo_publication_aliases"] = artifacts.verify_final_aliases(graphs)
    for record in consumed.values():
        fingerprints.verify_fingerprints(record)
    registry.verify_sources(registry_record)
    original.verify_tree(original_dir, original.catalog()["original_files"])
    require(original.producing_source(producer, original_dir) == report["whole_library_routing_inverse"],
            "the complete routing inverse changed during qualification")
    for record in (compiled["library"], compiled["test_binary"], compiled["test_list"], compiled["test_result"],
                   fixtures["full_inputs"], fixtures["index"], *observers["sources"].values(), *observed["artifacts"]):
        verify(record)
    for observer in observers["observers"].values():
        verify(observer["binary"])
        verify(observer["owner_library"])
    for record in metadata_sources.values():
        verify(record["manifest"])
    for record in report["toolchain_files"]:
        verify(record)
    for path, record in native_inputs.items():
        require(binding(path) == {"path": path, **record}, "a formally admitted native input changed")
    require(policy_environment(producer, rustc, env) == toolchain["policy_wrapper"],
            "the admitted compiler wrapper/configuration changed")
    require(producer_files(producer) == before and producer_files(original_repo) == original_before
            and clean_identity(producer) == report["producer_identity"]
            and clean_identity(original_repo) == report["original_identity"],
            "a complete producing or original checkout changed")
    report["actual_command_log"] = commands.verify()
    report["resources_after"] = resources.check("qualification complete")
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
    require(report_path != work and not report_path.is_relative_to(work), "report must be separate from its work directory")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.template-complete-original-cargo-public.v2", "passed": False,
        "controller": binding(Path(__file__)), "started_unix": time.time(), "work_dir": str(work),
        "scope": "Complete unchanged a201 four-file template crate and all fourteen original tests; actual default/native Cargo library and lib-test graphs with the full 54-file assertion dependency sources; literal complete native public observations. Both parsing and rendering use admitted HIA components; the trace carries twenty-word rows tagged with the real symbol.",
        "tests_skipped": 0, "current_cargo_owner_public_qualified": False,
        "current_native_full_suite_claimed": False, "current_strict_clippy_claimed": False,
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
