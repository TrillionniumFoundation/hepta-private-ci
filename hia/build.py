"""Build the checked HIA components with a pinned compiler checkout.

The default builds a Python-created B0 seed, then three native HIA compiler
generations. B3 compiles each component to ELF; GNU ld only links the object.
--seed-only is an explicitly labelled development path, never a selfhost claim.
Build outputs belong outside the source tree and are not committed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import struct
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
LINK_FIELDS = (
    "module", "target", "mode", "revision", "symbol", "object", "archive",
    "archive_member", "source_sha256", "toolchain_lock_sha256",
    "build_driver_sha256", "cargo_helper_sha256", "object_sha256",
    "text_sha256", "archive_sha256", "compiler_sha256", "build_report_sha256",
)


def text_section(data):
    """Read the admitted ELF object's text, without changing machine bytes."""
    table = struct.unpack_from("<Q", data, 40)[0]
    count, names_index = struct.unpack_from("<HH", data, 60)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, table + i * 64) for i in range(count)]
    names = sections[names_index]
    strings = data[names[4]:names[4] + names[5]]
    matches = [row for row in sections if strings[row[0]:].split(b"\0", 1)[0] == b".text"]
    if len(matches) != 1:
        raise ValueError("ELF must contain exactly one .text section")
    row = matches[0]
    return data[row[4]:row[4] + row[5]]


