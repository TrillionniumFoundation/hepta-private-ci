"""Run the real Cargo helper against native builds and isolated input mutations."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def update_field(path, key, value):
    lines = path.read_text().splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith(key + "=")]
    if len(matches) != 1:
        raise AssertionError(f"expected one receipt field {key}")
    lines[matches[0]] = key + "=" + value
    path.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--rustc", default=shutil.which("rustc"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.rustc:
        parser.error("rustc is required; this test never skips the Rust helper")
    artifacts = args.artifacts.resolve()
    modules = json.loads((ROOT / "toolchain.json").read_bytes())["modules"]
    observed = []
    with tempfile.TemporaryDirectory(prefix="codex-hia-build-check-") as temporary:
        base = Path(temporary)
        fixture_hia = base / "source" / "hia"
        fixture_hia.mkdir(parents=True)
        manifest = base / "source" / "codex-rs" / "apply-patch"
        manifest.mkdir(parents=True)
        native = base / "artifacts"
        (native / "bootstrap").mkdir(parents=True)
        inputs = {}
        for name in ["build.py", "cargo_build.rs", "toolchain.json", *(f"{m}.hepta" for m in modules)]:
            inputs[fixture_hia / name] = (ROOT / name).read_bytes()
        for name in ["build.json", *(f"bootstrap/B{i}.image.bin" for i in (1, 2, 3)),
                     *(f"{m}.link" for m in modules), *(f"{m}.namespaced.o" for m in modules),
                     *(f"libcodex_hia_{m}.a" for m in modules)]:
            inputs[native / name] = (artifacts / name).read_bytes()
        for path, raw in inputs.items():
            path.write_bytes(raw)
        helper = fixture_hia / "cargo_build.rs"
        driver = base / "helper.rs"
        driver.write_text(
            'include!("source/hia/cargo_build.rs");\n'
            'fn main() {\n'
            '  let arg = std::env::args().nth(1).unwrap_or_default();\n'
            '  if arg == "--sha256" {\n'
            '    let mut input = Vec::new();\n'
            '    std::io::Read::read_to_end(&mut std::io::stdin(), &mut input)'
            '.unwrap_or_else(|e| panic!("{e}"));\n'
            '    println!("{}", hia_sha256(&input));\n'
            '  } else { link_native(&arg); }\n'
            '}\n'
        )
        executable = base / "helper"
        subprocess.run([args.rustc, "--edition=2024", "-O", str(driver), "-o", str(executable)],
                       check=True, capture_output=True, timeout=120)
        for length in (0, 1, 3, 55, 56, 63, 64, 65, 1000, 1_000_000):
            raw = bytes((i * 37 + 19) % 256 for i in range(length))
            result = subprocess.run([str(executable), "--sha256"], input=raw, capture_output=True,
                                    check=True, timeout=30).stdout.decode().strip()
            if result != digest(raw):
                raise AssertionError(f"SHA256 disagrees with hashlib at {length} bytes")
            observed.append(f"sha256-{length}")
        env = dict(os.environ)
        env.update({"CARGO_FEATURE_HIA_NATIVE": "1", "CARGO_MANIFEST_DIR": str(manifest),
                    "CODEX_HIA_NATIVE_LIB_DIR": str(native), "OUT_DIR": str(base / "out"),
                    "CARGO_CFG_TARGET_OS": "linux", "CARGO_CFG_TARGET_ARCH": "x86_64",
                    "CARGO_CFG_TARGET_ENV": "gnu", "CARGO_CFG_TARGET_POINTER_WIDTH": "64",
                    "CARGO_CFG_TARGET_ENDIAN": "little"})

        def run(label, module, accepted, overrides=None, remove=()):
            current = dict(env)
            current.update(overrides or {})
            for key in remove:
                current.pop(key, None)
            result = subprocess.run([str(executable), module], env=current, capture_output=True,
                                    text=True, timeout=30)
            if (result.returncode == 0) != accepted:
                raise AssertionError(f"{label}: exit {result.returncode}: {result.stderr}")
            observed.append(label)

        run("feature-disabled-needs-no-files-or-target", modules[0], True,
            {"CARGO_MANIFEST_DIR": "/nonexistent", "CARGO_CFG_TARGET_OS": "windows"},
            ("CARGO_FEATURE_HIA_NATIVE", "CODEX_HIA_NATIVE_LIB_DIR", "OUT_DIR"))
        for module in modules:
            run(f"accepted-{module}", module, True)
            staged = base / "out" / f"libcodex_hia_{module}.a"
            if staged.read_bytes() != inputs[native / staged.name]:
                raise AssertionError("Cargo staging changed archive bytes")
        module = modules[0]
        receipt = native / f"{module}.link"
        for path in [fixture_hia / "build.py", helper, fixture_hia / "toolchain.json",
                     *(fixture_hia / f"{m}.hepta" for m in modules), native / "build.json",
                     native / f"{module}.namespaced.o", native / f"libcodex_hia_{module}.a",
                     *(native / "bootstrap" / f"B{i}.image.bin" for i in (1, 2, 3))]:
            original = path.read_bytes()
            path.write_bytes(original + b"\n")
            selected = path.stem if path.suffix == ".hepta" else module
            run(f"changed-bytes-{path.name}", selected, False)
            path.write_bytes(original)
        for key, value in [("mode", "seed-only"), ("symbol", "f0"), ("object", "../other.o"),
                           ("archive", "../other.a"), ("revision", "0" * 40)]:
            update_field(receipt, key, value)
            run(f"wrong-receipt-{key}", module, False)
            receipt.write_bytes(inputs[receipt])
        for key, value in [("status", "failed"), ("build_mode", "seed-only"), ("compiler_fixed_point", False)]:
            report_path = native / "build.json"
            report = json.loads(inputs[report_path])
            report[key] = value
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            update_field(receipt, "build_report_sha256", digest(report_path.read_bytes()))
            run(f"invalid-build-state-{key}", module, False)
            report_path.write_bytes(inputs[report_path])
            receipt.write_bytes(inputs[receipt])
        for raw in [inputs[receipt] + b"extra=value\n", inputs[receipt].replace(b"\n", b"\r\n"),
                    inputs[receipt].replace(b"module=" + module.encode(), b"other=" + module.encode())]:
            receipt.write_bytes(raw)
            run(f"noncanonical-receipt-{len(observed)}", module, False)
        receipt.write_bytes(inputs[receipt])
        run("missing-libdir", module, False, remove=("CODEX_HIA_NATIVE_LIB_DIR",))
        for key, value in [("CARGO_CFG_TARGET_OS", "windows"), ("CARGO_CFG_TARGET_ARCH", "aarch64"),
                           ("CARGO_CFG_TARGET_ENV", "musl"), ("CARGO_CFG_TARGET_POINTER_WIDTH", "32")]:
            run(f"unsupported-{key}", module, False, {key: value})
        obj_path = native / f"{module}.namespaced.o"
        archive_path = native / f"libcodex_hia_{module}.a"
        original_object = inputs[obj_path]
        shoff = struct.unpack_from("<Q", original_object, 40)[0]
        shnum = struct.unpack_from("<H", original_object, 60)[0]
        entries = []
        for index in range(shnum):
            section = struct.unpack_from("<IIQQQQIIQQ", original_object, shoff + index * 64)
            if section[1] == 2:
                entries.extend(range(section[4], section[4] + section[5], 24))
        public = next(at for at in entries if original_object[at + 4] >> 4 == 1)
        for label, offset, changed in [("weak-symbol", public + 4, b"\x22"),
                                       ("undefined-symbol", public + 6, b"\0\0")]:
            altered = bytearray(original_object)
            altered[offset:offset + len(changed)] = changed
            obj_path.write_bytes(altered)
            archive_path.write_bytes(inputs[archive_path].replace(original_object, altered))
            update_field(receipt, "object_sha256", digest(altered))
            update_field(receipt, "archive_sha256", digest(archive_path.read_bytes()))
            run(f"reject-rehashed-{label}", module, False)
            obj_path.write_bytes(original_object)
            archive_path.write_bytes(inputs[archive_path])
            receipt.write_bytes(inputs[receipt])
        specification = importlib.util.spec_from_file_location("codex_hia_builder", ROOT / "build.py")
        builder = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(builder)
        if builder.archive_member(inputs[archive_path]) != original_object:
            raise AssertionError("Python archive inspection disagrees with built member")
        raw = inputs[archive_path]
        at = 8
        while raw[at:at + 16].rstrip() != b"hia.o/":
            length = int(raw[at + 48:at + 58])
            at += 60 + length + length % 2
        duplicate = raw + raw[at:]
        archive_path.write_bytes(duplicate)
        update_field(receipt, "archive_sha256", digest(duplicate))
        run("duplicate-rehashed-archive-member", module, False)
        try:
            builder.archive_member(duplicate)
        except ValueError:
            observed.append("python-duplicate-archive-rejected")
        else:
            raise AssertionError("Python archive inspector accepted a duplicate member")
    result = {"schema": "codex.hia.build-receipt-test.v1", "status": "passed",
              "checks": len(observed), "cases": observed,
              "helper_sha256": digest((ROOT / "cargo_build.rs").read_bytes()),
              "build_report_sha256": digest((artifacts / "build.json").read_bytes()),
              "whole_codex_rewritten": False}
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
