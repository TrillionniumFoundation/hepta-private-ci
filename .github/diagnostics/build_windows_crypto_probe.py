"""Build a CRT-free observation child and verify its actual PE import table."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def imported_libraries(data):
    if data[:2] != b"MZ":
        raise ValueError("probe is not a PE executable")
    pe = struct.unpack_from("<I", data, 60)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature")
    machine, count = struct.unpack_from("<HH", data, pe + 4)
    if machine != 0x8664:
        raise ValueError("this diagnostic requires the native AMD64 owner runner")
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from("<H", data, optional)[0] != 0x20B:
        raise ValueError("probe is not PE32+")
    sections = []
    for index in range(count):
        location = optional + optional_size + 40 * index
        virtual_size, rva, raw_size, raw = struct.unpack_from(
            "<IIII", data, location + 8
        )
        sections.append((rva, virtual_size, raw_size, raw))

    def file_offset(address, size):
        for rva, virtual_size, raw_size, raw in sections:
            offset = address - rva
            if 0 <= offset and offset + size <= min(virtual_size, raw_size):
                result = raw + offset
                if result + size <= len(data):
                    return result
        raise ValueError("PE import range is outside initialized section data")

    imports, import_size = struct.unpack_from("<II", data, optional + 112 + 8)
    if not imports or not 20 <= import_size <= 65536:
        raise ValueError("probe import directory is missing or unbounded")
    libraries = []
    for index in range(min(import_size // 20, 64)):
        row = struct.unpack_from("<IIIII", data, file_offset(imports + index * 20, 20))
        if not any(row):
            return sorted(libraries)
        name = row[3]
        raw_name = bytearray()
        for offset in range(256):
            value = data[file_offset(name + offset, 1)]
            if value == 0:
                break
            raw_name.append(value)
        else:
            raise ValueError("unbounded PE import name")
        libraries.append(raw_name.decode("ascii").lower())
    raise ValueError("unterminated PE import directory")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", default="x86_64-pc-windows-msvc")
    parser.add_argument("--rustc", default="rustc")
    parser.add_argument("--linker")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        args.rustc,
        "--edition=2024",
        "--crate-name=windows_crypto_probe",
        "--target",
        args.target,
        "-C",
        "panic=abort",
        "-C",
        "opt-level=2",
        "-C",
        "lto=fat",
        "-C",
        "codegen-units=1",
        str(args.source),
        "-o",
        str(args.output),
    ]
    if args.linker:
        command += ["-C", f"linker={args.linker}"]
    if args.target.endswith("-msvc"):
        for flag in [
            "/ENTRY:mainCRTStartup",
            "/SUBSYSTEM:CONSOLE",
            "/NODEFAULTLIB",
            "/DEFAULTLIB:kernel32.lib",
        ]:
            command += ["-C", f"link-arg={flag}"]
    elif args.target == "x86_64-pc-windows-gnu":
        command += [
            "-C",
            "link-self-contained=no",
            "-C",
            "link-arg=-nostdlib",
            "-C",
            "link-arg=-Wl,--entry,mainCRTStartup",
        ]
    else:
        raise ValueError("unsupported diagnostic target")
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(
            f"probe compilation failed ({result.returncode}):\n{result.stdout}\n{result.stderr}"
        )
    data = args.output.read_bytes()
    libraries = imported_libraries(data)
    if libraries != ["kernel32.dll"]:
        raise ValueError(
            f"probe unexpectedly imports a runtime or provider: {libraries}"
        )
    print(
        json.dumps(
            {
                "target": args.target,
                "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
                "observer_sha256": hashlib.sha256(
                    args.source.with_name("windows_crypto_observe.rs").read_bytes()
                ).hexdigest(),
                "executable_sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "imports": libraries,
                "compiler_stdout": result.stdout,
                "compiler_stderr": result.stderr,
            }
        )
    )


if __name__ == "__main__":
    main()