def archive_member(data):
    """Accept one ordinary hia.o member plus the optional GNU symbol index."""
    if not data.startswith(b"!<arch>\n"):
        raise ValueError("not an ordinary static archive")
    at, members, indexes = 8, [], 0
    while at < len(data):
        header = data[at:at + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise ValueError("invalid archive header")
        name = header[:16].decode("ascii").rstrip(" ")
        size_text = header[48:58].decode("ascii").strip(" ")
        if not size_text or not size_text.isascii() or not size_text.isdigit():
            raise ValueError("invalid archive member length")
        size, at = int(size_text), at + 60
        end = at + size
        if end > len(data) or size % 2 and data[end:end + 1] != b"\n":
            raise ValueError("truncated archive member")
        if name == "/":
            indexes += 1
        elif name == "hia.o/":
            members.append(data[at:end])
        else:
            raise ValueError("unexpected archive member")
        at = end + size % 2
    if at != len(data) or len(members) != 1 or indexes > 1:
        raise ValueError("archive inventory differs from one HIA object")
    return members[0]


def write_link_receipt(output, name, row, record, report_hash):
    abi = row["codex_link_abi"]
    fields = {
        "module": name, "target": record["toolchain"]["target"],
        "mode": "native-selfhost", "revision": record["toolchain"]["revision"],
        "symbol": abi["symbol"], "object": abi["object"], "archive": abi["archive"],
        "archive_member": "hia.o", "source_sha256": row["source_sha256"],
        "toolchain_lock_sha256": record["toolchain_lock_sha256"],
        "build_driver_sha256": record["build_driver_sha256"],
        "cargo_helper_sha256": record["cargo_helper_sha256"],
        "object_sha256": abi["object_sha256"], "text_sha256": abi["text_sha256"],
        "archive_sha256": abi["archive_sha256"],
        "compiler_sha256": record["compiler_sha256"], "build_report_sha256": report_hash,
    }
    raw = "codex.hia.static-link.v1\n" + "".join(f"{key}={fields[key]}\n" for key in LINK_FIELDS)
    (output / f"{name}.link").write_text(raw, encoding="ascii")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-only", action="store_true")
    args = parser.parse_args()
    lock_path = ROOT / "toolchain.json"
    lock_bytes = lock_path.read_bytes()
    driver_path = Path(__file__)
    driver_bytes = driver_path.read_bytes()
    helper_path = ROOT / "cargo_build.rs"
    helper_bytes = helper_path.read_bytes()
    lock = json.loads(lock_bytes)
    hepta = args.hepta_root.resolve()
    output = args.output.resolve()
    if platform.system() != "Linux" or platform.machine().lower() not in ("x86_64", "amd64"):
        parser.error("the pinned native compiler currently targets Linux x86-64")
    if git(hepta, "rev-parse", "HEAD") != lock["revision"]:
        parser.error("Hepta revision differs from hia/toolchain.json")
    if git(hepta, "status", "--porcelain", "--untracked-files=normal"):
        parser.error("the Hepta checkout must be clean, including untracked files")
    if output == ROOT.parent or ROOT.parent in output.parents:
        parser.error("build output must be outside the source checkout; use a temporary directory")
    output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(hepta))
    from hepta.hia_agent_assembly import assemble_program
    from hepta.hia_program_native import build_program_machine
    from tools.qualify_hia_selfhost import build_seed, compile_stage, inspect_selfhost_object
    from hepta.object_symbols import inspect_object_symbols

    record = {
        "schema": "codex.hia.native-build.v1", "status": "building",
        "toolchain": lock, "toolchain_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "build_driver_sha256": hashlib.sha256(driver_bytes).hexdigest(),
        "cargo_helper_sha256": hashlib.sha256(helper_bytes).hexdigest(),
        "build_mode": "seed-only" if args.seed_only else "native-selfhost",
        "bootstrap_generations": [], "modules": {},
        "whole_codex_rewritten": False, "production_dispatch_migrated": False,
    }
    report = output / "build.json"
    report.write_text(json.dumps(record, indent=2) + "\n")
    try:
        compiler = None
        if not args.seed_only:
            bootstrap = output / "bootstrap"
            bootstrap.mkdir()
            own_source = (hepta / "examples/hia_bootstrap/selfhost.hepta").read_bytes()
            compiler, seed_receipt = build_seed(bootstrap, own_source)
            record["bootstrap_seed"] = seed_receipt
            for generation in ("B1", "B2", "B3"):
                compiler, receipt = compile_stage(
                    bootstrap, generation, compiler, own_source,
                    image_format="seed-shared" if generation == "B1" else "flat-x86-64",
                    workspace_fill=0x5A if generation == "B3" else 0,
                )
                record["bootstrap_generations"].append(receipt)
            hashes = {row["produced_sha256"] for row in record["bootstrap_generations"]}
            if len(hashes) != 1:
                raise RuntimeError("native compiler generations did not reproduce identical bytes")
            record["compiler_fixed_point"] = True
            record["compiler_sha256"] = hashes.pop()
            record["compiler_qualification_scope"] = "three generation rebuild; component differential tests separate"
        source_inputs = {}
        for name in lock["modules"]:
            source_path = ROOT / f"{name}.hepta"
            source = source_path.read_bytes()
            source_inputs[source_path] = source
            checked = assemble_program(source)
            library = output / f"{name}.so"
            row = {"source_sha256": hashlib.sha256(source).hexdigest(), "core_sha256": checked.sha256}
            if compiler is None:
                row["build"] = build_program_machine(
                    checked, library, linker="ld",
                    foreign_buffer_exports=(("f0", lock["borrowed_buffer_capacity"]),),
                )
            else:
                header, remainder = source.split(b"\n", 1)
                if not header.startswith(b"hia-asm.v1 hepta.hia.program.v8 "):
                    raise ValueError("unexpected HIA assembly header")
                object_source = b"hia-asm.v1 hepta.hia.program.v8 selfhost_elf\n" + remainder
                obj, receipt = compile_stage(output, name, compiler, object_source,
                                             output_extension=".o")
                row["compilation"] = receipt
                row["object_inventory"] = inspect_selfhost_object(obj.read_bytes())
                command = ["ld", "-m", "elf_x86_64", "-shared", "-z", "defs", "-z", "noexecstack",
                           "-z", "relro", "-z", "now", "--build-id=none", str(obj), "-o", str(library)]
                subprocess.run(command, check=True, capture_output=True, timeout=60)
                row["link_command"] = command
                row["linker_role"] = "links HIA-emitted object; no C/Rust code generation"
                # Each HIA component exports f0. Rename the generated ELF entry
                # for simultaneous linkage; all algorithm code remains HIA.
                public_symbol = f"codex_hia_{name}"
                named_obj = output / f"{name}.namespaced.o"
                objcopy_command = ["objcopy", f"--redefine-sym=f0={public_symbol}",
                                   str(obj), str(named_obj)]
                subprocess.run(objcopy_command, check=True, capture_output=True, timeout=60)
                original_bytes, named_bytes = obj.read_bytes(), named_obj.read_bytes()
                symbols = inspect_object_symbols(named_bytes, "ELF64", 62)
                if symbols != {"defined": frozenset({public_symbol}), "undefined": frozenset()}:
                    raise ValueError("namespaced object has unexpected exports or imports")
                original_text, named_text = text_section(original_bytes), text_section(named_bytes)
                if original_text != named_text:
                    raise ValueError("ELF symbol renaming changed HIA machine code")
                archive = output / f"lib{public_symbol}.a"
                with tempfile.TemporaryDirectory(prefix=".hia-archive-", dir=output) as temporary:
                    member = Path(temporary) / "hia.o"
                    member.write_bytes(named_bytes)
                    subprocess.run(["ar", "crsD", str(archive), str(member)], check=True,
                                   capture_output=True, timeout=60)
                archive_bytes = archive.read_bytes()
                if archive_member(archive_bytes) != named_bytes:
                    raise ValueError("archive member differs from the HIA object")
                named_library = output / f"lib{public_symbol}.so"
                named_link_command = [
                    "ld", "-m", "elf_x86_64", "-shared", "-z", "defs", "-z",
                    "noexecstack", "-z", "relro", "-z", "now", "--build-id=none",
                    str(named_obj), "-o", str(named_library),
                ]
                subprocess.run(named_link_command, check=True, capture_output=True, timeout=60)
                row["codex_link_abi"] = {
                    "symbol": public_symbol, "library": named_library.name,
                    "object": named_obj.name, "archive": archive.name,
                    "archive_member": "hia.o", "archive_bytes": len(archive_bytes),
                    "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
                    "text_sha256": hashlib.sha256(named_text).hexdigest(),
                    "defined_symbols": sorted(symbols["defined"]), "undefined_symbols": [],
                    "object_sha256": digest(named_obj),
                    "library_sha256": digest(named_library),
                    "objcopy_command": objcopy_command,
                    "link_command": named_link_command,
                    "scope": "ELF namespaced symbol; HIA-compiled machine implementation",
                }
            row["library_sha256"] = digest(library)
            row["library_bytes"] = library.stat().st_size
            row["build_status"] = "built_not_yet_behaviorally_verified"
            record["modules"][name] = row
        if git(hepta, "rev-parse", "HEAD") != lock["revision"] or git(hepta, "status", "--porcelain"):
            raise RuntimeError("Hepta checkout changed during build")
        if (lock_path.read_bytes() != lock_bytes or driver_path.read_bytes() != driver_bytes
                or helper_path.read_bytes() != helper_bytes):
            raise RuntimeError("build driver, Cargo helper or toolchain lock changed during build")
        if any(path.read_bytes() != captured for path, captured in source_inputs.items()):
            raise RuntimeError("HIA component source changed during build")
        record["status"] = "built"
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report.write_text(json.dumps(record, indent=2) + "\n")
    if not args.seed_only:
        report_hash = digest(report)
        for name, row in record["modules"].items():
            write_link_receipt(output, name, row, record, report_hash)
    print(json.dumps({"status": record["status"], "build_mode": record["build_mode"],
                      "report": str(report), "modules": list(record["modules"])}))


if __name__ == "__main__":
    main()
