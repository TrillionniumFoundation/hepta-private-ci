"""Refuse an unsafe historical pip freeze before a CPU replay installation.

This gate preserves the original requirements bytes. It does not project an
old environment, grant qualification, install packages or replace the caller's
complete post-install pip-freeze comparison.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat


MAX_FREEZE_BYTES = 1 << 20
PROTECTED_VERSIONS = {
    "torch": "2.10.0",
    "torchvision": "0.25.0",
    "torchaudio": "2.10.0",
}
CONSTRAINTS = Path(__file__).with_name("torch_runtime_constraints.txt")
PIN = re.compile(
    r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)=="
    r"([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
)


def read_regular(path):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= MAX_FREEZE_BYTES
        ):
            raise ValueError("requirements must be a nonempty bounded regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(MAX_FREEZE_BYTES + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not 0 < len(raw) <= MAX_FREEZE_BYTES
        or len(raw) != before.st_size
        or any(getattr(before, field) != getattr(after, field) for field in fields)
    ):
        raise ValueError("requirements changed or exceeded the byte limit")
    return raw


def parse_freeze(raw):
    packages = {}
    for number, text in enumerate(raw.decode("utf-8").splitlines(), 1):
        line = text.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if match is None:
            raise ValueError(
                f"line {number}: exact name==version required; options, URLs, "
                "nested requirements, markers and editable installs are refused"
            )
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in packages:
            raise ValueError(f"line {number}: duplicate normalized package name {name}")
        packages[name] = match[2]
    if not packages:
        raise ValueError("requirements contain no package pins")
    return packages


def validate_environment(packages):
    if "torch" not in packages:
        raise ValueError("historical freeze must explicitly pin torch")
    for name, version in PROTECTED_VERSIONS.items():
        if name in packages and packages[name] not in (version, version + "+cpu"):
            raise ValueError(
                f"{name}=={packages[name]} is incompatible with the declared safe "
                f"CPU runtime {version}; preserve the historical environment and "
                "register a new prospective runtime instead of replaying it"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", type=Path, required=True)
    args = parser.parse_args()
    record = {
        "schema": "hepta.torch-exact-environment-install-gate.v1",
        "requirements_path": str(args.requirements),
        "projection_applied": False,
        "historical_qualification_inherited": False,
        "complete_post_install_freeze_comparison_required": True,
    }
    try:
        raw = read_regular(args.requirements)
        record["original_requirements_sha256"] = hashlib.sha256(raw).hexdigest()
        record["original_requirements_bytes"] = len(raw)
        constraints = read_regular(CONSTRAINTS)
        if parse_freeze(constraints) != PROTECTED_VERSIONS:
            raise ValueError("the committed CPU runtime constraints differ")
        record["constraints_sha256"] = hashlib.sha256(constraints).hexdigest()
        packages = parse_freeze(raw)
        validate_environment(packages)
        record["package_count"] = len(packages)
        record["protected_pins"] = {
            name: packages[name] for name in PROTECTED_VERSIONS if name in packages
        }
    except (OSError, UnicodeError, ValueError) as error:
        record["status"] = "REFUSED_BEFORE_INSTALL"
        record["error"] = str(error)
        print(json.dumps(record, sort_keys=True))
        return 1
    record["status"] = "EXACT_ENVIRONMENT_ALLOWED_FOR_INSTALL"
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
