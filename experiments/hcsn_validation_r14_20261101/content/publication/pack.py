"""Publish byte-preserving evidence in complete gzip containers under 480 kB.

Every transport file is an independent gzip stream.  Its uncompressed content is
a slice of one deterministic tar archive; no trailing gzip fragments masquerade
as standalone .gz files.  Original scientific gzip bytes are ordinary tar member
payloads and are never rewritten.  Restore validates all bytes and paths before
writing, and refuses to replace a differing existing file.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parents[2]
PUB = BASE / "publication"
CHUNK_BYTES = 470000
MAX_TRANSPORT_BYTES = 480000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, payload):
    path.write_text(json.dumps(payload, indent=2, sort_keys=True)+"\n")


def archived_paths():
    # Preserve every execution byte, including development attempts, raw outcomes,
    # model checkpoints, original source snapshots and complete worker receipts.
    return sorted(str(p.relative_to(BASE)) for p in (BASE/"results").rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def publish_list(complete):
    archived = set(archived_paths())
    files = []
    for path in sorted(BASE.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix==".pyc":
            continue
        relative = str(path.relative_to(BASE))
        directly_reviewable = relative in {
            "results/formal_01/PROTOCOL.json", "results/formal_01/SOURCE_FREEZE.json",
            "results/formal_01/CANDIDATE_FREEZE.json", "results/formal_01/REPORT_ZH.md",
            "results/formal_01/RESULTS_COMPACT.json", "results/formal_01/receipts/train_TOTAL.json",
            "results/formal_01/receipts/evaluate_TOTAL.json",
        }
        if relative in archived and not directly_reviewable:
            continue
        if path.stat().st_size > 512000:
            raise ValueError("An unarchived publication file is too large: "+relative)
        files.append(str(path.relative_to(ROOT)))
    own = str((BASE/"PUBLISH_FILES.json").relative_to(ROOT))
    if own not in files:
        files.append(own)
    write(BASE/"PUBLISH_FILES.json",dict(schema="hcsn.r14.content.publication.v1",
          complete=complete,files=sorted(files),archive_members=sorted(archived),
          source_freeze_sha256=sha((BASE/"results/formal_01/SOURCE_FREEZE.json").read_bytes()),
          restore="python experiments/hcsn_validation_r14_20261101/content/publication/pack.py restore"))


def build():
    manifest_path=PUB/"MANIFEST.json"
    if manifest_path.exists() or list(PUB.glob("part-*.gz")):
        raise FileExistsError("Preserve an existing publication; do not repack in place")
    names=archived_paths()
    members={}
    buffer=io.BytesIO()
    with tarfile.open(fileobj=buffer,mode="w",format=tarfile.PAX_FORMAT) as archive:
        for name in names:
            path=BASE/name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Only ordinary existing files can be archived")
            raw=path.read_bytes()
            members[name]=dict(bytes=len(raw),sha256=sha(raw))
            info=tarfile.TarInfo(name)
            info.size=len(raw)
            info.mode=0o644
            info.mtime=0
            archive.addfile(info,io.BytesIO(raw))
    raw_tar=buffer.getvalue()
    parts=[]
    for number,offset in enumerate(range(0,len(raw_tar),CHUNK_BYTES)):
        chunk=raw_tar[offset:offset+CHUNK_BYTES]
        compressed=gzip.compress(chunk,compresslevel=6,mtime=0)
        if len(compressed)>MAX_TRANSPORT_BYTES:
            raise ValueError("Transport wrapper exceeds the upload bound")
        name=f"part-{number:04d}.tarpart.gz"
        (PUB/name).write_bytes(compressed)
        parts.append(dict(path=name,bytes=len(compressed),sha256=sha(compressed),
                          uncompressed_bytes=len(chunk),uncompressed_sha256=sha(chunk)))
    write(manifest_path,dict(schema="hcsn.r14.content.gzip-transport.v1",parts=parts,
          tar_bytes=len(raw_tar),tar_sha256=sha(raw_tar),members=members,
          gzip_containers="Each part is a complete independent gzip stream; concatenate decompressed parts to reconstruct tar.",
          source_freeze_sha256=sha((BASE/"results/formal_01/SOURCE_FREEZE.json").read_bytes())))
    publish_list(True)


def restore(destination):
    manifest=json.loads((PUB/"MANIFEST.json").read_text())
    if sha((BASE/"results/formal_01/SOURCE_FREEZE.json").read_bytes())!=manifest["source_freeze_sha256"]:
        raise ValueError("Publication belongs to a different scientific source freeze")
    chunks=[]
    for part in manifest["parts"]:
        name=PurePosixPath(part["path"])
        if len(name.parts)!=1 or name.is_absolute() or ".." in name.parts:
            raise ValueError("Unsafe transport filename")
        expected=part["uncompressed_bytes"]
        if not 0<expected<=CHUNK_BYTES:
            raise ValueError("Unregistered decompression size")
        raw=(PUB/str(name)).read_bytes()
        if len(raw)!=part["bytes"] or len(raw)>MAX_TRANSPORT_BYTES or sha(raw)!=part["sha256"]:
            raise ValueError("Transport identity mismatch: "+str(name))
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            chunk=stream.read(expected+1)
        if len(chunk)!=expected or sha(chunk)!=part["uncompressed_sha256"]:
            raise ValueError("Transport decompression mismatch")
        chunks.append(chunk)
    raw_tar=b"".join(chunks)
    if len(raw_tar)!=manifest["tar_bytes"] or sha(raw_tar)!=manifest["tar_sha256"]:
        raise ValueError("Archive identity mismatch")
    payloads={}
    with tarfile.open(fileobj=io.BytesIO(raw_tar),mode="r:") as archive:
        entries=archive.getmembers()
        if len(entries)!=len(manifest["members"]) or set(e.name for e in entries)!=set(manifest["members"]):
            raise ValueError("Archive member inventory mismatch")
        for entry in entries:
            name=PurePosixPath(entry.name)
            if name.is_absolute() or ".." in name.parts or not entry.isfile():
                raise ValueError("Unsafe archive member")
            expected=manifest["members"][entry.name]
            if entry.size!=expected["bytes"]:
                raise ValueError("Archive member size mismatch")
            raw=archive.extractfile(entry).read(entry.size+1)
            if len(raw)!=entry.size or sha(raw)!=expected["sha256"]:
                raise ValueError("Original scientific bytes changed")
            payloads[entry.name]=raw
    destination=destination.resolve()
    for name,raw in payloads.items():
        target=destination/name
        if not target.resolve().is_relative_to(destination):
            raise ValueError("Restore path escapes destination")
        if target.exists() and target.read_bytes()!=raw:
            raise FileExistsError("Refusing to overwrite different bytes: "+name)
    for name,raw in payloads.items():
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            target.write_bytes(raw)
    result=dict(restored_members=len(payloads),tar_sha256=sha(raw_tar),
                total_original_bytes=sum(map(len,payloads.values())),
                unchanged_source_freeze_sha256=manifest["source_freeze_sha256"],
                target=str(destination))
    print(json.dumps(result,sort_keys=True))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage",choices=("list","build","restore"))
    parser.add_argument("--destination",type=Path,default=BASE)
    args=parser.parse_args()
    if args.stage=="list":
        publish_list(False)
    elif args.stage=="build":
        build()
    else:
        restore(args.destination)


if __name__=="__main__":
    main()
