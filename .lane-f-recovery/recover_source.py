#!/usr/bin/env python3
"""Recover the exact, complete Lane F source members from damaged carriers.

The historical compressed carriers are truncated/corrupted as whole archives.
This utility never treats either archive as authoritative. It streams only the
recoverable prefix, validates TAR headers, and materializes a closed allow-list
whose bytes are pinned by SHA-256. Any missing, duplicate, unsafe, or mismatched
member fails closed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import zlib

BOOTSTRAP_EXPECTED = {
    "codex-rs/hepta-intelligence/Cargo.toml": "0a5be4f0ae54dd1a28ee8c3892c2436d1dcad1bff2d24609684598967242a436",
    "codex-rs/hepta-intelligence/src/lib.rs": "de4ac760d3c6d3bcae572a9fa48cd1a1faf659ba61f61decf2f5e09bc594018f",
    "codex-rs/hepta-intelligence/src/pipeline.rs": "7938bd5f6f716552977442356848467ce84be2af35361137328de3f05f8bc2ba",
    "codex-rs/hepta-intelligence/src/pipeline_tests.rs": "a48fc58a4f284e278f0b1180558585b237f5b6a9c32a2a54c6af287b52e3e736",
    "codex-rs/hepta-intelligence/tests/lane_f_shadow_vertical.rs": "15986b34d9ef2bbe2d146f59e473082b895639bd515b86469bffd73ecf079344",
    "codex-rs/hepta-intuition/src/calibrated.rs": "168aa033fc0eeeb2c4ff4bcc99782f39dcf514b9e26fe8add8b6b441fe7aa8e5",
    "codex-rs/hepta-intuition/src/calibrated_tests.rs": "adcd2f8f65e585e3b9aa14179e3f39aaed2a7f0b84a5f5abba587620324ba762",
    "codex-rs/hepta-intuition/src/lib.rs": "d2b457889daf771fea49b093f1e418027e620c392683d69a340588c98df1aa1e",
    "codex-rs/hepta-plasticity/src/durable_registry.rs": "7c17e0e071bb99397628c8d533132c36343c3486b1246b770fb576ef112db952",
}
MINIMAL_EXPECTED = {
    "codex-rs/hepta-plasticity/src/durable_registry_tests.rs": "7e849cc88fb5c58667139ff3eebbd8d08a59b152fd7f8a8ebd08480fe75810fe",
    "codex-rs/hepta-plasticity/src/lib.rs": "312c8ce62f6ab4a12087504f7f4728f0e1674949b516d46909d6331832e36c54",
    "codex-rs/hepta-prompt-optimizer/src/lib.rs": "1d01c606361f648eff48423b5026853622533ef974da6c4ed8049ee451f6b097",
    "qualification/lane-f-shadow/README.md": "49ba8e2cd892bd984432e479d4300b5a94a9579e574d8ab83d26b0a341207bdc",
    "qualification/lane-f-shadow/src/lib.rs": "8b678805093c3b29e545b586f2be2d8f8fced33d74539a0525e4f6a8628eb600",
}
EXPECTED = BOOTSTRAP_EXPECTED | MINIMAL_EXPECTED


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def parse_octal(field: bytes) -> int:
    value = field.rstrip(b"\0 ").lstrip(b" ")
    return int(value or b"0", 8)


def safe_path(raw: str) -> PurePosixPath:
    path = PurePosixPath(raw)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe TAR member: {raw!r}")
    return path


def partial_decompress(compressed: bytes, decoder: object) -> tuple[bytes, str | None]:
    output = bytearray()
    failure: str | None = None
    for offset in range(0, len(compressed), 256):
        chunk = compressed[offset : offset + 256]
        try:
            output.extend(decoder.decompress(chunk))  # type: ignore[attr-defined]
        except (zlib.error, lzma.LZMAError, EOFError) as exc:
            failure = f"{type(exc).__name__}: {exc}; compressedOffset={offset}"
            break
    return bytes(output), failure


def extract_pinned(
    tar_bytes: bytes,
    expected: dict[str, str],
    *,
    root: Path,
    source: str,
    check: bool,
) -> list[dict[str, object]]:
    recovered: dict[str, bytes] = {}
    offset = 0
    while offset + 512 <= len(tar_bytes):
        header = tar_bytes[offset : offset + 512]
        if not any(header):
            break
        try:
            recorded = parse_octal(header[148:156])
            calculated = sum(header[:148]) + (32 * 8) + sum(header[156:])
            if recorded != calculated:
                offset += 512
                continue
            name = header[:100].split(b"\0", 1)[0].decode("utf-8", "strict")
            prefix = header[345:500].split(b"\0", 1)[0].decode("utf-8", "strict")
            if prefix:
                name = f"{prefix}/{name}"
            member_size = parse_octal(header[124:136])
            type_flag = header[156:157]
        except (UnicodeDecodeError, ValueError):
            offset += 512
            continue

        data_start = offset + 512
        data_end = data_start + member_size
        if data_end > len(tar_bytes):
            break
        if name in expected:
            safe_path(name)
            if type_flag not in (b"", b"0", b"7"):
                raise ValueError(f"pinned member is not a regular file: {name}")
            if name in recovered:
                raise ValueError(f"duplicate pinned member in {source}: {name}")
            payload = tar_bytes[data_start:data_end]
            actual = sha256(payload)
            if actual != expected[name]:
                raise ValueError(
                    f"digest mismatch in {source} for {name}: expected {expected[name]}, got {actual}"
                )
            recovered[name] = payload
        offset = data_start + ((member_size + 511) // 512) * 512

    missing = set(expected) - set(recovered)
    if missing:
        raise ValueError(f"missing complete pinned members in {source}: {sorted(missing)}")

    receipt: list[dict[str, object]] = []
    for name in sorted(recovered):
        payload = recovered[name]
        target = root.joinpath(*PurePosixPath(name).parts)
        if check:
            if not target.is_file() or target.read_bytes() != payload:
                raise ValueError(f"materialized source mismatch: {name}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        receipt.append(
            {"path": name, "bytes": len(payload), "sha256": sha256(payload), "source": source}
        )
    return receipt


def recover(root: Path, check: bool) -> dict[str, object]:
    bootstrap_parts = sorted((root / ".lane-f-bootstrap").glob("part-*"))
    if [path.name for path in bootstrap_parts] != [f"part-{index:02d}" for index in range(7)]:
        raise ValueError("bootstrap carrier must contain exactly part-00 through part-06")
    bootstrap_compressed = b"".join(path.read_bytes() for path in bootstrap_parts)
    bootstrap_tar, bootstrap_error = partial_decompress(
        bootstrap_compressed, zlib.decompressobj(wbits=31)
    )

    minimal_parts = sorted((root / ".lane-f-min").glob("part-*.b64"))
    if [path.name for path in minimal_parts] != ["part-00.b64", "part-01.b64"]:
        raise ValueError("minimal carrier must contain exactly part-00 and part-01")
    encoded = b"".join(path.read_bytes() for path in minimal_parts)
    minimal_compressed = base64.b64decode(b"".join(encoded.split()), validate=False)
    minimal_tar, minimal_error = partial_decompress(
        minimal_compressed, lzma.LZMADecompressor()
    )

    files = extract_pinned(
        bootstrap_tar,
        BOOTSTRAP_EXPECTED,
        root=root,
        source="bootstrap-prefix",
        check=check,
    )
    files.extend(
        extract_pinned(
            minimal_tar,
            MINIMAL_EXPECTED,
            root=root,
            source="minimal-prefix",
            check=check,
        )
    )
    if {row["path"] for row in files} != set(EXPECTED):
        raise ValueError("recovered source set is not closed")
    return {
        "schema": "hepta.lane-f-source-recovery-receipt.v2",
        "status": "PASS_LANE_F_SOURCE_RECOVERY",
        "mode": "check" if check else "materialize",
        "bootstrapCompressedSha256": sha256(bootstrap_compressed),
        "bootstrapDecompressionBoundary": bootstrap_error,
        "minimalCompressedSha256": sha256(minimal_compressed),
        "minimalDecompressionBoundary": minimal_error,
        "files": sorted(files, key=lambda row: str(row["path"])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = recover(args.root.resolve(), args.check)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
