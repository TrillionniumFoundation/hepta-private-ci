"""Package finished workers separately so every manifest stays bounded."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from ..archive import pack, restore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("groups", nargs="+")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--defer-diagnostics", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    start = time.process_time()
    index = []
    for group in args.groups:
        source = root / group
        fits = sorted(p for p in source.glob("fit_*") if p.is_dir())
        entries = [(group + "_" + p.name, p, group + "/" + p.name) for p in fits]
        with tempfile.TemporaryDirectory(prefix="digital-feedback-control-", dir="/tmp") as scratch:
            control = Path(scratch)
            if fits:
                for path in source.iterdir():
                    if path.is_file():
                        shutil.copy2(path, control / path.name)
                if (source / "process_receipts").exists():
                    shutil.copytree(source / "process_receipts", control / "process_receipts")
                entries.append((group + "_control", control, group))
            else:
                entries.append((group, source, group))
            for name, directory, destination in entries:
                if not directory.exists():
                    raise FileNotFoundError(directory)
                archive = root / "archives" / name
                with tempfile.TemporaryDirectory(prefix="digital-feedback-stage-", dir="/tmp") as stage:
                    staged = Path(stage) / "files"
                    derived = []
                    if args.defer_diagnostics and directory.name.startswith("fit_"):
                        shutil.copytree(directory, staged, copy_function=os.link)
                        for split in ("iid", "ood"):
                            path = staged / (split + "_audits.json.gz")
                            if path.exists():
                                raw = path.read_bytes()
                                derived.append(dict(path=path.name, split=split, bytes=len(raw),
                                                    sha256=hashlib.sha256(raw).hexdigest()))
                                path.unlink()
                        (staged / "DERIVED_DIAGNOSTICS.json").write_text(json.dumps(dict(
                            schema="digital-feedback-derived-inventory-v1", derived_files=derived,
                            raw_records_omitted=False,
                            reconstruction="orchestration/rebuild_diagnostics.py; verify every original SHA256"),
                            indent=2) + "\n")
                    else:
                        staged = directory
                    manifest = pack(staged, archive)
                verification = None
                if args.verify:
                    with tempfile.TemporaryDirectory(prefix="digital-feedback-cold-", dir="/tmp") as fresh:
                        verification = restore(archive, Path(fresh) / "restored")
                item = dict(name=name, destination=destination, files=len(manifest["files"]),
                            parts=len(manifest["parts"]), compressed_bytes=manifest["archive_bytes"],
                            archive_sha256=manifest["archive_sha256"], verification=verification)
                index.append(item)
                print(json.dumps(item), flush=True)
    result = dict(groups=args.groups, entries=index, packaging_and_restore_cpu_seconds=time.process_time() - start)
    output = root / "evidence" / ("PACK_" + "_".join(args.groups) + ".json")
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
