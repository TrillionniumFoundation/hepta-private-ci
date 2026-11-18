"""Bind template parse behavior gates to the actual complete native build and producer."""
import hashlib
import json
from pathlib import Path
import sys

MODULE, SYMBOL = "template_parse", "codex_hia_template_parse"

def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def admit(producer, library_dir):
    require(sys.flags.optimize == 0, "qualification cannot disable Python assertions")
    source = producer / "hia/template_parse.hepta"
    contract_path = producer / "hia/template_parse_buffer_contract.json"
    lock_path, driver_path = producer / "hia/toolchain.json", producer / "hia/build.py"
    helper_path = producer / "hia/cargo_build.rs"
    build_path = library_dir / "build.json"
    build, lock = json.loads(build_path.read_text()), json.loads(lock_path.read_text())
    require(build.get("schema") == "codex.hia.native-build.v1" and
            build.get("status") == "built" and build.get("build_mode") == "native-selfhost"
            and build.get("compiler_fixed_point") is True,
            "a genuine complete native-selfhost build is required")
    require(build.get("toolchain") == lock and
            build.get("toolchain_lock_sha256") == sha(lock_path) and
            set(build["modules"]) == set(lock["modules"]) and MODULE in lock["modules"],
            "the complete build is not bound to the current locked module inventory")
    require(build.get("build_driver_sha256") == sha(driver_path) and
            build.get("cargo_helper_sha256") == sha(helper_path),
            "the actual native build driver/helper differs from the producer")
    module_sources = []
    for name in lock["modules"]:
        path = producer / "hia" / (name + ".hepta")
        require(build["modules"][name]["source_sha256"] == sha(path),
                "a locked native program differs from the actual complete build")
        module_sources.append(path)
    contract = json.loads(contract_path.read_text())
    require(sha(contract_path) == "694469d618325b30ec5f81093d573f39cad3d76ef8bcb87514a1be7db47393aa"
            and contract.get("schema") == "codex.hia.template-parse-buffer-contract.v1"
            and contract.get("revision") == 1 and contract.get("module") == MODULE
            and contract.get("symbol") == SYMBOL,
            "the complete reviewed template parse byte-pattern contract differs")
    component = build["modules"][MODULE]
    require(component.get("source_sha256") == sha(source) and
            component.get("entry_profile") == "borrowed-buffers-u32-v1" and
            lock.get("entry_profiles", {}).get(MODULE, "borrowed-buffers-u32-v1") ==
            "borrowed-buffers-u32-v1", "stale source or incompatible native entry profile")
    abi = component["codex_link_abi"]
    require(abi.get("symbol") == SYMBOL and abi.get("defined_symbols") == [SYMBOL] and
            abi.get("undefined_symbols") == [], "the namespaced object has a wrong symbol inventory")
    artifacts = {}
    for kind, name in (("library", "libcodex_hia_template_parse.so"),
                       ("archive", "libcodex_hia_template_parse.a"),
                       ("object", "template_parse.namespaced.o")):
        path = library_dir / name
        require(abi.get(kind) == name and abi.get(kind + "_sha256") == sha(path),
                "stale native artifact: " + kind)
        artifacts[kind] = path
    raw = library_dir / "template_parse.o"
    compiler_input = library_dir / "template_parse.input.bin"
    inventory, compilation = component["object_inventory"], component["compilation"]
    require(inventory.get("object_sha256") == sha(raw) and inventory.get("exports") == ["f0"]
            and inventory.get("undefined_symbols") == [] and inventory.get("external_relocations") == []
            and inventory.get("entry_wrapper_bytes") == 78,
            "the raw object differs from the admitted buffer object")
    require(compilation.get("status") == "returned" and compilation.get("abi_status") == 0
            and compilation.get("source_unchanged") is True
            and compilation.get("forbidden_compiler_modules_loaded") == []
            and compilation.get("produced_sha256") == sha(raw)
            and compilation.get("source_sha256") == sha(compiler_input)
            and compilation.get("image_sha256") == build["compiler_sha256"]
            and compilation.get("artifact_sha256") == build["compiler_sha256"],
            "the module lacks the genuine fixed-point compilation receipt")
    generations = build["bootstrap_generations"]
    require([item.get("case") for item in generations] == ["B1", "B2", "B3"],
            "the actual compiler bootstrap generations are incomplete")
    images = []
    for generation in generations:
        image = library_dir / "bootstrap" / (generation["case"] + ".image.bin")
        require(generation.get("status") == "returned" and generation.get("abi_status") == 0
                and generation.get("source_unchanged") is True
                and generation.get("forbidden_compiler_modules_loaded") == []
                and generation.get("produced_sha256") == build["compiler_sha256"] == sha(image),
                "the actual bootstrap generation does not match the fixed-point image")
        images.append(image)
    inputs = {str(path): {"bytes": path.stat().st_size, "sha256": sha(path)} for path in (
        Path(__file__).resolve(), source, contract_path, lock_path, driver_path, helper_path,
        build_path, raw, compiler_input, *artifacts.values(), *images, *module_sources)}
    for path in [producer / "codex-rs/utils/template/src/hia_native_parse.rs",
                 producer / "codex-rs/utils/template/src/lib.rs",
                 *sorted(Path(__file__).parent.glob("*.py"))]:
        inputs[str(path)] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    from . import index_admission

    inputs.update(index_admission.admit(producer, library_dir, build))
    return build, artifacts["library"], inputs
