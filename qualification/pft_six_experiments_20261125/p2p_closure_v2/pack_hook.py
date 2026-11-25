#!/usr/bin/env python3
"""Archive a completed external-provider run without rerunning any computation."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time

EXPECTED_SOURCES = {
    "sufficient.py": "aa00a413a973c93cb74761c2918c3618100909d05870b062d5eb0507cfe38553",
    "stream_peer.py": "0a1a6a8721197ab756cd7a40f460723832bc98cbf56eb2cd06a5442d0872c638",
    "ssh_runner.py": "e860287e58562531566d3c4ff90f71beba5df9a1d46cd19862b9d2939d337f7f",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--node", choices=["ai395", "pocket4"], required=True)
    args = parser.parse_args()
    start = time.monotonic()
    root, output = Path(args.root), Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    logical = output / "logical_private"
    logical.mkdir(exist_ok=True)
    files, archives = {}, []
    for n in (21, 41, 81, 161):
        for seed in (271901, 271902, 271903):
            folder = root / f"pft2-hcsn-usb4-v2-n{n}-s{seed}"
            result = json.loads((folder / "result.json").read_text())
            if (result["node"] != args.node or result["size"] != n or result["seed"] != seed
                    or result["sources"] != EXPECTED_SOURCES or result["round_id"] != folder.name):
                raise ValueError("Unexpected completed host result")
            if sha((folder / "stats.json.zlib").read_bytes()) != result["stats_sha256"]:
                raise ValueError("Statistics changed after completion")
            members = [folder / name for name in ("result.json", "terminal_receipt.json", "stats.json.zlib", "crash.json", "crash_checkpoint.json.zlib") if (folder / name).exists()]
            if args.node == "ai395" and n == 161 and seed == 271903:
                members.append(root / "supervisor_result.json")
            name = f"pft2_hcsn_ssh_{args.node}_d{n}_s{seed}.tar.xz"
            target = logical / name
            with tarfile.open(target, "w:xz", preset=6) as archive:
                for path in sorted(members):
                    content = path.read_bytes()
                    relative = str(path.relative_to(root))
                    info = tarfile.TarInfo(relative)
                    info.size, info.mode, info.mtime = len(content), 0o644, 0
                    archive.addfile(info, io.BytesIO(content))
                    files[relative] = {"sha256": sha(content), "bytes": len(content)}
            raw, parts = target.read_bytes(), []
            for index, offset in enumerate(range(0, len(raw), 480000)):
                part = raw[offset:offset + 480000]
                part_name = name if len(raw) <= 480000 else name + f".part{index:03}"
                path = output / part_name
                if path.exists() and path.read_bytes() != part:
                    raise ValueError("Published archive parts are immutable")
                path.write_bytes(part)
                if path.read_bytes() != part:
                    raise ValueError("Archive readback changed")
                parts.append({"name": part_name, "bytes": len(part), "sha256": sha(part)})
            archives.append({"name": name, "dimension": n, "seed": seed, "bytes": len(raw),
                             "sha256": sha(raw), "parts": parts})
    report = {"record_kind": "pft_hcsn_peer_archive_manifest", "schema_version": 1,
              "node": args.node, "sources": EXPECTED_SOURCES, "archives": archives, "files": files,
              "pack_source_sha256": sha(Path(__file__).read_bytes()), "pack_wall_seconds": time.monotonic() - start,
              "excluded": "SSH private logs and endpoint/configuration files; logical archives exceeding the public blob size are reconstructed from their ordered parts."}
    content = (json.dumps(report, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (output / "manifest.json").write_bytes(content)
    print(json.dumps({"node": args.node, "manifest_sha256": sha(content), "manifest_bytes": len(content),
                      "logical_archives": len(archives), "parts": sum(len(a["parts"]) for a in archives),
                      "total_bytes": sum(a["bytes"] for a in archives), "pack_wall_seconds": report["pack_wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
