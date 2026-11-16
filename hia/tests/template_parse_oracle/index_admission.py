"""Admit the Index's real native artifacts before it joins the template links."""
from pathlib import Path

from .common import require, sha

MODULE, SYMBOL = "template_index", "codex_hia_template_index"
SOURCE_SHA = "e839d8dcbd7ec81721b79b6cdba490a3e951b1eab55f29d04e11e61c8f12575a"
CONTRACT_SHA = "1740045a062382b1e9eb620491e04a2a49add345df40d59f5d236fcc5e83b61b"
# Exact field order of the unchanged hia/build.py and hia/cargo_build.rs.
LINK_FIELDS = (
    "module", "target", "mode", "revision", "symbol", "object", "archive",
    "archive_member", "source_sha256", "toolchain_lock_sha256",
    "build_driver_sha256", "cargo_helper_sha256", "object_sha256",
    "text_sha256", "archive_sha256", "compiler_sha256", "build_report_sha256",
)


def admit(producer, library_dir, build):
    # The caller first admits the complete lock, build, source inventory and
    # all three bootstrap generations. Add actual Index identities, not names.
    lock = build["toolchain"]
    require(MODULE in lock["modules"] and MODULE in build["modules"],
            "the complete build lacks the placeholder Index")
    source = producer / "hia/template_index.hepta"
    contract = producer / "hia/template_buffer_contract.md"
    require(sha(source) == SOURCE_SHA and sha(contract) == CONTRACT_SHA,
            "the reviewed Index source or contract differs")
    component = build["modules"][MODULE]
    require(component.get("source_sha256") == sha(source)
            and component.get("entry_profile") == "borrowed-buffers-u32-v1"
            and lock.get("entry_profiles", {}).get(MODULE, "borrowed-buffers-u32-v1")
            == "borrowed-buffers-u32-v1"
            and lock["target"] == "x86_64-unknown-linux-gnu",
            "stale Index source or incompatible native profile")
    abi = component["codex_link_abi"]
    require(abi.get("symbol") == SYMBOL and abi.get("defined_symbols") == [SYMBOL]
            and abi.get("undefined_symbols") == [] and abi.get("archive_member") == "hia.o",
            "wrong Index object symbol or archive-member inventory")
    artifacts = {}
    for kind, name in (("library", "libcodex_hia_template_index.so"),
                       ("archive", "libcodex_hia_template_index.a"),
                       ("object", "template_index.namespaced.o")):
        path = library_dir / name
        require(abi.get(kind) == name and abi.get(kind + "_sha256") == sha(path),
                "stale Index native artifact: " + kind)
        artifacts[kind] = path
    raw = library_dir / "template_index.o"
    compiler_input = library_dir / "template_index.input.bin"
    inventory, compilation = component["object_inventory"], component["compilation"]
    require(inventory.get("object_sha256") == sha(raw) and inventory.get("exports") == ["f0"]
            and inventory.get("undefined_symbols") == [] and inventory.get("external_relocations") == []
            and inventory.get("entry_wrapper_bytes") == 78,
            "wrong raw Index buffer object")
    require(compilation.get("status") == "returned" and compilation.get("abi_status") == 0
            and compilation.get("source_unchanged") is True
            and compilation.get("forbidden_compiler_modules_loaded") == []
            and compilation.get("produced_sha256") == sha(raw)
            and compilation.get("source_sha256") == sha(compiler_input)
            and compilation.get("image_sha256") == build["compiler_sha256"]
            and compilation.get("artifact_sha256") == build["compiler_sha256"],
            "the Index lacks the genuine fixed-point compilation receipt")
    # Keep the actual .link in native_inputs as well as build.json. The Cargo
    # helper independently verifies its object text, exact archive member and
    # bootstrap bytes before publishing the OUT_DIR archive.
    receipt = library_dir / "template_index.link"
    fields = {
        "module": MODULE, "target": lock["target"], "mode": "native-selfhost",
        "revision": lock["revision"], "symbol": SYMBOL,
        "object": artifacts["object"].name, "archive": artifacts["archive"].name,
        "archive_member": "hia.o", "source_sha256": sha(source),
        "toolchain_lock_sha256": build["toolchain_lock_sha256"],
        "build_driver_sha256": build["build_driver_sha256"],
        "cargo_helper_sha256": build["cargo_helper_sha256"],
        "object_sha256": abi["object_sha256"], "text_sha256": abi["text_sha256"],
        "archive_sha256": abi["archive_sha256"],
        "compiler_sha256": build["compiler_sha256"],
        "build_report_sha256": sha(library_dir / "build.json"),
    }
    expected = "codex.hia.static-link.v1\n" + "".join(f"{key}={fields[key]}\n" for key in LINK_FIELDS)
    require(receipt.read_bytes() == expected.encode("ascii"),
            "Index static-link receipt differs from the actual complete build and artifacts")
    extra = [Path(__file__).resolve(), source, contract, raw, compiler_input, receipt,
             *artifacts.values(),
             producer / "codex-rs/utils/template/src/hia_native_index.rs",
             producer / "codex-rs/utils/template/src/hia_native_placeholders.rs",
             producer / "codex-rs/utils/template/src/hia_native_index_tests.rs",
             producer / "hia/tests/test_template_index_abi.py"]
    return {str(path): {"bytes": path.stat().st_size, "sha256": sha(path)} for path in extra}
