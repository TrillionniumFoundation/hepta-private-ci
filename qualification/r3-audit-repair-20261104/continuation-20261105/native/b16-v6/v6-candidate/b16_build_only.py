"""A current-host build cache is never evidence that A tests were executed."""

import collections
import json
import os
from pathlib import Path
import platform

from b16_guard import need, same_record

MODE = "BUILD_ONLY_CURRENT_HOST"


def validate_mode_binding(binding):
    pin = binding.get("current_host_build_only_baseline", {})
    need(pin.get("path") and pin.get("sha256") and isinstance(pin.get("bytes"), int),
         "actual current-host build-only baseline is missing; this template cannot run")
    need(binding.get("build_only_host") and binding.get("build_only_cache_owner"),
         "bind the actual current host and cache owner")
    need(pin["sha256"] != binding.get("last_tested_A_artifacts", {}).get("sha256"),
         "build-only evidence cannot replace the historical tested-A receipt")


def pinned_json(pin):
    need(same_record(pin["path"], pin), "build-only original receipt bytes changed: " + pin["path"])
    return json.loads(Path(pin["path"]).read_bytes())


def observed_host():
    return {"uname": list(platform.uname()), "uid": os.getuid(), "euid": os.geteuid()}


def byte_id(row):
    return {key: row[key] for key in ("bytes", "sha256")}


