"""Archive immutable evaluated models and predictions with bounded Git blobs."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    root, output = Path(args.evaluation), Path(args.output)
    result_raw = (root / "RESULT.json").read_bytes()
    result = json.loads(result_raw)
    expected = {(n, s) for n in (8, 16, 32, 64) for s in (271901, 271902, 271903)}
    if len(result["rows"]) != 12 or {(r["width"], r["seed"]) for r in result["rows"]} != expected:
        raise ValueError("Unexpected evaluated case roster")
    output.mkdir(exist_ok=False)
    records = []
    for row in result["rows"]:
        width, seed = row["width"], row["seed"]
        names = [f"adopted_n{width}_s{seed}.pt"]
        names += [f"predictions_n{width}_s{seed}_{node}.npz" for node in ("pocket4", "ai395")]
        files, buffer = {}, io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:xz", preset=6) as archive:
            for name in names:
                path = root / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Unexpected evidence file")
                raw = path.read_bytes()
                if name.endswith(".pt") and sha(raw) != row["saved_model_sha256"]:
                    raise ValueError("Evaluated model changed before archiving")
                files[name] = {"sha256": sha(raw), "bytes": len(raw)}
                member = tarfile.TarInfo(name)
                member.size, member.mode, member.mtime = len(raw), 0o644, 0
                archive.addfile(member, io.BytesIO(raw))
        compressed, parts = buffer.getvalue(), []
        for index, offset in enumerate(range(0, len(compressed), 480000)):
            part = compressed[offset:offset + 480000]
            name = f"case_n{width}_s{seed}.tar.xz.part{index:03d}"
            (output / name).write_bytes(part)
            parts.append({"name": name, "index": index, "sha256": sha(part), "bytes": len(part)})
        records.append({"width": width, "seed": seed, "candidate_sha256": row["candidate_sha256"],
                        "archive_sha256": sha(compressed), "archive_bytes": len(compressed),
                        "parts": parts, "files": files})
    manifest = {"schema_version": 1, "result_sha256": sha(result_raw),
                "source_sha256": sha(Path(__file__).read_bytes()), "records": records,
                "raw_files": sum(len(r["files"]) for r in records),
                "archive_bytes": sum(r["archive_bytes"] for r in records),
                "max_part_bytes": max(p["bytes"] for r in records for p in r["parts"]),
                "training_or_evaluation_rerun": False, "pack_wall_s": time.perf_counter() - started}
    (output / "MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "records"}), flush=True)


if __name__ == "__main__":
    main()
