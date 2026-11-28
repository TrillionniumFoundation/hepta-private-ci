"""Build the strict RFC3339 parsing component with the existing pinned native HIA compiler.

This separate component gate does not extend the 38 production modules or claim
that the remaining Chrono callers have been migrated. B0 is an explicit Python
bootstrap boundary; B1, B2, B3 and the parse object are native HIA executions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def binding(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def identity(root):
    require(not git(root, "status", "--porcelain", "--untracked-files=all"), "source checkout is dirty")
    return {"head": git(root, "rev-parse", "HEAD"), "tree": git(root, "rev-parse", "HEAD^{tree}")}


def build(args, report):
    require(sys.flags.optimize == 0, "assertions may not be disabled")
    require(platform.system() == "Linux" and platform.machine().lower() in ("x86_64", "amd64"),
            "the pinned component targets Linux x86-64")
    report["producer"] = identity(ROOT)
    report["hepta"] = identity(args.hepta_root)
    contract = json.loads((ROOT / "hia/datetime_parse_buffer_contract.json").read_bytes())
    lock = json.loads((ROOT / "hia/toolchain.json").read_bytes())
    require(report["hepta"]["head"] == lock["revision"] == contract["compiler"]["revision"],
            "compiler checkout differs from the existing production pin")
    source_path = ROOT / "hia/datetime_parse.hepta"
    report["inputs"] = [binding(path) for path in (source_path, Path(__file__).resolve(),
                        ROOT / "hia/datetime_parse_buffer_contract.json", ROOT / "hia/toolchain.json")]
    require(report["inputs"][0]["sha256"] == contract["source_sha256"], "parse source identity differs")
    sys.path.insert(0, str(args.hepta_root))
    from hepta.hia_agent_assembly import assemble_program
    from tools.qualify_hia_selfhost import build_seed, compile_stage, inspect_selfhost_object
    source = source_path.read_bytes()
    checked = assemble_program(source)
    require(checked.sha256 == contract["core_sha256"], "checked Core identity differs")
    report["core_sha256"] = checked.sha256
    own = (args.hepta_root / "examples/hia_bootstrap/selfhost.hepta").read_bytes()
    compiler, seed = build_seed(args.output, own)
    report["bootstrap_seed"] = seed
    report["native_generations"] = []
    for generation in ("B1", "B2", "B3"):
        compiler, receipt = compile_stage(
            args.output, generation, compiler, own,
            image_format="seed-shared" if generation == "B1" else "flat-x86-64",
            workspace_fill=0x5A if generation == "B3" else 0,
        )
        require(receipt["produced_sha256"] == contract["compiler"]["native_sha256"],
                "native compiler generation differs from its fixed point")
        report["native_generations"].append(receipt)
    header, body = source.split(b"\n", 1)
    require(header == b"hia-asm.v1 hepta.hia.program.v9 codex_datetime_parse", "unexpected source header")
    object_source = b"hia-asm.v1 hepta.hia.program.v9 selfhost_elf\n" + body
    obj, receipt = compile_stage(args.output, "datetime-parse", compiler, object_source,
                                 output_extension=".o")
    report["compilation"] = receipt
    report["object"] = inspect_selfhost_object(obj.read_bytes())
    require(not report["object"]["undefined_symbols"] and not report["object"]["external_relocations"],
            "parse object must not call a host implementation")
    linker = Path(shutil.which("ld")).resolve(strict=True)
    library = args.output / "datetime_parse.so"
    command = [str(linker), "-m", "elf_x86_64", "-shared", "-z", "defs", "-z", "noexecstack",
               "-z", "relro", "-z", "now", "--build-id=none", str(obj), "-o", str(library)]
    result = subprocess.run(command, capture_output=True, timeout=60)
    report["linker"] = binding(linker)
    report["link"] = {"argv": command, "returncode": result.returncode,
                      "stdout": result.stdout.decode(), "stderr": result.stderr.decode(),
                      "role": "link the HIA-emitted object only"}
    require(result.returncode == 0, "native object linking failed")
    report["library"] = binding(library)
    require(identity(ROOT) == report["producer"] and identity(args.hepta_root) == report["hepta"],
            "source identity changed during the build")
    require(all(binding(Path(row["path"])) == row for row in report["inputs"]), "a build input changed")
    report["passed"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.hepta_root = args.hepta_root.resolve(strict=True)
    args.output = args.output.resolve()
    require(not args.output.is_relative_to(ROOT) and not args.output.is_relative_to(args.hepta_root),
            "build output must be outside both source checkouts")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "codex.hia.datetime-parse-build.v1", "passed": False,
              "started_unix": time.time(), "target": "x86_64-unknown-linux-gnu",
              "scope": "strict RFC3339 value and error-kind component; no production caller or whole-product qualification",
              "bootstrap_boundary": "Python B0; native HIA B1/B2/B3 and component compilation",
              "production_module_count_changed": False, "legacy_retirement": False}
    try:
        build(args, report)
    except BaseException:
        report["exception"] = traceback.format_exc()
        raise
    finally:
        report["finished_unix"] = time.time()
        path = args.output / "build.json"
        path.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"passed": report["passed"], "report": binding(path)}), flush=True)


if __name__ == "__main__":
    main()
