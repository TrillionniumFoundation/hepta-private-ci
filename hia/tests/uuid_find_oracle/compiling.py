"""Compile the complete immutable original; link the real Cargo native owner."""
import json
from pathlib import Path
import re

from .common import binding, require

OBSERVER_SHA = "0fe695b968f4cee95b96e026aa3f203fc5cc15b17be87073f4fd678d715e473d"
ORIGINAL_TEST_COUNT = 26


def flags(graph):
    result = ["-L", "dependency=" + graph["stage"]]
    for path in graph["native_paths"]:
        result += ["-L", path]
    return result


def whole_original(rustc, original, graph, output, commands, env):
    output.mkdir()
    root = original / "src/lib.rs"
    profile = ["--edition=2024", "--target=x86_64-unknown-linux-gnu", "-Copt-level=0",
               "-Cdebuginfo=0", "-Cdebug-assertions=on", "-Coverflow-checks=on"]
    dependencies = flags(graph)
    for name in ("regex_lite", "serde", "serde_json", "pretty_assertions"):
        dependencies += ["--extern", name + "=" + graph["direct"][name]["path"]]
    child = env.copy()
    child["CARGO_MANIFEST_DIR"] = str(original)
    library = output / "libuuid_original.rlib"
    commands.run("compile-complete-original-library", [rustc, root,
        "--crate-name=codex_utils_string", "--crate-type=rlib", "-Cmetadata=uuid_original_whole",
        *profile, *dependencies, "-o", library], cwd=output, env=child)
    tests = output / "original-all-tests"
    commands.run("compile-complete-original-tests", [rustc, root,
        "--crate-name=codex_utils_string", "--test", "-Cmetadata=uuid_original_tests",
        *profile, *dependencies, "-o", tests], cwd=output, env=child)
    listing = commands.run("list-complete-original-tests", [tests, "--list", "--format=terse"],
                           cwd=output, env=child)
    names = [line.removesuffix(": test") for line in listing.read_text().splitlines() if line.endswith(": test")]
    require(len(names) == len(set(names)) == ORIGINAL_TEST_COUNT,
            "the complete original test inventory differs")
    result = commands.run("run-complete-original-tests", [tests, "--test-threads=1", "--nocapture"],
                          cwd=output, env=child)
    summaries = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out", result.read_text())
    require(summaries == [(str(ORIGINAL_TEST_COUNT), "0", "0", "0", "0")],
            "the complete original test execution did not pass without omissions")
    return {"library": binding(library), "test_binary": binding(tests),
            "test_list": binding(listing), "test_result": binding(result),
            "test_names": names, "tests_passed": ORIGINAL_TEST_COUNT, "tests_skipped": 0,
            "whole_original_library_compiled": True, "profile_flags": profile}


def observers(rustc, original_build, graphs, output, commands, env):
    source = Path(__file__).with_name("observer.rs")
    require(binding(source)["sha256"] == OBSERVER_SHA, "the frozen public observer changed")
    records = {}
    for name in ("original", "native"):
        graph = graphs["default" if name == "original" else "native"]
        library = (original_build["library"]["path"] if name == "original"
                   else graph["direct"]["codex_utils_string"]["path"])
        binary = output / (name + "-observer")
        selected = ["--cfg=native_observer", "-Clink-arg=-Wl,--wrap=codex_hia_uuid_find"] if name == "native" else []
        commands.run("compile-" + name + "-public-observer", [rustc, source,
            "--crate-name=uuid_observer", "--check-cfg=cfg(native_observer)",
            *original_build["profile_flags"], *flags(graph),
            "--extern", "uuid_owner=" + library,
            "--extern", "regex_lite=" + graph["direct"]["regex_lite"]["path"],
            *selected, "-o", binary], cwd=output, env=env)
        records[name] = {"binary": binding(binary), "owner_library": binding(library)}
    return {"source": binding(source), "observers": records,
            "native_owner_is_the_actual_cargo_artifact": True,
            "counter_forwards_all_six_arguments_unchanged": True}
