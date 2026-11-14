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
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


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

    record = {
        "schema": "codex.hia.native-build.v1", "status": "building",
        "toolchain": lock, "toolchain_lock_sha256": hashlib.sha256(lock_bytes).hexdigest(),
        "build_driver_sha256": hashlib.sha256(driver_bytes).hexdigest(),
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
                named_library = output / f"lib{public_symbol}.so"
                named_link_command = [
                    "ld", "-m", "elf_x86_64", "-shared", "-z", "defs", "-z",
                    "noexecstack", "-z", "relro", "-z", "now", "--build-id=none",
                    str(named_obj), "-o", str(named_library),
                ]
                subprocess.run(named_link_command, check=True, capture_output=True, timeout=60)
                row["codex_link_abi"] = {
                    "symbol": public_symbol, "library": named_library.name,
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
        if lock_path.read_bytes() != lock_bytes or driver_path.read_bytes() != driver_bytes:
            raise RuntimeError("build driver or toolchain lock changed during build")
        if any(path.read_bytes() != captured for path, captured in source_inputs.items()):
            raise RuntimeError("HIA component source changed during build")
        record["status"] = "built"
    except BaseException as error:
        record["status"] = "failed"
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        report.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"status": record["status"], "build_mode": record["build_mode"],
                      "report": str(report), "modules": list(record["modules"])}))


if __name__ == "__main__":
    main()
