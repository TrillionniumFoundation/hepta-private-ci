"""Observe native filesystem behavior using owned disposable fixtures."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import socket
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = {
        "schema": "codex.macos.filesystem-observation.v1",
        "platform": platform.platform(),
        "machine": platform.machine(),
        "temp_dir": tempfile.gettempdir(),
        "canonical_temp_dir": str(Path(tempfile.gettempdir()).resolve(strict=True)),
        "observations": [],
        "owner_qualification_passed": False,
    }

    def observe(name, action):
        try:
            result = action()
            report["observations"].append({"name": name, "ok": True, "result": result})
        except OSError as error:
            report["observations"].append(
                {"name": name, "ok": False, "errno": error.errno, "error": str(error)}
            )

    def bind_unix(path):
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(path)

    with tempfile.TemporaryDirectory(prefix="hmp-") as temporary:
        root = Path(temporary).resolve(strict=True)
        source = root / "source"
        source.write_bytes(b"immutable release fixture\n")
        source.chmod(0o555)
        staging = root / "staging"
        staging.mkdir(mode=0o700)
        binary_directory = staging / "bin"
        binary_directory.mkdir(mode=0o700)
        copied = binary_directory / "program"
        with source.open("rb") as input_file, copied.open("xb") as output_file:
            output_file.write(input_file.read())
            output_file.flush()
            copied.chmod(0o555)
            observe("fsync-writer-after-chmod-555", lambda: os.fsync(output_file.fileno()))
            if hasattr(fcntl, "F_FULLFSYNC"):
                observe("fullfsync-writer-after-chmod-555", lambda: fcntl.fcntl(output_file.fileno(), fcntl.F_FULLFSYNC))
        binary_directory.chmod(0o555)
        for label, directory in [("bin-555", binary_directory), ("staging-700", staging)]:
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                observe("fsync-directory-" + label, lambda: os.fsync(descriptor))
                if hasattr(fcntl, "F_FULLFSYNC"):
                    observe("fullfsync-directory-" + label, lambda: fcntl.fcntl(descriptor, fcntl.F_FULLFSYNC))
            finally:
                os.close(descriptor)
        staging.chmod(0o555)
        final = root / "final"
        observe("rename-immutable-directory-within-parent", lambda: os.rename(staging, final))
        current = final if final.exists() else staging
        observe("read-immutable-published-program", lambda: (current / "bin/program").read_text())
        for length in [90, 103, 104, 107, 108]:
            prefix = str(root) + "/"
            if len(os.fsencode(prefix)) >= length:
                continue
            path = prefix + "s" * (length - len(os.fsencode(prefix)))
            observe("unix-socket-path-bytes-" + str(length), lambda: bind_unix(path))
        # Restore only fixture nodes created above for portable cleanup.
        current.chmod(0o700)
        (current / "bin").chmod(0o700)
        (current / "bin/program").chmod(0o600)
        source.chmod(0o600)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
