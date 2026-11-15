"""Per-checkout policy configuration; no diff algorithm or profile inference."""
import hashlib
import json
import os
from pathlib import Path
import platform
import types

RUSTC_SHA = "4a84e05991ad6f2a84c1361c29b52b38c390365bd1fc269b1936c88d482a8928"
CLIPPY_SHA = "4b6976de2e62e12adaa5e6ef190b1d3f3fbf062e0f8ea5f4014fca45fb918a66"
EXACT = {
    "hia/unified_policy_fix.py": "430de4f64db34d45af073fcc335deeae8f18d5a0169f0a57184306ecf915e26c",
    "hia/unified_policy_fix_outer.py": "0c49c7ac11f17b5d91b75ec9539ccc64e6a45e3fd71a7a3f58c650af8eb2347b",
    "hia/unified_policy_fix_workspace.py": "9a8564f68be52f42810b94b4b843714b2b631c119304b4b179d0eccb7e4c657a",
    "hia/similar_policy.py": "8d97a44b12a7626ed567789ddede9a17f50ac63fe0b0d99c359a60ff38ab1d96",
    "hia/similar-source.json": "7fceb120e1cefbf4de7677fbc15dfe65ce845c23fb23b64eb73fede8afb8999f",
    "hia/unified_diff.hepta": "36e347f329d061af2e6f45fbd7f0897b3c0a870a54b3d05090b335bfbce72ef5",
    "hia/unified_diff_buffer_contract.json": "758ffca2ba472ba7e8cd0618a92b5867c611efcdbc633d00ecae9bbafea1045e",
    "codex-rs/apply-patch/src/hia_native_unified_diff.rs": "cddc068db30a8dc14766c8eea1a7a951010872e0a9970875ea9a9e012a84c144",
    "codex-rs/apply-patch/src/hia_native_unified_diff_policy.rs": "90bdecd1249fbcb4a70f051b910c79befde27aa2d04a5ee5354843eafba12bea",
}
MANDATORY = (
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/.cargo/config.toml",
    "codex-rs/rust-toolchain.toml", "codex-rs/apply-patch/Cargo.toml",
    "codex-rs/apply-patch/build.rs", "hia/toolchain.json", "hia/build.py",
    "hia/cargo_build.rs", "hia/unified_policy_ci.py", "hia/prepare_unified_diff_policy.py",
    "justfile", "scripts/just-shell.py",
    *EXACT,
)
CONFIG_KEYS = {"schema", "rustc", "receipt_root", "consumer_crate", "consumer_package",
               "consumer_root", "extra_inputs", "supported_modes"}
