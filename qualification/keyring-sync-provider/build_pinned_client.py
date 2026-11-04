"""Build and test exactly the pinned Bazel D-Bus client inputs with host GCC."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    inputs = repo / "third_party/dbus"
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = {"status": "RUNNING", "commands": []}
    try:
        url = "https://dbus.freedesktop.org/releases/dbus/dbus-1.16.2.tar.xz"
        archive = urllib.request.urlopen(url, timeout=60).read(2_000_000)
        digest = hashlib.sha256(archive).hexdigest()
        assert (
            digest == "0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2"
        )
        receipt["archive"] = {"url": url, "bytes": len(archive), "sha256": digest}
        receipt["inputs"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs.iterdir()
            if p.is_file()
        }
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:xz") as members:
            for member in members:
                path = Path(member.name)
                assert path.parts[0] == "dbus-1.16.2" and ".." not in path.parts
                if member.isdir():
                    continue
                assert member.isfile()
                target = args.output / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(members.extractfile(member).read())
        src = args.output / "dbus-1.16.2"
        shutil.copyfile(inputs / "config.h", src / "config.h")
        shutil.copyfile(inputs / "dbus-arch-deps.h", src / "dbus/dbus-arch-deps.h")

        def run(command, cwd=None):
            process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
            result = {
                "command": command,
                "exit": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
            receipt["commands"].append(result)
            assert process.returncode == 0, result
            return result

        for check in [["--dry-run"], []]:
            run(
                ["patch", *check, "-p1", "-i", str(inputs / "close_range.patch")],
                cwd=src,
            )
        text = (
            (inputs / "dbus.BUILD.bazel")
            .read_text()
            .split("srcs = [", 1)[1]
            .split("]", 1)[0]
        )
        sources = [
            line.strip().rstrip(",").strip('"')
            for line in text.splitlines()
            if '"' in line
        ]
        assert len(sources) == 47 and len(set(sources)) == 47
        objects = args.output / "objects"
        objects.mkdir()
        common = [
            "gcc",
            "-std=gnu11",
            "-O2",
            "-fno-strict-aliasing",
            "-DDBUS_COMPILATION",
            f"-I{src}",
            "-pthread",
        ]

        def compile_one(source):
            output = objects / (Path(source).stem + ".o")
            run([*common, "-c", str(src / source), "-o", str(output)])
            return str(output)

        with ThreadPoolExecutor(max_workers=2) as workers:
            object_paths = list(workers.map(compile_one, sources))
        lib = args.output / "lib"
        (lib / "pkgconfig").mkdir(parents=True)
        static = lib / "libdbus-1.a"
        run(["ar", "rcs", str(static), *object_paths])
        receipt["static_sha256"] = hashlib.sha256(static.read_bytes()).hexdigest()
        (lib / "pkgconfig/dbus-1.pc").write_text(
            f"Name: dbus\nDescription: pinned D-Bus client qualification\nVersion: 1.16.2\nLibs: -L{lib} -ldbus-1 -pthread\nCflags: -I{src}\n"
        )
        identity = args.output / "native-identity"
        run(
            [
                *common,
                str(inputs / "native_identity_test.c"),
                str(static),
                "-o",
                str(identity),
            ]
        )
        receipt["identity_sha256"] = hashlib.sha256(identity.read_bytes()).hexdigest()
        run([str(identity)])
        assert receipt["inputs"] == {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in inputs.iterdir()
            if p.is_file()
        }
        receipt["status"] = "PASS"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
