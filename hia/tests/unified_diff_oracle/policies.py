"""Real Cargo builds, cached artifact admission and eight real rejection commands."""
import json
import os
from pathlib import Path
import sys

from .common import bind, require


def profiles(context):
    root = Path(context.config["_binding"]["path"]).parent if "_binding" in context.config else Path(context.env["CODEX_HIA_SIMILAR_POLICY_CONFIG"]).parent
    result = {}
    for name, expected in context.ci.PROFILE_CONFIGS.items():
        path = root / "policy-profiles" / name
        require(path.read_text() == expected and str(path.resolve()) in context.config["extra_inputs"],
                "qualification profile was not bound by the actual configuration")
        result[name] = path
    return result


def cargo_args(context):
    return ["--locked", *(["--offline"] if context.args.offline else []),
            "--no-default-features", "-p", "codex-apply-patch", "--features", "hia-native",
            "--lib", "--jobs", "1", "--message-format=json-render-diagnostics"]


def verify_log(context, name, outcome, mode):
    row = context.run(name, [sys.executable, context.repo / "hia/similar_policy.py",
                            "--verify-cargo-log", outcome["stdout"]["path"]])
    value = json.loads(Path(row["stdout"]["path"]).read_bytes())
    require(value["passed"] and value["cargo_log"] == outcome["stdout"], "Cargo log binding differs")
    require(value["consumer_artifacts"] and all(x["policy_mode"] == mode for x in value["consumer_artifacts"]),
            "actual compiler policy differs from this qualification mode")
    return value


def build(context, mode):
    name = "checked" if mode == 0 else "wrapping"
    cargo = context.rustc.parent / "cargo"
    prefix = [] if mode == 0 else ["--config", profiles(context)["wrapping.toml"]]
    command = [cargo, *prefix, "build", *cargo_args(context)]
    built = context.run(name + "-build", command)
    rows = [json.loads(x) for x in Path(built["stdout"]["path"]).read_text().splitlines()]
    require(rows[-1] == {"reason": "build-finished", "success": True}, "Cargo did not finish")
    owners = [x for x in rows if x.get("reason") == "compiler-artifact" and x["target"]["name"] == "codex_apply_patch"]
    require(len(owners) == 1 and owners[0]["features"] == ["hia-native"], "wrong actual owner feature inventory")
    require(Path(owners[0]["target"]["src_path"]).resolve() == context.repo / "codex-rs/apply-patch/src/lib.rs",
            "Cargo selected another owner")
    qualified = verify_log(context, name + "-admission", built, mode)
    cached = context.run(name + "-cached-build", command)
    cached_rows = [json.loads(x) for x in Path(cached["stdout"]["path"]).read_text().splitlines()]
    selected = [x for x in cached_rows if x.get("reason") == "compiler-artifact" and x["target"]["name"] in ("similar", "codex_apply_patch")]
    require({x["target"]["name"] for x in selected} == {"similar", "codex_apply_patch"}
            and all(x["fresh"] is True for x in selected), "the actual second build was not cached")
    cached_admission = verify_log(context, name + "-cached-admission", cached, mode)
    libraries = [x for x in qualified["consumer_artifacts"] if x["actual_cargo_artifact"]["path"].endswith(".rlib")]
    require(len(libraries) == 1, "missing or ambiguous actual owner rlib")
    selected_path = libraries[0]["actual_cargo_artifact"]["path"]
    index = context.helper.index_path(context.helper_cfg, selected_path)
    pointer = json.loads(index.read_text())
    require(bind(pointer["receipt"]["path"]) == pointer["receipt"], "actual owner receipt changed")
    actual, receipt = context.helper.select_receipt(context.helper_cfg, selected_path, "consumer")
    require(actual == libraries[0]["actual_cargo_artifact"] and receipt["policy_mode"] == mode,
            "selected owner artifact policy differs")
    dependencies = {}
    for value in context.helper.option_values(receipt["argv"], "--extern"):
        name, source = value.split("=", 1)
        source = Path(source).resolve(strict=True)
        library = source.with_suffix(".rlib") if source.suffix == ".rmeta" else source
        matches = [row for row in rows if row.get("reason") == "compiler-artifact"
                   and row["target"]["name"].replace("-", "_") == name
                   and str(library) in row["filenames"]]
        require(len(matches) == 1, "selected dependency absent or ambiguous in actual Cargo output: " + name)
        dependencies[name] = {"selected": bind(source), "link_library": bind(library),
                              "cargo_unit": matches[0]}
    return {"passed": True, "mode": mode, "actual_cargo_owner": owners[0], "build": built,
            "actual_policy_admission": qualified, "cached_build": cached,
            "cached_admission": cached_admission, "actual_owner_receipt": pointer["receipt"],
            "actual_defining_extern": receipt["selected_extern"], "actual_owner_extern_inputs": dependencies}


