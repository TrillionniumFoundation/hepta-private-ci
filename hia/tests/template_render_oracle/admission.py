"""Admit both template components against the actual complete producer build."""
import json
from pathlib import Path

from template_parse_oracle import admission as parse_admission

MODULE, SYMBOL = "template_render", "codex_hia_template_render"
CONTRACT_SHA = "2ad593ca2d76c7ed8eb9ef3b47d52a70fcd3ea3f77bc1ef25b595bdff440fe94"
sha, require = parse_admission.sha, parse_admission.require


def admit(producer, library_dir):
    # Preserve the complete existing parse/bootstrap/all-module admission first.
    build, _, inputs = parse_admission.admit(producer, library_dir)
    source = producer / "hia/template_render.hepta"
    contract_path = producer / "hia/template_render_buffer_contract.json"
    lock = build["toolchain"]
    require(MODULE in lock["modules"] and MODULE in build["modules"],
            "the complete actual build lacks the native renderer")
    contract = json.loads(contract_path.read_text())
    require(sha(contract_path) == CONTRACT_SHA
            and contract.get("schema") == "codex.hia.template-render-buffer-contract.v1"
            and contract.get("revision") == 1 and contract.get("module") == MODULE
            and contract.get("symbol") == SYMBOL,
            "the reviewed complete render buffer contract differs")
    component = build["modules"][MODULE]
    require(component.get("source_sha256") == sha(source)
            and component.get("entry_profile") == "borrowed-buffers-u32-v1"
            and lock.get("entry_profiles", {}).get(MODULE, "borrowed-buffers-u32-v1")
            == "borrowed-buffers-u32-v1", "stale render source or incompatible native profile")
    abi = component["codex_link_abi"]
    require(abi.get("symbol") == SYMBOL and abi.get("defined_symbols") == [SYMBOL]
            and abi.get("undefined_symbols") == [], "wrong render object symbol inventory")
    artifacts = {}
    for kind, name in (("library", "libcodex_hia_template_render.so"),
                       ("archive", "libcodex_hia_template_render.a"),
                       ("object", "template_render.namespaced.o")):
        path = library_dir / name
        require(abi.get(kind) == name and abi.get(kind + "_sha256") == sha(path),
                "stale render native artifact: " + kind)
        artifacts[kind] = path
    raw = library_dir / "template_render.o"
    compiler_input = library_dir / "template_render.input.bin"
    inventory, compilation = component["object_inventory"], component["compilation"]
    require(inventory.get("object_sha256") == sha(raw) and inventory.get("exports") == ["f0"]
            and inventory.get("undefined_symbols") == [] and inventory.get("external_relocations") == []
            and inventory.get("entry_wrapper_bytes") == 78, "wrong raw render buffer object")
    require(compilation.get("status") == "returned" and compilation.get("abi_status") == 0
            and compilation.get("source_unchanged") is True
            and compilation.get("forbidden_compiler_modules_loaded") == []
            and compilation.get("produced_sha256") == sha(raw)
            and compilation.get("source_sha256") == sha(compiler_input)
            and compilation.get("image_sha256") == build["compiler_sha256"]
            and compilation.get("artifact_sha256") == build["compiler_sha256"],
            "the renderer lacks the genuine fixed-point compilation receipt")
    extra = [Path(__file__).resolve(), source, contract_path, raw, compiler_input,
             *artifacts.values(), producer / "codex-rs/utils/template/src/hia_native_render.rs",
             producer / "codex-rs/utils/template/build.rs",
             producer / "hia/tests/test_template_render_abi.py",
             *sorted(Path(__file__).parent.glob("*.py"))]
    for path in extra:
        inputs[str(path)] = {"bytes": path.stat().st_size, "sha256": sha(path)}
    return build, artifacts["library"], inputs