PROFILE_CONFIGS = {
    "wrapping.toml": "[profile.dev.package.similar]\noverflow-checks=false\n[profile.dev.package.codex-apply-patch]\noverflow-checks=false\n",
    "mixed.toml": "[profile.dev.package.similar]\noverflow-checks=false\n",
    "mixed-opposite.toml": "[profile.dev.package.codex-apply-patch]\noverflow-checks=false\n",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def binding(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            digest.update(block)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def source_inputs(repo):
    repo = Path(repo).resolve(strict=True)
    records = []
    for relative in sorted(set(MANDATORY)):
        path = repo / relative
        require(not path.is_symlink(), "policy input symlink is not admitted: " + relative)
        row = binding(path)
        require(Path(row["path"]).is_relative_to(repo), "policy input escaped checkout")
        if relative in EXACT:
            require(row["sha256"] == EXACT[relative], "frozen policy input differs: " + relative)
        records.append(row)
    return records


def load_helper(repo):
    path = Path(repo).resolve(strict=True) / "hia/similar_policy.py"
    require(binding(path)["sha256"] == EXACT["hia/similar_policy.py"], "unknown policy wrapper")
    module = types.ModuleType("admitted_similar_policy")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def validate_configuration(repo, rustc, config_path):
    repo, rustc = Path(repo).resolve(strict=True), Path(rustc).resolve(strict=True)
    require(platform.system() == "Linux" and platform.machine() == "x86_64",
            "only native Linux x86-64 is admitted")
    compiler = binding(rustc)
    require(compiler["sha256"] == RUSTC_SHA, "unqualified policy compiler")
    sources = source_inputs(repo)
    path = Path(config_path).resolve(strict=True)
    value = json.loads(path.read_text())
    require(set(value) == CONFIG_KEYS, "unknown policy configuration keys")
    expected = {"schema": "codex.hia.similar-policy-config.v1", "rustc": str(rustc),
                "consumer_crate": "codex_apply_patch", "consumer_package": "codex-apply-patch",
                "consumer_root": str(repo / "codex-rs/apply-patch"), "supported_modes": [0, 1]}
    require(all(value.get(k) == v for k, v in expected.items()), "policy configuration scope differs")
    require(all(type(mode) is int for mode in value["supported_modes"]), "policy modes must be integers")
    extras = value["extra_inputs"]
    require(isinstance(extras, list) and all(isinstance(x, str) for x in extras), "invalid policy inputs")
    require(extras == sorted(set(extras)), "policy inputs must be unique and sorted")
    bound = [binding(p) for p in extras]
    require([x["path"] for x in bound] == extras, "policy inputs must use canonical actual paths")
    require({x["path"] for x in sources} <= set(extras), "required policy inputs were omitted")
    receipts = Path(value["receipt_root"]).resolve()
    require(str(receipts) == value["receipt_root"] and not receipts.is_relative_to(repo),
            "receipt output must be canonical and outside the source checkout")
    require(not path.is_relative_to(repo), "configuration must be outside the source checkout")
    return value, {"config": binding(path), "compiler": compiler, "source_inputs": bound,
                   "receipt_root": str(receipts), "supported_modes": [0, 1],
                   "mixed_policy_qualified": False, "lto_qualified": False}


def admit_environment(repo, rustc, env):
    wrapper = env.get("RUSTC_WRAPPER")
    workspace = env.get("RUSTC_WORKSPACE_WRAPPER")
    if not wrapper:
        require(not workspace, "an unverified workspace rustc wrapper cannot qualify this oracle")
        return None
    expected = Path(repo).resolve(strict=True) / "hia/similar_policy.py"
    require(Path(wrapper).resolve(strict=True) == expected, "unverified rustc wrapper path")
    require(binding(expected)["sha256"] == EXACT["hia/similar_policy.py"], "unverified rustc wrapper bytes")
    require(env.get("CODEX_HIA_SIMILAR_POLICY_CONFIG"), "missing producer policy configuration")
    _, record = validate_configuration(repo, rustc, env["CODEX_HIA_SIMILAR_POLICY_CONFIG"])
    record["wrapper"] = binding(expected)
    if workspace:
        require(binding(workspace)["sha256"] == CLIPPY_SHA, "unverified workspace wrapper bytes")
        require(env.get("CLIPPY_ARGS", "") == os.environ.get("CLIPPY_ARGS", ""),
                "Clippy environment differs from the validated compiler chain")
        load_helper(repo).compiler_chain([workspace, str(rustc)], {"rustc": str(rustc)})
        record["workspace_wrapper"] = binding(workspace)
    return record


def configure(repo, rustc, output, receipts, extra_inputs=()):
    repo, rustc = Path(repo).resolve(strict=True), Path(rustc).resolve(strict=True)
    output, receipts = Path(output).resolve(), Path(receipts).resolve()
    require(not output.is_relative_to(repo) and not receipts.is_relative_to(repo),
            "generated configuration and receipts must be outside the source checkout")
    inputs = {x["path"] for x in source_inputs(repo)}
    inputs.update(binding(path)["path"] for path in extra_inputs)
    profiles = output.parent / "policy-profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    for name, text in PROFILE_CONFIGS.items():
        profile = profiles / name
        try:
            with profile.open("x") as stream:
                stream.write(text)
        except FileExistsError:
            require(profile.read_text() == text, "refusing to replace a changed qualification profile")
        inputs.add(str(profile.resolve()))
    value = {"schema": "codex.hia.similar-policy-config.v1", "rustc": str(rustc),
             "receipt_root": str(receipts), "consumer_crate": "codex_apply_patch",
             "consumer_package": "codex-apply-patch", "consumer_root": str(repo / "codex-rs/apply-patch"),
             "extra_inputs": sorted(inputs), "supported_modes": [0, 1]}
    data = (json.dumps(value, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        require(output.read_bytes() == data, "refusing to replace a different policy configuration")
    _, record = validate_configuration(repo, rustc, output)
    return {"schema": "codex.hia.unified-policy-configuration.v1", "passed": True, **record,
            "environment": {"RUSTC_WRAPPER": str(repo / "hia/similar_policy.py"),
                            "CODEX_HIA_SIMILAR_POLICY_CONFIG": str(output)},
            "actual_compiler_artifacts_qualified": False,
            "scope": "Configuration identity only; real compiler artifacts require separate receipt admission."}