def load_build_only(binding):
    """Validate pinned original build receipts; no compilation or test execution."""
    from b16_family import metadata_projection, digest
    from b16_native import HELPERS, check_helper_roster

    validate_mode_binding(binding)
    receipt = pinned_json(binding["current_host_build_only_baseline"])
    need(receipt.get("schema") == "hepta-b16-current-host-build-only-baseline-v1" and
         receipt.get("role") == MODE and receipt.get("tests_executed") is False and
         receipt.get("test_qualification") is False,
         "current-host cache must remain BUILD_ONLY, without A test qualification")
    historical = pinned_json(binding["last_tested_A_artifacts"])
    need(historical.get("role") != MODE and historical["source"] == binding["last_tested_A_tree"] and
         historical["cargo_profile"] == "dev-small" and historical["nextest_profile"] == "local",
         "historical tested-A identity cannot be relabeled from a build-only receipt")
    need(receipt["host"] == binding["build_only_host"] and
         all(receipt["host"].get(key) == value for key, value in observed_host().items()),
         "build-only receipt belongs to another host or user")
    need(receipt["cache_owner"] == binding["build_only_cache_owner"], "build-only cache owner differs")
    need(receipt["source_tree"] == binding["final_A_tree"] and
         receipt["source_commit"] == binding["ordinary_head"], "build-only source identity differs")
    need(receipt["source_directory"] == binding["source_directory"] and
         receipt["target_directory"] == binding["target_directory"], "build-only source/target paths differ")
    need(byte_id(receipt["ordinary_index"]) == byte_id(binding["ordinary_index"]), "build-only ordinary index differs")
    tools = lambda rows: sorted(({key: row[key] for key in ("name", "path", "bytes", "sha256")} for row in rows), key=lambda row: row["name"])
    recipes = lambda rows: sorted(({key: row[key] for key in ("path", "bytes", "sha256")} for row in rows), key=lambda row: row["path"])
    need(receipt["cargo_profile"] == "dev-small" and tools(receipt["tools"]) == tools(binding["tools"]) and
         recipes(receipt["recipe_sources"]) == recipes(binding["recipe_sources"]), "build-only recipe/tools/profile differ")
    need(set(receipt["locks"]) == {"codex-rs/Cargo.lock", "MODULE.bazel.lock"}, "build-only locks missing")
    if binding["authorized_epoch"] in ("foundation", "driver"):
        need({key: byte_id(row) for key, row in receipt["locks"].items()} ==
             {key: byte_id(row) for key, row in binding["locks"].items()}, "pre-adoption build-only locks differ")
    need(receipt["environment"] == binding["environment"], "build-only effective environment differs")
    need(len(receipt["source_guards"]) == len({pin["path"] for pin in receipt["source_guards"]}) == 6,
         "three original build commands need both distinct source fences")
    for pin in receipt["source_guards"]:
        guard = pinned_json(pin)
        files = {row["path"]: row for row in guard["guarded_files"]}
        need(guard["working_tree"] == guard["head_tree"] == receipt["source_tree"] and
             guard["head"] == receipt["source_commit"] and
             byte_id(guard["ordinary_index"]) == byte_id(receipt["ordinary_index"]) and
             all(byte_id(files[str(Path(receipt["source_directory"]) / key)]) == byte_id(row)
                 for key, row in receipt["locks"].items()) and guard["untracked"] == [],
             "build-only source/index/lock fence differs")
    argv = ["cargo", "build", "--locked", "--profile", "dev-small", "--message-format=json-render-diagnostics"]
    for package, binaries in HELPERS.items():
        argv += ["-p", package]
        for binary in binaries:
            argv += ["--bin", binary]
    expected_commands = [argv, ["cargo", "metadata", "--locked", "--format-version=1"],
                         ["cargo", "nextest", "list", "--locked", "--cargo-profile", "dev-small", "--message-format=json"]]
    need(len(receipt["commands"]) == 3, "build-only requires the three complete original commands")
    for command, expected in zip(receipt["commands"], expected_commands, strict=True):
        need(command["argv"] == expected and command["exit_code"] == 0 and
             command["cwd"] == str(Path(receipt["source_directory"]) / "codex-rs") and
             command["source_before"] == command["source_after"] == receipt["source_tree"],
             "build-only command, zero return code or source binding differs")
        for stream in ("stdout", "stderr"):
            need(same_record(command[stream]["path"], command[stream]), "build-only complete command output changed")
    need(all(receipt[key][field] == receipt["commands"][index]["stdout"][field]
             for key, index in (("metadata", 1), ("catalog", 2)) for field in ("path", "bytes", "sha256")),
         "build-only raw command output association differs")
    metadata, catalog = pinned_json(receipt["metadata"]), pinned_json(receipt["catalog"])
    need(metadata["workspace_root"] == str(Path(receipt["source_directory"]) / "codex-rs") and
         metadata["target_directory"] == receipt["target_directory"] and
         catalog["rust-build-meta"]["target-directory"] == receipt["target_directory"], "build-only metadata paths differ")
    need(len(metadata["workspace_members"]) == 193 and len(metadata["resolve"]["nodes"]) == 1501 and
         sorted(metadata["workspace_default_members"]) == sorted(metadata["workspace_members"]) and
         {row["id"] for row in metadata["packages"]} == {row["id"] for row in metadata["resolve"]["nodes"]},
         "build-only metadata is not the full original A graph")
    if binding["authorized_epoch"] == "foundation":
        need(digest(metadata_projection(metadata)) == digest(metadata_projection(pinned_json(binding["baseline_metadata"]))),
             "foundation baseline metadata differs from the actual current-host build")
    normal = receipt["normal_helpers_before_catalog"]
    messages = [json.loads(line) for line in Path(receipt["commands"][0]["stdout"]["path"]).read_text().splitlines()]
    need([m for m in messages if m.get("reason") == "build-finished"] == [{"reason": "build-finished", "success": True}],
         "normal helper build did not finish exactly once")
    names = {name for binaries in HELPERS.values() for name in binaries}
    built = [m for m in messages if m.get("reason") == "compiler-artifact" and
             m.get("executable") and m["target"]["name"] in names]
    need(len(normal) == len(built) == 6 and {row["target"] for row in normal} == names, "build-only normal helper roster differs")
    for row in normal:
        match = [m for m in built if m["target"]["name"] == row["target"]]
        need(isinstance(row["bytes"], int) and row["bytes"] > 0 and len(row["sha256"]) == 64 and
             len(match) == 1 and match[0]["executable"] == row["path"] and
             all(match[0][key] == row[key] for key in ("package_id", "features", "fresh")),
             "normal helper identity/features differ from compiler output")
    programs, helpers = receipt["programs_after_catalog"], receipt["helpers_after_catalog"]
    need(len(programs) == len(catalog["rust-suites"]) == 363 and len(helpers) == 33,
         "complete current-host 363 programs and 33 helpers are required")
    need(collections.Counter((row["binary_id"], row["path"]) for row in programs) ==
         collections.Counter((key, row["binary-path"]) for key, row in catalog["rust-suites"].items()),
         "program receipt does not cover the complete unfiltered catalog")
    packages = {package["id"]: package["name"] for package in metadata["packages"]}
    helper_packages = {binary: package for package, binaries in HELPERS.items() for binary in binaries}
    need(all(packages.get(row["package-id"]) == row["package-name"] for row in catalog["rust-suites"].values()) and
         all(packages.get(row["package_id"]) == helper_packages[row["target"]] for row in normal),
         "catalog/normal helper package identities differ from full metadata")
    need(all(item["filter-match"]["status"] == "matches" for suite in catalog["rust-suites"].values()
             for item in suite["testcases"].values()), "build-only catalog was filtered")
    check_helper_roster(helpers, binding["A_helper_basename_roster"])
    need(collections.Counter(Path(row["path"]).name for row in historical["helpers_after_catalog_before_just"]) ==
         collections.Counter(binding["A_helper_basename_roster"]), "historical helper name contract changed")
    paths = {row["path"] for row in normal}

    def visit(value):
        if isinstance(value, dict):
            if value.get("kind") == "bin-exe" and isinstance(value.get("path"), str):
                path = Path(value["path"])
                paths.add(str(path if path.is_absolute() else Path(receipt["target_directory"]) / path))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(catalog["rust-build-meta"]["non-test-binaries"])
    need(len(paths) == 33 and collections.Counter(row["path"] for row in helpers) == collections.Counter(paths),
         "helper identities do not cover actual catalog plus normal helpers")
    by_path = {row["path"]: row for row in helpers}
    after = receipt["normal_helpers_after_catalog"]
    need(len(after) == 6 and {row["target"] for row in after} == names, "post-catalog normal helper identities missing")
    for row in after:
        need(any(before["target"] == row["target"] and before["path"] == row["path"] for before in normal) and
             all(row[key] == by_path[row["path"]][key] for key in ("bytes", "sha256")), "post-catalog helper hash association differs")
    artifact = {"source": receipt["source_tree"], "packages": historical["packages"],
                "helpers_after_catalog_before_just": helpers, "test_binaries_after_catalog_before_just": programs}
    return {"receipt": receipt, "metadata": metadata, "catalog": catalog, "normal": normal, "artifact": artifact}


