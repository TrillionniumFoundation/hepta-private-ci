"""Lossless numerical/TSV evidence transport; never changes experiment results."""
import argparse
import base64
import gzip
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tempfile

import numpy as np

HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def npz_bytes(native, reference):
    output = io.BytesIO()
    np.savez_compressed(output, native=native, torch=reference)
    return output.getvalue()


def rust_number(value, precision):
    significand, exponent = format(float(value), f".{precision}e").split("e")
    return significand + "e" + str(int(exponent))


def tsv_bytes(array):
    return ("\n".join("\t".join([str(int(row[0])), str(int(row[1]))]
        + [rust_number(x, 17) for x in row[2:162]]
        + [rust_number(x, 9) for x in row[162:]]) for row in array) + "\n").encode()


def recover(record, arrays, numerical, opaque):
    def array(index):
        descriptor = arrays[index]
        raw = numerical[descriptor["offset"]:descriptor["offset"] + descriptor["bytes"]]
        assert sha(raw) == descriptor["sha256"]
        return np.frombuffer(raw, dtype="<f8").reshape(descriptor["shape"])
    if record["codec"] == "npz-pair-xor":
        native, delta = array(record["native"]), array(record["xor"])
        reference = np.bitwise_xor(native.view("<u8"), delta.view("<u8")).view("<f8")
        return npz_bytes(native, reference)
    if record["codec"] == "rust-tsv":
        return tsv_bytes(array(record["array"]))
    return opaque[record["offset"]:record["offset"] + record["bytes"]]


def pack(target):
    roots = [HERE / f"development_{i:02d}" for i in range(1, 5)] + [HERE / "run_01", HERE / "profiles"]
    paths = [p for root in roots for p in root.rglob("*") if p.is_file() and p.name != "forward"]
    paths += list(HERE.glob("development_*.*")) + list(HERE.glob("run_01.*"))
    paths += [HERE / name for name in ("PROFILE_MANIFEST_v1.json", "GUARD_CHECKS.json",
        "REPORT_ZH.md", "COST.json", "BLOCKERS.json", "BINARY_IDENTITIES.json")]
    paths = sorted(set(p for p in paths if p.is_file()))
    numerical, opaque, arrays, ids, records, paired = bytearray(), bytearray(), [], {}, {}, {}

    def add_array(value):
        value = np.ascontiguousarray(value, dtype="<f8")
        raw = value.tobytes(); identity = (sha(raw), tuple(value.shape))
        if identity not in ids:
            ids[identity] = len(arrays)
            arrays.append(dict(offset=len(numerical), bytes=len(raw), shape=list(value.shape), sha256=sha(raw)))
            numerical.extend(raw)
        return ids[identity]

    # Pair matrices carry a shared base plus bytewise XOR, preserving every bit.
    for path in [p for p in paths if p.name.startswith("pair_") and p.suffix == ".npz"]:
        raw = path.read_bytes()
        with np.load(io.BytesIO(raw), allow_pickle=False) as source:
            native, reference = source["native"], source["torch"]
        if native.dtype != np.float64 or reference.dtype != np.float64 or native.shape != reference.shape:
            continue
        if npz_bytes(native, reference) != raw:
            continue
        delta = np.bitwise_xor(native.view("<u8"), reference.view("<u8")).view("<f8")
        records[path] = dict(codec="npz-pair-xor", native=add_array(native), xor=add_array(delta))
        paired[path.with_name(path.stem.removeprefix("pair_") + ".tsv")] = native
    for path in paths:
        raw = path.read_bytes()
        if path not in records and path.suffix == ".tsv" and raw:
            try:
                value = paired[path] if path in paired else np.loadtxt(io.BytesIO(raw), ndmin=2)
                if value.shape[1] == 205 and tsv_bytes(value) == raw:
                    records[path] = dict(codec="rust-tsv", array=add_array(value))
            except (ValueError, IndexError):
                pass
        if path not in records:
            records[path] = dict(codec="verbatim", offset=len(opaque))
            opaque.extend(raw)
        records[path].update(path=path.relative_to(HERE).as_posix(), bytes=len(raw), sha256=sha(raw))
        assert recover(records[path], arrays, numerical, opaque) == raw, path
    metadata = dict(files=[records[path] for path in paths], arrays=arrays,
        numerical_bytes=len(numerical), opaque_bytes=len(opaque), schema="native-evidence-lossless-v1")
    header = canonical(metadata)
    shuffled = np.frombuffer(numerical, dtype="u1").reshape(-1, 8).T.tobytes()
    frame = len(header).to_bytes(8, "little") + header + shuffled + opaque
    normal, alternative = gzip.compress(frame, mtime=0), lzma.compress(frame, preset=6)
    payload, codec = (alternative, "xz") if len(alternative) < len(normal) else (normal, "gzip")
    target.mkdir(exist_ok=False)
    parts = []
    for number, start in enumerate(range(0, len(payload), 90000)):
        raw = base64.b64encode(payload[start:start+90000]); name=f"part_{number:04d}.b64"
        (target / name).write_bytes(raw)
        parts.append(dict(path=name, bytes=len(raw), sha256=sha(raw)))
    logical = [{k:record[k] for k in ("path", "bytes", "sha256")} for record in metadata["files"]]
    (target / "LOGICAL_FILES.json").write_bytes(canonical(logical)+b"\n")
    index = dict(codec=codec, parts=parts, payload_sha256=sha(payload), payload_bytes=len(payload),
        logical_files=len(paths), logical_bytes=sum(len(p.read_bytes()) for p in paths),
        logical_manifest_sha256=sha((target/"LOGICAL_FILES.json").read_bytes()),
        arrays=len(arrays), native_tsv_files=sum(r["codec"]=="rust-tsv" for r in records.values()),
        npz_pair_files=sum(r["codec"]=="npz-pair-xor" for r in records.values()),
        gzip_bytes=len(normal), xz_bytes=len(alternative),
        exactness="NPZ reserialization, Rust TSV formatting, XOR and byte shuffle all checked byte-for-byte; fresh restore verifies every original SHA; no precision reduction",
        excluded_binaries="BINARY_IDENTITIES.json in logical files records all5 generated executable hashes; no binary release")
    (target / "INDEX.json").write_bytes(canonical(index)+b"\n")
    (target / "RESTORE.py").write_bytes(Path(__file__).read_bytes())
    with tempfile.TemporaryDirectory(prefix="hcsn-native-evidence-") as temporary:
        result = restore(target, Path(temporary)/"fresh")
    (target / "FRESH_ROUNDTRIP.json").write_bytes(canonical(result)+b"\n")
    print(json.dumps(dict(files=len(paths), parts=len(parts), logical_bytes=index["logical_bytes"],
        compressed_bytes=len(payload), codec=codec, all_exact=True)))


