"""Verify retained Rust data against its original qualification, without writing it."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

POLICY = Path(__file__).with_name("format_provenance") / "retained_rust.json"
POLICY_SHA256 = "297c9433259161d5612b9de59850416cba0a325274df98019f0c280a515d7980"
PREFORMAT = "research/rrsnn_v4/hepta/bootstrap_runtime_preformat.rs"
SUPERSESSION = "research/rrsnn_v4/hepta/bootstrap_format_supersession.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_policy() -> dict:
    data = POLICY.read_bytes()
    if sha(data) != POLICY_SHA256:
        raise ValueError("retained Rust source inventory changed")
    return json.loads(data)


INVENTORY = read_policy()


def checked_bytes(root: Path, relative: str, expected: str) -> bytes:
    source = root / relative
    try:
        if (
            not source.is_relative_to(root)
            or source.resolve(strict=True) != source
            or not source.is_file()
        ):
            raise ValueError(f"retained Rust source escapes or aliases: {relative}")
        data = source.read_bytes()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"cannot read retained Rust source: {relative}") from error
    if sha(data) != expected:
        raise ValueError(f"retained Rust source changed: {relative}")
    return data


def verify_preformat(source: bytes, receipt: dict) -> None:
    """Reconstruct the exact recorded successor in memory using the published hunk."""
    before = source.decode().splitlines(keepends=True)
    patch = receipt["diff"].splitlines(keepends=True)
    match = re.fullmatch(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@\n", patch[2])
    if not match or patch[:2] != ["--- tested-preformat\n", "+++ final-rustfmt\n"]:
        raise ValueError("invalid retained pre-format successor hunk")
    offset, length, new_offset, new_length = map(int, match.groups())
    lines = patch[3:]
    previous = [line[1:] for line in lines if line.startswith((" ", "-"))]
    updated = [line[1:] for line in lines if line.startswith((" ", "+"))]
    start = offset - 1
    if (
        len(previous) != length
        or len(updated) != new_length
        or new_offset != offset
        or before[start : start + length] != previous
    ):
        raise ValueError("retained pre-format successor context differs")
    final = "".join(before[:start] + updated + before[start + length :]).encode()
    if (
        sha(source) != receipt["preformat_source_sha256"]
        or sha(final) != receipt["final_source_sha256"]
        or receipt["rustfmt_check_code"] != 0
    ):
        raise ValueError("retained pre-format and final source identities differ")


def verify_all(root: Path) -> None:
    root = root.resolve()
    companions = {
        p: checked_bytes(root, p, digest)
        for p, digest in INVENTORY["companions"].items()
    }
    for relative, row in INVENTORY["archived"].items():
        data = checked_bytes(root, relative, row["sha256"])
        if relative == PREFORMAT:
            receipt = json.loads(companions[SUPERSESSION])
            verify_preformat(data, receipt)
            for name, key in (
                ("bootstrap_recovery_preformat.patch", "preformat_patch_sha256"),
                ("bootstrap_recovery.patch", "final_patch_sha256"),
            ):
                if (
                    sha(
                        companions[
                            str(Path(PREFORMAT).with_name(name)).replace("\\", "/")
                        ]
                    )
                    != receipt[key]
                ):
                    raise ValueError(
                        f"retained bootstrap patch identity differs: {name}"
                    )


def builder_edition(root: Path, relative: str) -> str:
    """Read the declared edition from a maintained source's code-generating build driver."""
    builder = INVENTORY["maintained_builders"][relative]
    tree = ast.parse((root / builder).read_text(encoding="utf-8"))
    editions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for flag, manifest in re.findall(
                r'--edition=(\d{4})\b|\bedition\s*=\s*"(\d{4})"', node.value
            ):
                editions.add(flag or manifest)
    if len(editions) != 1 or not editions <= {"2015", "2018", "2021", "2024"}:
        raise ValueError(
            f"cannot determine the single Rust edition in build driver {builder}"
        )
    return editions.pop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    relative = args.source.relative_to(root).as_posix()
    row = INVENTORY["archived"][relative]
    checked_bytes(root, relative, row["sha256"])
    if row["role"] == "preformat":
        receipt = checked_bytes(
            root, SUPERSESSION, INVENTORY["companions"][SUPERSESSION]
        )
        verify_preformat((root / relative).read_bytes(), json.loads(receipt))
    print(f"{relative}: {row['role']} original bytes verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