def verify_current_outputs(context):
    receipt = context["receipt"]
    target = Path(receipt["target_directory"]).resolve()
    for row in [*receipt["programs_after_catalog"], *receipt["helpers_after_catalog"]]:
        path = Path(row["path"])
        need(path.is_file() and path.resolve().is_relative_to(target) and path.stat().st_mode & 0o111 and
             isinstance(row["bytes"], int) and row["bytes"] > 0 and same_record(path, row),
             "current-host build-only artifact is missing, changed or outside its target: " + str(path))


def current_family(binding, historical_family):
    from b16_family import catalog_layout, digest, helper_layout, metadata_projection, normal_helper_layout

    context = load_build_only(binding)
    layout = catalog_layout(context["catalog"])
    roles = lambda rows: [{key: row[key] for key in ("binary_id", "binary_name", "package_name", "kind", "build_platform")} for row in rows]
    need(roles(layout) == roles(historical_family["complete_catalog_layout"]), "current-host catalog program roles differ from A")
    return {"schema": "hepta-b16-build-only-output-family-v1", "role": MODE,
            "source_tree": context["receipt"]["source_tree"], "tests_executed": False, "test_qualification": False,
            "current_host_build_only_baseline": binding["current_host_build_only_baseline"],
            "historical_roster_reference": {"source_tree": binding["last_tested_A_tree"], "receipt": binding["last_tested_A_artifacts"]},
            **{key: historical_family[key] for key in ("payload_sha256", "foundation_delta_order", "foundation_source_paths")},
            "complete_metadata_projection_sha256": digest(metadata_projection(context["metadata"])),
            "complete_rust_build_meta_sha256": digest(context["catalog"]["rust-build-meta"]),
            "complete_catalog_layout": layout,
            "normal_six_helper_layout": normal_helper_layout(context["normal"], binding["target_directory"]),
            "complete_helper_relative_paths": helper_layout(context["receipt"]["helpers_after_catalog"], binding["target_directory"])}
