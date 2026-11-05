#!/usr/bin/env python3
"""Verify the cold CI Python environment and retain its exact installed bytes.

These before/after snapshots detect observed drift. They do not provide a held
immutable execution namespace or attest which files a later worker maps.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import sys
import sysconfig

LOCK_SHA256 = "178b2fe89a7bf58f2d127b195d82e4fa9b5c19d93cb3526d8789edf3df901017"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def managed_files(prefix, stdlib):
    paths = {str(path) for path in prefix.rglob("*") if path.is_file()}
    for path in stdlib.rglob("*"):
        if "site-packages" not in path.relative_to(stdlib).parts and path.is_file():
            paths.add(str(path))
    return sorted(paths)


def capture(lock, installation):
    require(
        sys.version_info[:2] == (3, 12) and sys.prefix != sys.base_prefix,
        "a private CPython 3.12 virtual environment is required",
    )
    require(
        sys.flags.isolated == 1 and sys.flags.no_user_site == 1,
        "snapshot entry must use Python -I",
    )
    require(digest(lock) == LOCK_SHA256, "original CPU requirements bytes changed")
    lock_raw = lock.read_text()
    expected = {
        normalized(name): version
        for name, version in re.findall(
            r"^([A-Za-z0-9_-]+)==([^\s]+)", lock_raw, re.MULTILINE
        )
    }
    expected["torch"] = "2.9.1+cpu"
    allowed = set(re.findall(r"--hash=sha256:([0-9a-f]{64})", lock_raw))
    report = json.loads(installation.read_bytes())
    wheels = {}
    for row in report["install"]:
        name = normalized(row["metadata"]["name"])
        value = row["download_info"]["archive_info"]["hashes"]["sha256"]
        require(
            value in allowed and name not in wheels,
            "installed wheel is not uniquely locked",
        )
        require(
            row["download_info"]["url"].split("?")[0].endswith(".whl"),
            "wheel-only installation",
        )
        wheels[name] = dict(version=row["metadata"]["version"], sha256=value)
    require(
        {name: item["version"] for name, item in wheels.items()} == expected,
        "installed wheels differ from the complete original requirements",
    )
    prefix = Path(sys.prefix).resolve()
    files, distributions = {}, {}
    for distribution in importlib.metadata.distributions():
        name = normalized(distribution.metadata["Name"])
        require(name not in distributions, "ambiguous installed distribution")
        distributions[name] = distribution.version
        require(distribution.files is not None, "installed distribution lacks RECORD")
        for item in distribution.files:
            path = Path(distribution.locate_file(item)).resolve(strict=True)
            require(
                path.is_relative_to(prefix) and path.is_file(),
                "distribution escapes private environment",
            )
            actual = digest(path)
            if item.hash is not None:
                require(
                    item.hash.mode == "sha256"
                    and item.hash.value
                    == base64.urlsafe_b64encode(bytes.fromhex(actual))
                    .decode()
                    .rstrip("="),
                    "installed RECORD digest mismatch: " + str(item),
                )
            files[str(path)] = actual
    require(
        {name: version for name, version in distributions.items() if name != "pip"}
        == expected,
        "ambient or missing distributions",
    )
    require((prefix / "pyvenv.cfg").is_file(), "private venv configuration")
    files[str(prefix / "pyvenv.cfg")] = digest(prefix / "pyvenv.cfg")
    executable = Path(sys.executable).resolve(strict=True)
    files[str(executable)] = digest(executable)
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    inventory = managed_files(prefix, stdlib)
    for path in inventory:
        files[path] = digest(Path(path))
    # This import probe records real selected native libraries in this process.
    # It is deliberately labelled separately from ordinary model-load evidence.
    import torch
    import peft
    import transformers

    require(
        torch.__version__ == "2.9.1+cpu" and torch.version.cuda is None,
        "the exact CPU Torch build is required",
    )
    require(
        peft.__version__ == expected["peft"]
        and transformers.__version__ == expected["transformers"],
        "actual imports differ",
    )
    mapped = {}
    for row in Path("/proc/self/maps").read_text().splitlines():
        fields = row.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith("/"):
            path = Path(fields[5]).resolve(strict=True)
            mapped[str(path)] = digest(path)
    files.update(mapped)
    return dict(
        schema="hepta-controlled-cold-runtime-snapshot-v2",
        requirements_sha256=LOCK_SHA256,
        installation_report_sha256=digest(installation),
        python=dict(
            executable=str(executable),
            version=sys.version,
            implementation=platform.python_implementation(),
            abi=sysconfig.get_config_var("SOABI"),
        ),
        wheels=wheels,
        distributions=distributions,
        files=files,
        managed_inventory=inventory,
        prefix=str(prefix),
        preflight_import_probe_mapped_files=mapped,
        stdlib_root=str(stdlib),
        platform=platform.platform(),
        observed_environment_isolated=True,
        immutable_held_runtime_closure=False,
        actual_model_execution=False,
        production_qualification=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    for name in ("lock", "installation", "output"):
        record.add_argument("--" + name, type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "record":
        value = capture(args.lock, args.installation)
        with args.output.open("x") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
        print(
            json.dumps(
                dict(
                    snapshot_sha256=digest(args.output),
                    files=len(value["files"]),
                    wheels=len(value["wheels"]),
                    held_runtime_closure=False,
                )
            )
        )
    else:
        value = json.loads(args.snapshot.read_bytes())
        require(
            value["schema"] == "hepta-controlled-cold-runtime-snapshot-v2",
            "snapshot schema",
        )
        require(
            value["python"]["executable"]
            == str(Path(sys.executable).resolve(strict=True)),
            "actual interpreter differs",
        )
        require(
            value["managed_inventory"]
            == managed_files(Path(value["prefix"]), Path(value["stdlib_root"])),
            "runtime file inventory drift",
        )
        for path, expected in value["files"].items():
            require(digest(Path(path)) == expected, "runtime byte drift: " + path)
        print(
            json.dumps(
                dict(
                    unchanged_observed_files=len(value["files"]),
                    snapshot_sha256=digest(args.snapshot),
                    held_runtime_closure=False,
                )
            )
        )


if __name__ == "__main__":
    main()