def negatives(context, checked, wrapping):
    require(checked["passed"] and wrapping["passed"], "both actual positive builds are required")
    receipt = json.loads(Path(checked["actual_owner_receipt"]["path"]).read_bytes())
    helper = context.repo / "hia/similar_policy.py"
    cargo = context.rustc.parent / "cargo"
    root = context.output / "negatives"
    root.mkdir()
    rows = []
    def reject(name, args, expected, reason, env=None):
        row = context.run(name, args, env, expected=expected, diagnostic=reason)
        rows.append({**row, "expected_returncode": expected, "expected_diagnostic": reason,
                     "rejected": True, "actual_command_executed": True})
    for name, profile in (("mixed-defining-wrapping", "mixed.toml"),
                          ("mixed-owner-wrapping", "mixed-opposite.toml")):
        reject(name, [cargo, "--config", profiles(context)[profile], "build", *cargo_args(context)],
               101, "mixed arithmetic category mapping is not admitted")
    selected = Path(receipt["selected_extern"]["path"])
    index_path = context.helper.index_path(context.helper_cfg, selected)
    pointer = json.loads(index_path.read_bytes())
    defining = json.loads(Path(pointer["receipt"]["path"]).read_bytes())
    relocated = []
    hidden = root / "temporarily-hidden-indices"
    hidden.mkdir()
    try:
        for path in sorted((Path(context.config["receipt_root"]) / "indices").glob("*.json")):
            value = json.loads(path.read_bytes())
            if value["receipt"] == pointer["receipt"]:
                backup = hidden / path.name
                path.rename(backup)
                relocated.append((path, backup))
        require(relocated, "no actual selected receipt index to hide")
        reject("missing-selected-receipt", [cargo, "rustc", *cargo_args(context), "--", "--cfg",
               "hia_missing_receipt_fixture"], 101, "missing defining-crate policy receipt")
    finally:
        for path, backup in relocated:
            require(not path.exists(), "receipt lookup was concurrently replaced")
            backup.rename(path)
    original = selected.read_bytes()
    before, metadata = bind(selected), selected.stat()
    try:
        altered = bytearray(original)
        altered[-1] ^= 1
        selected.write_bytes(altered)
        reject("tampered-actual-selected-artifact", [sys.executable, helper,
               "--verify-defining-artifact", selected], 74, "selected actual artifact changed")
    finally:
        selected.write_bytes(original)
        os.utime(selected, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    require(bind(selected) == before, "actual selected artifact was not restored")
    direct_env = dict(context.env, CARGO_MANIFEST_DIR=receipt["source_root"],
                      CARGO_PKG_NAME="codex-apply-patch", CARGO_PKG_VERSION="0.0.0")
    def redirected(name):
        args = list(receipt["argv"])
        directory = root / name
        directory.mkdir()
        args[args.index("--out-dir") + 1] = str(directory)
        return args
    for name, option in (("lto-thin", "lto=thin"), ("lto-fat", "lto=fat"),
                         ("linker-plugin-lto", "linker-plugin-lto=yes")):
        reject(name, [sys.executable, helper, context.rustc, *redirected(name), "-C", option],
               74, "unsupported LTO policy arrangement", direct_env)
    reject("missing-explicit-policy-cfg", [context.rustc, *redirected("missing-cfg")], 1,
           "hia-native unified diff requires an admitted same-policy compiler receipt", direct_env)
    require(all(bind(x["path"]) == x for x in defining["artifacts"]), "defining artifacts changed during rejection gate")
    require(len(rows) == 8, "the actual eight-command rejection inventory changed")
    return {"passed": True, "rejection_count": len(rows), "commands": rows,
            "selected_artifact_restored": before, "hidden_indices_restored": len(relocated),
            "defining_receipt": pointer["receipt"], "all_build_arrangements_qualified": False}
