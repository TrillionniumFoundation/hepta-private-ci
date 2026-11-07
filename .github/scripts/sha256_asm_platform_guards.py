"""Verify actual configured Rustc arguments, response files and dependency inputs."""

import json
import re

from sha256_asm_lock_guards import require, unique


TRIPLES = (
    "aarch64-unknown-linux-gnu",
    "x86_64-unknown-linux-gnu",
    "aarch64-pc-windows-msvc",
    "x86_64-pc-windows-gnullvm",
)
OWNER_PREFIX = r"(?:@@rules_rs\+\+crate\+|@)crates__"
SHA2_OWNER = re.compile(OWNER_PREFIX + r"sha2-0\.10\.9//:sha2")
ASM_OWNER = re.compile(OWNER_PREFIX + r"sha2-asm-0\.6\.4//:sha2-asm")


def aquery_command(triple):
    require(triple in TRIPLES, "UNKNOWN_PLATFORM")
    return [
        "bazel",
        "aquery",
        "--announce_rc",
        "--output=jsonproto",
        "--include_param_files",
        "--include_commandline",
        "--include_artifacts",
        "--lockfile_mode=error",
        "--host_platform=//:local_linux",
        "--platforms=@rules_rs//rs/platforms:" + triple,
        'mnemonic("^(Rustc|RustcMetadata)$", deps(@crates//:sha2-0.10.9))',
    ]


def rustc_arguments(action):
    params = unique(action.get("paramFiles", []), lambda p: p["execPath"])
    used = set()

    def take(path):
        require(path in params and path not in used, "MISSING_OR_REUSED_PARAM_FILE")
        used.add(path)
        values = params[path]["arguments"]
        require(
            isinstance(values, list) and all(isinstance(v, str) for v in values),
            "INVALID_PARAM_ARGUMENTS",
        )
        return values

    argv = list(action["arguments"])
    require(
        len(argv) >= 3 and all(isinstance(v, str) for v in argv),
        "INVALID_ACTION_ARGUMENTS",
    )
    if argv[1].startswith("--wrapper-args="):
        wrapper = take(argv[1].split("=", 1)[1])
        require("--" not in wrapper, "WRAPPER_CHANGED_CHILD_BOUNDARY")
        argv[1:2] = wrapper
    require(argv.count("--") == 1, "MISSING_OR_AMBIGUOUS_CHILD_BOUNDARY")
    child = argv[argv.index("--") + 1 :]
    require(
        child and child[0].replace("\\", "/").split("/")[-1] in ("rustc", "rustc.exe"),
        "NOT_RUSTC_CHILD",
    )
    expanded = []
    for arg in child[1:]:
        if arg.startswith("@"):
            values = take(arg[1:])
            require(
                not any(v.startswith("@") for v in values), "NESTED_RUSTC_PARAM_FILE"
            )
            expanded.extend(values)
        else:
            expanded.append(arg)
    require(used == set(params), "UNCONSUMED_PARAM_FILE")
    return expanded, sorted(used)


def option_values(argv, name):
    values = []
    for index, value in enumerate(argv):
        if value == name:
            require(index + 1 < len(argv), "OPTION_VALUE_MISSING")
            values.append(argv[index + 1])
        elif value.startswith(name + "="):
            values.append(value[len(name) + 1 :])
    return values


