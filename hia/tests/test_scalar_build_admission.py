"""Check scalar entry admission against real B3 artifacts and rejected mutations.

Core projections below exercise entry-profile and header checks only. They do not
replace assembler verification, native compilation, or behavioral comparisons.
All ELF mutations stay in memory; qualified build inputs remain unchanged.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODULE = "token_budget"
PROFILE = "u64-pair-to-u64-v1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def check_object_source(builder, observed):
    # The module name also occurs inside the body. Only the header may change.
    module = "scalar_header_probe"
    body = (b"exports(f0)\n"
            b"fn f0(scalar_header_probe:u64,operation:u64) -> (u64) effects() entry(entry)\n"
            b"block entry(scalar_header_probe:u64,operation:u64)\n"
            b"  ret(scalar_header_probe)\nend\n")
    for version in ("v8", "v9"):
        schema = f"hepta.hia.program.{version}"
        source = f"hia-asm.v1 {schema} {module}\n".encode() + body
        expected = f"hia-asm.v1 {schema} selfhost_elf\n".encode() + body
        actual = builder.selfhost_object_source(source, {"schema": schema, "module": module})
        if actual != expected:
            raise AssertionError(f"object source changed the {version} schema or body")
        observed.append(f"preserve-{version}-object-source-schema-and-body")
    program = {"schema": "hepta.hia.program.v8", "module": module}
    for label, header, candidate in [
        ("unknown-source-schema", f"hia-asm.v1 hepta.hia.program.v10 {module}",
         {"schema": "hepta.hia.program.v10", "module": module}),
        ("source-schema-differs-from-core", f"hia-asm.v1 hepta.hia.program.v9 {module}", program),
        ("source-module-differs-from-core", "hia-asm.v1 hepta.hia.program.v8 other_module", program),
        ("source-assembly-tag-differs", f"hia-asm.v2 hepta.hia.program.v8 {module}", program),
        ("source-header-extra-token", f"hia-asm.v1 hepta.hia.program.v8 {module} extra", program),
    ]:
        try:
            builder.selfhost_object_source(header.encode() + b"\n" + body, candidate)
        except ValueError:
            observed.append(label)
        else:
            raise AssertionError(f"object source accepted {label}")


def check_profile(builder, lock, module, observed, borrowed_module=None):
    if borrowed_module is None:
        borrowed_module = next((name for name in lock["modules"]
                                if lock.get("entry_profiles", {}).get(name, "borrowed-buffers-u32-v1")
                                == "borrowed-buffers-u32-v1"), None)
    elif (borrowed_module not in lock["modules"]
          or lock.get("entry_profiles", {}).get(borrowed_module, "borrowed-buffers-u32-v1")
          != "borrowed-buffers-u32-v1"):
        raise AssertionError("explicit borrowed fixture must be a locked borrowed module")
    if borrowed_module is None:
        raise AssertionError("a locked borrowed module is required to check the default profile")
    scalar = {"exports": ["f0"], "functions": [{"name": "f0", "params": [
        {"name": "value", "type": "u64"}, {"name": "operation", "type": "u64"}],
        "returns": ["u64"]}]}
    borrowed = {"functions": [{"name": "f0", "params": [
        {"name": "source", "type": "readbuf"}, {"name": "output", "type": "mutbuf"},
        {"name": "workspace", "type": "mutbuf"}], "returns": ["u32"]}]}
    if builder.entry_profile(lock, module, scalar) != PROFILE:
        raise AssertionError("scalar entry profile was not selected")
    observed.append("accept-scalar-entry")
    if builder.entry_profile(lock, borrowed_module, borrowed) != "borrowed-buffers-u32-v1":
        raise AssertionError("borrowed entry default changed")
    observed.append("accept-borrowed-entry")
    reordered = copy.deepcopy(scalar)
    helper = copy.deepcopy(scalar["functions"][0])
    helper["name"] = "private_helper"
    reordered["functions"].insert(0, helper)
    if builder.entry_profile(lock, module, reordered) != PROFILE:
        raise AssertionError("explicit scalar export must bind by name")
    observed.append("accept-scalar-entry-after-private-helper")

    def reject(label, candidate_lock, program, name=module):
        try:
            builder.entry_profile(candidate_lock, name, program)
        except ValueError:
            observed.append(label)
        else:
            raise AssertionError(f"entry profile accepted {label}")

    for label, value in [("unknown-profile", "unknown-v1"), ("empty-profile", ""),
                         ("list-profile", []), ("integer-profile", 1)]:
        changed = copy.deepcopy(lock)
        changed["entry_profiles"][module] = value
        reject(label, changed, scalar)
    changed = copy.deepcopy(lock)
    changed["entry_profiles"]["unlocked_module"] = PROFILE
    reject("profile-for-unlocked-module", changed, scalar)
    changed = copy.deepcopy(lock)
    changed["entry_profiles"] = []
    reject("profiles-not-an-object", changed, scalar)
    changed = copy.deepcopy(lock)
    del changed["entry_profiles"][module]
    reject("scalar-without-locked-profile", changed, scalar)
    for label, params in [("missing-parameter", scalar["functions"][0]["params"][:1]),
                          ("extra-parameter", scalar["functions"][0]["params"] + [{"name": "extra", "type": "u64"}]),
                          ("resource-parameter", borrowed["functions"][0]["params"]),
                          ("wrong-scalar-type", [{"name": "value", "type": "usize"}, {"name": "operation", "type": "u64"}])]:
        changed = copy.deepcopy(scalar)
        changed["functions"][0]["params"] = params
        reject(label, lock, changed)
    for label, returns in [("missing-return", []), ("wrong-return", ["u32"]),
                           ("extra-return", ["u64", "u64"])]:
        changed = copy.deepcopy(scalar)
        changed["functions"][0]["returns"] = returns
        reject(label, lock, changed)
    for label, exports in [("missing-export", []), ("wrong-export", ["private_helper"]),
                           ("extra-export", ["f0", "private_helper"]), ("duplicate-export", ["f0", "f0"])]:
        changed = copy.deepcopy(scalar)
        changed["exports"] = exports
        reject(label, lock, changed)
    changed = copy.deepcopy(scalar)
    changed.pop("exports")
    reject("no-explicit-scalar-exports", lock, changed)
    changed = copy.deepcopy(scalar)
    changed["functions"][0]["name"] = "other"
    reject("missing-f0", lock, changed)
    changed = copy.deepcopy(scalar)
    changed["functions"].append(copy.deepcopy(changed["functions"][0]))
    reject("duplicate-f0", lock, changed)
    changed = copy.deepcopy(borrowed)
    changed["exports"] = ["f0"]
    reject("borrowed-explicit-resource-export", lock, changed, borrowed_module)
    changed = copy.deepcopy(borrowed)
    first = copy.deepcopy(changed["functions"][0])
    first["name"] = "different_byte_entry"
    changed["functions"].insert(0, first)
    reject("borrowed-entry-not-first", lock, changed, borrowed_module)


def check_elf(builder, raw, observed):
    inventory = builder.inspect_scalar_object(raw)
    observed.append("accept-real-b3-scalar-object")
    table = struct.unpack_from("<Q", raw, 40)[0]
    sections = [struct.unpack_from("<IIQQQQIIQQ", raw, table + i * 64) for i in range(7)]
    symbols = sections[2][4]
    public = symbols + 48

    def reject(label, changed):
        try:
            builder.inspect_scalar_object(bytes(changed))
        except ValueError:
            observed.append(label)
        else:
            raise AssertionError(f"scalar object accepted {label}")

    def field(label, at, fmt, value):
        changed = bytearray(raw)
        struct.pack_into(fmt, changed, at, value)
        reject(label, changed)

    reject("truncated-header", raw[:63])
    reject("trailing-object-data", raw + b"\0")
    field("wrong-machine", 18, "<H", 183)
    field("wrong-object-kind", 16, "<H", 3)
    field("wrong-section-count", 60, "<H", 6)
    field("non-null-section-zero", table + 8, "<Q", 1)
    for label, offset, fmt, value in [
        ("rela-type", 4, "<I", 1), ("rela-flags", 8, "<Q", 1),
        ("rela-address", 16, "<Q", 8), ("rela-offset", 24, "<Q", sections[6][4] - 8),
        ("rela-link", 40, "<I", 3), ("rela-info", 44, "<I", 2),
        ("rela-alignment", 48, "<Q", 16), ("rela-entry-size", 56, "<Q", 16),
    ]:
        field(label, table + 6 * 64 + offset, fmt, value)
    # Insert one complete relocation record and move the section table. The
    # section is structurally in bounds but the profile forbids any relocations.
    changed = bytearray(raw[:table] + bytes(24) + raw[table:])
    struct.pack_into("<Q", changed, 40, table + 24)
    struct.pack_into("<Q", changed, table + 24 + 6 * 64 + 32, 24)
    reject("nonempty-relocation-section", changed)
    field("writable-text", table + 64 + 8, "<Q", 7)
    field("executable-stack-note", table + 5 * 64 + 8, "<Q", 4)
    field("weak-export", public + 4, "<B", 0x22)
    field("undefined-export", public + 6, "<H", 0)
    field("non-function-export", public + 4, "<B", 0x11)
    field("nondefault-export-visibility", public + 5, "<B", 1)
    field("zero-size-export", public + 16, "<Q", 0)
    field("export-outside-text", public + 8, "<Q", sections[1][5])
    entry, entry_size = struct.unpack_from("<QQ", raw, public + 8)
    field("export-shifted-inside-text", public + 8, "<Q", entry - 1)
    field("export-truncated-inside-text", public + 16, "<Q", entry_size - 1)
    # Both fields still end at .text's end; the fixed wrapper width must hold.
    changed = bytearray(raw)
    struct.pack_into("<QQ", changed, public + 8, entry + 1, entry_size - 1)
    reject("export-shifted-with-tail-preserved", changed)
    wrapper = sections[1][4] + entry
    field("wrapper-wrong-first-argument-register", wrapper + 13, "<B", 0xF0)
    field("wrapper-wrong-return-suffix", wrapper + entry_size - 1, "<B", 0x90)
    # The pinned two-u64 wrapper's call displacement occupies bytes 46..49;
    # its target is relative to byte 50, not to the start of the instruction.
    for label, target in [
        ("wrapper-call-enters-wrapper", entry),
        ("wrapper-call-before-text", -1),
        ("wrapper-call-past-text", sections[1][5] + 1),
    ]:
        field(label, wrapper + 46, "<i", target - (entry + 50))
    field("wrong-export-name-offset", public, "<I", 0)
    field("non-null-symbol-zero", symbols, "<I", 1)
    changed = bytearray(raw)
    changed[sections[3][4] + 1] = ord("g")
    reject("wrong-export-name", changed)
    # Add a second global function entry, retaining valid in-bounds ELF offsets.
    insertion = symbols + sections[2][5]
    changed = bytearray(raw[:insertion] + raw[public:public + 24] + raw[insertion:])
    moved_table = table + 24
    struct.pack_into("<Q", changed, 40, moved_table)
    struct.pack_into("<Q", changed, moved_table + 2 * 64 + 32, sections[2][5] + 24)
    for index in range(3, 7):
        struct.pack_into("<Q", changed, moved_table + index * 64 + 24, sections[index][4] + 24)
    reject("extra-global-function-export", changed)
    return inventory


def verify(artifacts, module, borrowed_module=None):
    inputs = {}

    def read(path):
        path = path.resolve()
        raw = path.read_bytes()
        inputs[path] = raw
        return raw

    lock_bytes = read(ROOT / "toolchain.json")
    lock = json.loads(lock_bytes)
    if module not in lock["modules"]:
        raise AssertionError(f"module is not locked: {module}")
    if lock.get("entry_profiles", {}).get(module) != PROFILE:
        raise AssertionError(f"module does not have the supported scalar profile: {module}")
    driver = read(ROOT / "build.py")
    helper = read(ROOT / "cargo_build.rs")
    test_source = read(Path(__file__))
    report_bytes = read(artifacts / "build.json")
    report = json.loads(report_bytes)
    raw = read(artifacts / f"{module}.o")
    named = read(artifacts / f"{module}.namespaced.o")
    archive = read(artifacts / f"libcodex_hia_{module}.a")
    library = read(artifacts / f"{module}.so")
    named_library = read(artifacts / f"libcodex_hia_{module}.so")
    specification = importlib.util.spec_from_file_location("codex_hia_builder", ROOT / "build.py")
    builder = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(builder)
    observed = []

    def equal(label, actual, expected):
        if actual != expected:
            raise AssertionError(f"{label}: {actual!r} != {expected!r}")
        observed.append(label)

    equal("native-build-schema", report["schema"], "codex.hia.native-build.v1")
    equal("native-build-complete", report["status"], "built")
    equal("native-build-mode", report["build_mode"], "native-selfhost")
    equal("native-fixed-point", report["compiler_fixed_point"] is True, True)
    equal("locked-toolchain", report["toolchain"], lock)
    equal("locked-toolchain-bytes", report["toolchain_lock_sha256"], digest(lock_bytes))
    equal("current-build-driver", report["build_driver_sha256"], digest(driver))
    equal("current-cargo-helper", report["cargo_helper_sha256"], digest(helper))
    equal("complete-module-inventory", set(report["modules"]), set(lock["modules"]))
    for locked_module in lock["modules"]:
        source = read(ROOT / f"{locked_module}.hepta")
        equal(f"current-source-{locked_module}", report["modules"][locked_module]["source_sha256"], digest(source))
    generations = report["bootstrap_generations"]
    equal("three-bootstrap-generations", [row["case"] for row in generations], ["B1", "B2", "B3"])
    compiler_hash = report["compiler_sha256"]
    for row in generations:
        image = read(artifacts / "bootstrap" / f"{row['case']}.image.bin")
        equal(f"{row['case']}-recorded-fixed-point", row["produced_sha256"], compiler_hash)
        equal(f"{row['case']}-actual-fixed-point", digest(image), compiler_hash)

    row = report["modules"][module]
    equal("recorded-scalar-profile", row["entry_profile"], PROFILE)
    source = inputs[(ROOT / f"{module}.hepta").resolve()]
    # Derive only the declared header projection from the actual locked source.
    # The complete source and native compilation remain bound by their hashes.
    header = source.split(b"\n", 1)[0].decode("ascii").split(" ")
    if len(header) != 3:
        raise AssertionError("scalar source requires an exact three-field assembly header")
    tag, schema, source_module = header
    equal("source-assembly-tag", tag, "hia-asm.v1")
    compiled_source = builder.selfhost_object_source(source, {
        "schema": schema, "module": source_module,
    })
    equal("compiled-source-assembly-version", compiled_source.split(b"\n", 1)[0],
          f"hia-asm.v1 {schema} selfhost_elf".encode("ascii"))
    compilation = row["compilation"]
    equal("scalar-native-compilation", (
        compilation["case"], compilation["status"], compilation["abi_status"],
        compilation["source_unchanged"] is True, compilation["forbidden_compiler_modules_loaded"],
        compilation["format"], compilation["image_sha256"], compilation["artifact_sha256"],
    ), (module, "returned", 0, True, [], "flat-x86-64", compiler_hash, compiler_hash))
    equal("compiled-source-input", compilation["input_sha256"], digest(compiled_source))
    equal("compiled-source-observed", compilation["source_sha256"], digest(compiled_source))
    equal("compiled-source-length", compilation["input_bytes"], len(compiled_source))
    equal("produced-raw-object", compilation["produced_sha256"], digest(raw))
    equal("produced-raw-object-length", compilation["produced_bytes"], len(raw))

    check_object_source(builder, observed)
    check_profile(builder, lock, module, observed, borrowed_module)
    inventory = check_elf(builder, raw, observed)
    equal("recorded-raw-object-inventory", row["object_inventory"], inventory)
    equal("normalized-section-count", struct.unpack_from("<H", named, 60)[0], 6)
    original_text, named_text = builder.text_section(raw), builder.text_section(named)
    equal("normalized-machine-text", named_text, original_text)
    equal("recorded-object-normalization", row["object_normalization"], {
        "removed_section": ".rela.text", "removed_payload_bytes": 0,
        "text_unchanged": True, "imports_added": False,
        "source_object_sha256": digest(raw), "normalized_object_sha256": digest(named),
    })
    abi = row["codex_link_abi"]
    equal("namespaced-archive-contract", (
        abi["symbol"], abi["object"], abi["archive"], abi["archive_member"],
        abi["defined_symbols"], abi["undefined_symbols"],
    ), (f"codex_hia_{module}", f"{module}.namespaced.o", f"libcodex_hia_{module}.a",
        "hia.o", [f"codex_hia_{module}"], []))
    equal("namespaced-object-hash", abi["object_sha256"], digest(named))
    equal("namespaced-text-hash", abi["text_sha256"], digest(named_text))
    equal("archive-hash", abi["archive_sha256"], digest(archive))
    equal("archive-length", abi["archive_bytes"], len(archive))
    equal("archive-machine-object", builder.archive_member(archive), named)
    equal("raw-library-hash", row["library_sha256"], digest(library))
    equal("namespaced-library-hash", abi["library_sha256"], digest(named_library))
    for path, original in inputs.items():
        if path.read_bytes() != original:
            raise AssertionError(f"input changed while checking scalar admission: {path}")
    observed.append("inputs-unchanged")
    result = {
        "schema": "codex.hia.scalar-build-admission.v1", "status": "passed",
        "passed": True, "module": module, "source_schema": schema,
        "source_module": source_module, "skipped": 0,
        "checks": len(observed), "cases": observed, "entry_profile": PROFILE,
        "test_sha256": digest(test_source), "build_driver_sha256": digest(driver),
        "source_sha256": digest(source), "build_report_sha256": digest(report_bytes),
        "raw_object_sha256": digest(raw), "normalized_object_sha256": digest(named),
        "archive_sha256": digest(archive), "compiler_sha256": compiler_hash,
        "object_inventory": inventory, "whole_codex_rewritten": False,
        "qualification_scope": "entry-profile and scalar ELF admission; behavioral gates separate",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--module", default=DEFAULT_MODULE)
    parser.add_argument("--borrowed-module", help="Explicit locked borrowed fixture; default is the first borrowed module")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if re.fullmatch(r"[a-z0-9_]+", args.module) is None:
        parser.error("module must contain only lowercase letters, digits and underscores")
    artifacts = args.artifacts.resolve()
    destination = args.report.resolve() if args.report else None
    if destination is not None:
        source_tree = ROOT.parent
        if destination == source_tree or source_tree in destination.parents:
            parser.error("report must be outside the source tree")
        if destination == artifacts or artifacts in destination.parents:
            parser.error("report must be outside the native artifact directory")
    result = {
        "schema": "codex.hia.scalar-build-admission.v1", "status": "failed",
        "passed": False, "module": args.module, "skipped": 0,
        "qualification_scope": "entry-profile and scalar ELF admission; behavioral gates separate",
    }
    try:
        result = verify(artifacts, args.module, args.borrowed_module)
    except (AssertionError, AttributeError, ImportError, IndexError, KeyError,
            OSError, RuntimeError, TypeError, ValueError, struct.error) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        print(result["error"], file=sys.stderr)
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
