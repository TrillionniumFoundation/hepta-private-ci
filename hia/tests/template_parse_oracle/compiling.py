"""Compile the whole original crate; the native observer uses the actual Cargo owner."""
from pathlib import Path
import re

from .common import binding, require
from .original import catalog

PROFILE = ["--edition=2024", "--target=x86_64-unknown-linux-gnu", "-Copt-level=0",
           "-Cdebuginfo=0", "-Cdebug-assertions=on", "-Coverflow-checks=on"]
DECLARATIONS = ["--check-cfg=cfg(test)", '--check-cfg=cfg(feature,values("hia-native"))']


def flags(graph):
    result = ["-L", "dependency=" + graph["stage"]]
    for path in graph["native_paths"]:
        result += ["-L", path]
    return result


def whole_original(rustc, original, graph, output, commands, env):
    output.mkdir()
    root = original / "src/lib.rs"
    child = env.copy()
    child["CARGO_MANIFEST_DIR"] = str(original)
    library = output / "libtemplate_original.rlib"
    commands.run("compile-complete-original-library", [rustc, root,
        "--crate-name=codex_utils_template", "--crate-type=rlib", "-Cmetadata=template_original_whole",
        *PROFILE, *DECLARATIONS, *flags(graph), "-o", library], cwd=output, env=child)
    tests = output / "original-all-tests"
    commands.run("compile-complete-original-tests", [rustc, root,
        "--crate-name=codex_utils_template", "--test", "-Cmetadata=template_original_tests",
        *PROFILE, *DECLARATIONS, *flags(graph), "--extern",
        "pretty_assertions=" + graph["direct"]["pretty_assertions"]["path"], "-o", tests],
        cwd=output, env=child)
    listing = commands.run("list-complete-original-tests", [tests, "--list", "--format=terse"],
                           cwd=output, env=child)
    names = [line.removesuffix(": test") for line in listing.read_text().splitlines() if line.endswith(": test")]
    require(names == catalog()["original_tests"], "the exact complete fourteen-test inventory differs")
    result = commands.run("run-complete-original-tests", [tests, "--test-threads=1", "--nocapture"],
                          cwd=output, env=child)
    summaries = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", result.read_text())
    require(summaries == [("14", "0", "0", "0", "0")], "complete original tests did not pass without omissions")
    return {"library": binding(library), "test_binary": binding(tests),
            "test_list": binding(listing), "test_result": binding(result), "test_names": names,
            "tests_passed": 14, "tests_skipped": 0, "whole_original_library_compiled": True,
            "profile_flags": PROFILE, "check_cfg_declarations": DECLARATIONS}


def observers(rustc, original_build, graphs, output, commands, env):
    root = Path(__file__).parent
    sources = {}
    for name, record in catalog()["frozen_observers"].items():
        actual = binding(root / name)
        require({key: actual[key] for key in ("bytes", "sha256")} == record,
                "a frozen public observer/transport source changed")
        sources[name] = actual
    records = {}
    for name in ("original", "native"):
        graph = graphs["default" if name == "original" else "native"]
        library = (original_build["library"]["path"] if name == "original"
                   else graph["direct"]["codex_utils_template"]["path"])
        binary = output / (name + "-observer")
        selected = (["--cfg=native_observer", "-Clink-arg=-Wl,--wrap=codex_hia_template_parse"]
                    if name == "native" else [])
        commands.run("compile-" + name + "-public-observer", [rustc, root / "observer.rs",
            "--crate-name=template_public_observer", "--check-cfg=cfg(native_observer)",
            *PROFILE, *DECLARATIONS, *flags(graph), "--extern", "subject=" + library,
            "-Dwarnings", *selected, "-o", binary], cwd=output, env=env)
        records[name] = {"binary": binding(binary), "owner_library": binding(library)}
    return {"sources": sources, "observers": records,
            "native_owner_is_the_actual_cargo_artifact": True,
            "counter_forwards_all_six_arguments_unchanged": True,
            "same_observer_source_for_both_complete_libraries": True}