def configured_graph(raw, triple):
    graph = json.loads(raw)
    targets = unique(graph["targets"], lambda item: item["id"])
    configs = unique(graph["configuration"], lambda item: item["id"])
    artifacts = unique(graph["artifacts"], lambda item: item["id"])
    fragments = unique(graph["pathFragments"], lambda item: item["id"])
    depsets = unique(graph["depSetOfFiles"], lambda item: item["id"])
    paths, resolved_inputs = {}, {}

    def fragment_path(key, active=frozenset()):
        require(key not in active and key in fragments, "INVALID_PATH_FRAGMENT_GRAPH")
        if key not in paths:
            node = fragments[key]
            parent = node.get("parentId", 0)
            paths[key] = (
                fragment_path(parent, active | {key}) + "/" if parent else ""
            ) + node["label"]
        return paths[key]

    def artifact_path(key):
        require(key in artifacts, "MISSING_ARTIFACT")
        return fragment_path(artifacts[key]["pathFragmentId"])

    def inputs(key, active=frozenset()):
        require(key not in active and key in depsets, "INVALID_INPUT_DEPSET_GRAPH")
        if key not in resolved_inputs:
            node = depsets[key]
            result = {artifact_path(item) for item in node.get("directArtifactIds", [])}
            for child in node.get("transitiveDepSetIds", []):
                result.update(inputs(child, active | {key}))
            resolved_inputs[key] = result
        return resolved_inputs[key]

    selected, asm_actions = [], []
    for action in graph["actions"]:
        require(action["targetId"] in targets, "MISSING_ACTION_OWNER")
        owner = targets[action["targetId"]]["label"]
        is_sha2, is_asm = (
            bool(SHA2_OWNER.fullmatch(owner)),
            bool(ASM_OWNER.fullmatch(owner)),
        )
        if not (is_sha2 or is_asm) or action["mnemonic"] not in (
            "Rustc",
            "RustcMetadata",
        ):
            continue
        require(action["configurationId"] in configs, "MISSING_ACTION_CONFIGURATION")
        config = configs[action["configurationId"]]
        argv, response_files = rustc_arguments(action)
        require(
            option_values(argv, "--crate-name") == ["sha2" if is_sha2 else "sha2_asm"],
            "CRATE_NAME_MISMATCH",
        )
        # Host tools may coexist in deps(); only actual target actions prove isolation.
        if config.get("isTool", False):
            require(not is_sha2, "SHA2_OWNER_ONLY_IN_EXEC_CONFIGURATION")
            continue
        require(option_values(argv, "--target") == [triple], "RUSTC_TARGET_MISMATCH")
        require(
            option_values(argv, "--crate-type") in (["rlib"], ["lib"]),
            "NOT_LIBRARY_ACTION",
        )
        require(
            re.fullmatch(r"[0-9a-f]{64}", config["checksum"]),
            "INVALID_CONFIGURATION_CHECKSUM",
        )
        crate_dir = "crates__" + ("sha2-0.10.9" if is_sha2 else "sha2-asm-0.6.4")
        require(
            any(
                value.endswith(crate_dir + "/src/lib.rs") and "external/" in value
                for value in argv
            ),
            "CRATE_SOURCE_VERSION_MISMATCH",
        )
        cfg_values = option_values(argv, "--cfg")
        require(
            all(
                re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:="[^"\\\r\n]*")?', value)
                for value in cfg_values
            ),
            "UNSUPPORTED_CFG_SYNTAX",
        )
        features = [
            value[9:-1] for value in cfg_values if value.startswith('feature="')
        ]
        require(len(features) == len(set(features)), "DUPLICATE_CRATE_FEATURE")
        externs = [
            value.split("=", 1)[1]
            for value in option_values(argv, "--extern")
            if value.startswith("sha2_asm=")
        ]
        all_inputs = set()
        for key in action.get("inputDepSetIds", []):
            all_inputs.update(inputs(key))
        row = {
            "owner": owner,
            "mnemonic": action["mnemonic"],
            "target": triple,
            "configuration_checksum": config["checksum"],
            "features": sorted(features),
            "asm_externs": externs,
            "outputs": sorted(artifact_path(key) for key in action["outputIds"]),
            "param_files": response_files,
            "input_paths": all_inputs,
        }
        (selected if is_sha2 else asm_actions).append(row)
    require(
        selected and any(row["mnemonic"] == "Rustc" for row in selected),
        "NO_TARGET_SHA2_COMPILE_ACTION",
    )
    require(
        len({row["configuration_checksum"] for row in selected}) == 1,
        "MULTIPLE_SHA2_TARGET_CONFIGURATIONS",
    )
    require(
        len({tuple(row["features"]) for row in selected}) == 1,
        "SHA2_ACTION_FEATURES_DIFFER",
    )
    for row in asm_actions:
        require(
            row["configuration_checksum"] == selected[0]["configuration_checksum"],
            "ASM_TARGET_CONFIGURATION_DIFFERS",
        )
    for row in selected:
        for dependency in row["asm_externs"]:
            require(
                dependency in row["input_paths"]
                and any(dependency in asm["outputs"] for asm in asm_actions),
                "ASM_EXTERN_NOT_LINKED_TO_TARGET_INPUT",
            )
    for row in selected + asm_actions:
        del row["input_paths"]
    return {"sha2_actions": selected, "asm_actions": asm_actions}


def platform_guard(files):
    proof = {}
    for triple in TRIPLES:
        phases = {
            phase: configured_graph(
                files["logs/aquery-" + phase + "-" + triple + ".log"], triple
            )
            for phase in ("before", "after")
        }
        before, after = phases["before"], phases["after"]
        old_features = set(before["sha2_actions"][0]["features"])
        require(
            not (
                {"asm", "sha2-asm", "force-soft", "force-soft-compact"} & old_features
            ),
            "BASE_BACKEND_FEATURES_UNEXPECTED",
        )
        require(
            not before["asm_actions"]
            and all(not row["asm_externs"] for row in before["sha2_actions"]),
            "BASE_ASM_DEPENDENCY_ALREADY_SELECTED",
        )
        enabled = triple == TRIPLES[0]
        expected = old_features | ({"asm", "sha2-asm"} if enabled else set())
        require(
            set(after["sha2_actions"][0]["features"]) == expected,
            "TARGET_FEATURE_DELTA_MISMATCH",
        )
        require(
            bool(after["asm_actions"]) == enabled,
            "TARGET_ASM_ACTION_SELECTION_MISMATCH",
        )
        require(
            all(
                len(row["asm_externs"]) == (1 if enabled else 0)
                for row in after["sha2_actions"]
            ),
            "TARGET_ASM_EXTERN_SELECTION_MISMATCH",
        )
        proof[triple] = phases
    return {
        "all_four_configured_analyses_present": True,
        "linux_aarch64_only_asm_feature_and_dependency": True,
        "actual_arguments_param_files_and_input_linkage_checked": True,
        "execution_or_hardware_speed_qualified": False,
        "configurations": proof,
    }
