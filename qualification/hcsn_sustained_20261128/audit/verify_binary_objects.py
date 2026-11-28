"""Verify Git objects by streaming their bytes. Payloads are never unpacked or executed."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sqlite3
import subprocess
import tempfile
import time


REMOTE = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"
PACK_LIMIT = 1024**3
MIN_FREE = 8 * 1024**3


def signature(prefix):
    for magic, name in (
        (b"\x1f\x8b", "gzip"), (b"PK\x03\x04", "zip"), (b"PK\x05\x06", "zip"),
        (b"\xfd7zXZ\0", "xz"), (b"BZh", "bzip2"), (b"\x28\xb5\x2f\xfd", "zstd"),
        (b"\x93NUMPY", "npy"), (b"\x89HDF\r\n\x1a\n", "hdf5"), (b"PAR1", "parquet"),
        (b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpeg"),
        (b"GIF87a", "gif"), (b"GIF89a", "gif"), (b"RIFF", "riff"),
        (b"fLaC", "flac"), (b"OggS", "ogg"), (b"%PDF-", "pdf"),
        (b"\x7fELF", "elf"), (b"\x00asm", "wasm"), (b"GGUF", "gguf"),
        (b"version https://git-lfs.github.com/spec/v1", "git-lfs-pointer"),
    ):
        if prefix.startswith(magic):
            return name
    if prefix[4:8] == b"ftyp":
        return "iso-base-media"
    if prefix[257:262] == b"ustar":
        return "tar"
    if not prefix:
        return "empty"
    return "unrecognized-header"


def limit_pack_file():
    resource.setrlimit(resource.RLIMIT_FSIZE, (PACK_LIMIT, PACK_LIMIT))


def inspect_pack(root, records):
    if shutil.disk_usage(root).free < MIN_FREE:
        raise OSError("Less than eight GiB of disk headroom")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1"}
    with tempfile.TemporaryDirectory(prefix="binary-pack-", dir=root) as tmp:
        base = ["git", "-C", tmp]
        subprocess.run(base + ["init", "--bare", "--quiet"], env=env, check=True)
        subprocess.run(base + ["remote", "add", "origin", REMOTE], env=env, check=True)
        command = base + ["-c", "fetch.negotiationAlgorithm=noop", "-c", "gc.auto=0",
                          "-c", "fetch.writeCommitGraph=false", "fetch", "--quiet", "--no-tags",
                          "--filter=blob:none", "--no-write-fetch-head", "--stdin", "origin"]
        payload = b"".join(oid.encode() + b"\n" for oid, _ in records)
        fetched = subprocess.run(command, input=payload, env=env, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.PIPE, timeout=480)
        if fetched.returncode:
            msg = fetched.stderr.decode(errors="replace")
            if "file too large" in msg.lower() or "exceeds maximum" in msg.lower():
                raise OverflowError("The temporary pack exceeded its file limit")
            raise RuntimeError("Git fetch failed with exit %d: %s" % (fetched.returncode, msg[-450:]))
        rows = []
        with subprocess.Popen(base + ["cat-file", "--batch"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, env=env) as git:
            for oid, label in records:
                git.stdin.write(oid.encode() + b"\n")
                git.stdin.flush()
                header = git.stdout.readline().split()
                if len(header) != 3 or header[:2] != [oid.encode(), b"blob"]:
                    raise ValueError("Unexpected Git object header: " + oid)
                size = int(header[2])
                git_hash = hashlib.sha1(b"blob " + header[2] + b"\0")
                sha256 = hashlib.sha256()
                prefix = bytearray()
                left = size
                while left:
                    block = git.stdout.read(min(left, 1024 * 1024))
                    if not block:
                        raise ValueError("Premature end of blob " + oid)
                    if len(prefix) < 512:
                        prefix.extend(block[:512-len(prefix)])
                    git_hash.update(block)
                    sha256.update(block)
                    left -= len(block)
                if git.stdout.read(1) != b"\n" or git_hash.hexdigest() != oid:
                    raise ValueError("Git blob integrity mismatch: " + oid)
                rows.append((oid, label, size, sha256.hexdigest(), signature(prefix)))
            git.stdin.close()
        return rows


def recoverable_batch(root, records):
    for attempt in range(3):
        try:
            return inspect_pack(root, records), []
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            failure = str(exc)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
        except OverflowError as exc:
            failure = str(exc)
            break
    if len(records) > 1 and "file limit" in failure:
        middle = len(records) // 2
        left, left_errors = recoverable_batch(root, records[:middle])
        right, right_errors = recoverable_batch(root, records[middle:])
        return left + right, left_errors + right_errors
    return [], [(oid, failure) for oid, _ in records]


def main(root, jobs, batch_size, shard, shard_count):
    root.mkdir(parents=True, exist_ok=True)
    limit_pack_file()
    lock = (root / "binary.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    meta = json.loads((root / "roster.json").read_text())
    roster = gzip.decompress((root / "roster.tsv.gz").read_bytes())
    if hashlib.sha256(roster).hexdigest() != meta["uncompressed_sha256"]:
        raise ValueError("Frozen binary roster checksum mismatch")
    records = [line.decode().split("\t") for line in roster.splitlines()]
    if len(records) != len({oid for oid, _ in records}) or len(records) != meta["objects"]:
        raise ValueError("Frozen roster population mismatch")
    assigned = [r for r in records if int(r[0][:8], 16) % shard_count == shard]
    db = sqlite3.connect(root / "binary.sqlite")
    db.execute("create table if not exists blobs(oid text primary key, label text, size integer, sha256 text, magic text)")
    db.execute("create table if not exists errors(oid text primary key, reason text)")
    done = {row[0] for row in db.execute("select oid from blobs")}
    if not done.issubset({r[0] for r in assigned}):
        raise ValueError("Existing results belong to a different shard")
    pending = [r for r in assigned if r[0] not in done]
    print("Assigned", len(assigned), "already verified", len(done), "free bytes", shutil.disk_usage(root).free, flush=True)
    chunks = [pending[i:i+batch_size] for i in range(0, len(pending), batch_size)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for offset in range(0, len(chunks), jobs):
            futures = [pool.submit(recoverable_batch, root, group) for group in chunks[offset:offset+jobs]]
            for future in futures:
                rows, errors = future.result()
                with db:
                    db.executemany("insert into blobs values(?,?,?,?,?)", rows)
                    db.executemany("delete from errors where oid=?", [(x[0],) for x in rows])
                    db.executemany("insert or replace into errors values(?,?)", errors)
                if errors:
                    print("Fetch errors", len(errors), errors[0][1], flush=True)
            if offset % (jobs * 8) == 0:
                print("Verified objects and bytes", *db.execute("select count(*),sum(size) from blobs").fetchone(), flush=True)
    total, nbytes = db.execute("select count(*),coalesce(sum(size),0) from blobs").fetchone()
    stats = {"finished_utc": datetime.now(timezone.utc).isoformat(), "assigned": len(assigned),
             "shard":shard, "shard_count":shard_count, "verified":total, "bytes":nbytes,
             "errors":db.execute("select count(*) from errors").fetchone()[0],
             "by_path_class":{}, "by_signature":{}, "roster_sha256":meta["uncompressed_sha256"]}
    for k, n, size in db.execute("select label,count(*),sum(size) from blobs group by label"):
        stats["by_path_class"][meta["labels"][k]] = {"objects":n,"bytes":size}
    for k, n, size in db.execute("select magic,count(*),sum(size) from blobs group by magic"):
        stats["by_signature"][k] = {"objects":n,"bytes":size}
    table_sha = hashlib.sha256()
    with gzip.open(root/"verified.tsv.gz", "wb") as output:
        for row in db.execute("select oid,label,size,sha256,magic from blobs order by oid"):
            line = ("\t".join(map(str, row))+"\n").encode()
            table_sha.update(line)
            output.write(line)
    stats["uncompressed_table_sha256"] = table_sha.hexdigest()
    (root / "binary_summary.json").write_text(json.dumps(stats,indent=2)+"\n")
    print(json.dumps(stats),flush=True)
    if total != len(assigned):
        raise SystemExit(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("--jobs",type=int,choices=range(1,5),default=2)
    parser.add_argument("--batch",type=int,default=72)
    parser.add_argument("--shard",type=int,default=0)
    parser.add_argument("--shards",type=int,default=1)
    args = parser.parse_args()
    if args.batch < 1 or args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("Require a positive batch size and a valid zero-based shard")
    main(args.root,args.jobs,args.batch,args.shard,args.shards)