def restore(source, destination):
    assert not destination.exists(), "Use a fresh destination"
    index = json.loads((source/"INDEX.json").read_text()); pieces=[]
    for part in index["parts"]:
        raw=(source/part["path"]).read_bytes()
        assert len(raw)==part["bytes"] and sha(raw)==part["sha256"]
        pieces.append(base64.b64decode(raw, validate=True))
    payload=b"".join(pieces); assert sha(payload)==index["payload_sha256"]
    frame=lzma.decompress(payload) if index["codec"]=="xz" else gzip.decompress(payload)
    size=int.from_bytes(frame[:8],"little"); meta=json.loads(frame[8:8+size]); body=frame[8+size:]
    count=meta["numerical_bytes"]
    numerical=np.frombuffer(body[:count],dtype="u1").reshape(8,-1).T.tobytes(); opaque=body[count:]
    assert len(opaque)==meta["opaque_bytes"]
    logical=(source/"LOGICAL_FILES.json").read_bytes()
    assert sha(logical)==index["logical_manifest_sha256"]
    identities={r["path"]:r for r in json.loads(logical)}
    for record in meta["files"]:
        name=PurePosixPath(record["path"])
        assert not name.is_absolute() and ".." not in name.parts
        raw=recover(record,meta["arrays"],numerical,opaque)
        assert len(raw)==record["bytes"] and sha(raw)==record["sha256"]==identities[str(name)]["sha256"]
        path=destination/name; path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("xb") as stream:stream.write(raw)
    return dict(all_exact=True,verified_original_files=len(meta["files"]),
        verified_original_bytes=sum(r["bytes"] for r in meta["files"]),index_sha256=sha((source/"INDEX.json").read_bytes()))


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("mode",choices=("pack","restore"))
    parser.add_argument("--source",type=Path,default=HERE/"evidence_compact")
    parser.add_argument("--destination",type=Path);parser.add_argument("--receipt",type=Path)
    args=parser.parse_args()
    if args.mode=="pack":pack(args.source)
    else:
        if args.destination is None:parser.error("restore requires fresh --destination")
        result=restore(args.source,args.destination)
        if args.receipt:args.receipt.write_bytes(canonical(result)+b"\n")
        print(json.dumps(result))
