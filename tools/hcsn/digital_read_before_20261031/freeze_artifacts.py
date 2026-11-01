"""Deterministic, lossless delivery of completed fits, inputs and raw receipts.

Packaging does not train or select models. Gzip timestamps and names are fixed;
tar metadata is normalized while every original file byte is preserved. Large
compressed streams are split into numbered byte chunks, never truncated.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zlib

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
MAX_BYTES = 511999
FAMILIES = ("ordinary_base", "ordinary_bank", "clocked_bank", "first_passage_bank", "raw_history")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write(path, payload):
    if len(payload) > MAX_BYTES:
        raise ValueError("artifact exceeds the strict 512000-byte limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"refusing to overwrite a different artifact: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    if digest(path.read_bytes()) != digest(payload):
        raise IOError(f"artifact readback failed: {path}")
    return dict(path=str(path.relative_to(REPO)), sha256=digest(payload), bytes=len(payload))


def _gzip(payload):
    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as stream:
        stream.write(payload)
    return output.getvalue()


def _pack(path, raw):
    compressed = _gzip(raw)
    metadata = dict(raw_sha256=digest(raw), raw_bytes=len(raw), gzip_sha256=digest(compressed), gzip_bytes=len(compressed))
    if len(compressed) <= MAX_BYTES:
        result = dict(**_write(path, compressed), encoding="gzip", **metadata)
    else:
        parts = [_write(path.with_name(path.name+f".part{i:04d}"), compressed[start:start+MAX_BYTES])
                 for i, start in enumerate(range(0, len(compressed), MAX_BYTES))]
        index = dict(schema="digital-gzip-chunks-v1", reconstruction="Concatenate parts in listed order, verify gzip_sha256, then gzip-decompress and verify raw_sha256", parts=parts, **metadata)
        result = dict(**_write(path.with_name(path.name+".index.json"), canonical(index)+b"\n"),
                      encoding="gzip_chunks", parts=parts, **metadata)
    recovered = read_packed(result)
    if recovered != raw:
        raise IOError("lossless archive roundtrip failed")
    return result


def read_packed(record):
    if record["encoding"] == "gzip":
        compressed = (REPO/record["path"]).read_bytes()
        if digest(compressed) != record["sha256"]:
            raise IOError("compressed artifact identity mismatch")
    elif record["encoding"] == "gzip_chunks":
        index_bytes = (REPO/record["path"]).read_bytes()
        if digest(index_bytes) != record["sha256"]:
            raise IOError("chunk index identity mismatch")
        index = json.loads(index_bytes)
        chunks = []
        for part in index["parts"]:
            payload = (REPO/part["path"]).read_bytes()
            if len(payload) != part["bytes"] or digest(payload) != part["sha256"]:
                raise IOError("chunk identity mismatch")
            chunks.append(payload)
        compressed = b"".join(chunks)
    else:
        raise ValueError("unsupported archive encoding")
    if digest(compressed) != record["gzip_sha256"] or len(compressed) != record["gzip_bytes"]:
        raise IOError("complete compressed stream identity mismatch")
    raw = gzip.decompress(compressed)
    if digest(raw) != record["raw_sha256"] or len(raw) != record["raw_bytes"]:
        raise IOError("uncompressed identity mismatch")
    return raw


def _read_stable(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"only regular evidence files are accepted: {path}")
    before = path.stat()
    payload = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(payload) != after.st_size:
        raise RuntimeError(f"input changed while packaging: {path}")
    return payload


def _snapshot(root, fit):
    folder = root/f"fit_{fit}"
    files = {}
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in evidence: {path}")
        if path.is_file():
            files[str(path.relative_to(folder))] = path
    for path in sorted((root/"logs").glob(f"fit_{fit}.*")):
        files[f"external_logs/{path.name}"] = path
    for path in sorted(root.glob(f"fit_{fit}.*")):
        if path.is_file():
            files[f"external_measurement/{path.name}"] = path
    output, members = io.BytesIO(), []
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, path in sorted(files.items()):
            payload = _read_stable(path)
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(payload), 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(payload))
            members.append(dict(path=name, bytes=len(payload), sha256=digest(payload)))
    for member in members:
        if digest(_read_stable(files[member["path"]])) != member["sha256"]:
            raise RuntimeError("fit evidence changed during snapshot")
    return output.getvalue(), members


def _verify_freeze():
    raw = (HERE/"SOURCE_FREEZE.json").read_bytes()
    freeze = json.loads(raw)
    for relative, expected in freeze["source_sha256"].items():
        path = (REPO/relative).resolve()
        if not path.is_relative_to(REPO) or digest(path.read_bytes()) != expected:
            raise RuntimeError(f"frozen scientific source changed: {relative}")
    return freeze, digest(raw)


def _pack_stage(root, fit, stage, primary_model_hashes=None):
    root = Path(root).resolve()
    folder, models_dir = root/f"fit_{fit}", root/f"fit_{fit}"/"models"
    freeze, freeze_sha = _verify_freeze()
    run_complete = json.loads((folder/"RUN_COMPLETE.json").read_bytes())
    run_started = json.loads((folder/"RUN_STARTED.json").read_bytes())
    complete_raw = _read_stable(models_dir/"COMPLETE.json")
    complete = json.loads(complete_raw)
    started = json.loads(_read_stable(models_dir/"STARTED.json"))
    if (fit != complete["fit"] or fit != run_complete["fit"] or run_started["freeze_sha256"] != freeze_sha
            or run_complete["source_commit"] != freeze["source_commit"]
            or set(complete["models"]) != set(FAMILIES)
            or complete["source_sha256"] != started["source_sha256"]):
        raise ValueError("fit completion/freeze identity mismatch")
    for name, expected in complete["source_sha256"].items():
        if digest((HERE/name).read_bytes()) != expected:
            raise RuntimeError(f"training source identity mismatch: {name}")
    data_path = folder/"data"/f"fit_{fit}_data.json"
    data_raw = _read_stable(data_path)
    data = json.loads(data_raw)
    if digest(data_raw) != complete["data_sha256"] or digest(data_raw) != started["data_sha256"] or data["fit"] != fit:
        raise ValueError("complete training-data identity mismatch")
    for split in ("train", "validation"):
        for relative, expected in data[f"{split}_cohort"]["files"].items():
            path = (folder/"data"/relative).resolve()
            if not path.is_relative_to((folder/"data").resolve()) or digest(_read_stable(path)) != expected:
                raise ValueError(f"cohort raw input identity mismatch: {relative}")
    evidence = HERE/"evidence"/("training" if stage == "primary" else "training_timed")/f"fit_{fit}"
    model_records, equality, receipts = [], [], {}
    for family in FAMILIES:
        declared = complete["models"][family]
        model_raw = _read_stable(models_dir/f"{family}.json")
        model = json.loads(model_raw)
        receipt_raw = _read_stable(models_dir/f"{family}_training.json")
        receipt = json.loads(receipt_raw)
        if (digest(model_raw) != declared["model"]["sha256"] or len(model_raw) != declared["model"]["bytes"]
                or digest(canonical(model)) != declared["model_identity"]
                or digest(receipt_raw) != declared["training_receipt"]["sha256"]
                or receipt["selected_update"] != started["protocol"]["updates"]
                or receipt["validation_used_for_selection"] or model["fit"] != fit or model["family"] != family
                or receipt["initial_head_sha256"] != complete["common_initial_head_sha256"]
                or receipt["minibatch_sha256"] != complete["common_minibatch_sha256"]):
            raise ValueError(f"model/receipt identity mismatch: {family}")
        if stage == "primary":
            packed = _pack(HERE/"checkpoints"/f"fit_{fit}"/f"{family}.json.gz", model_raw)
            if packed["encoding"] != "gzip":
                raise ValueError("unexpected oversized model requires an explicit checkpoint-loader update")
            model_records.append(dict(fit=fit, family=family, path=packed["path"], sha256=packed["sha256"],
                                      model_sha256=digest(model_raw), bytes=packed["bytes"], raw_bytes=len(model_raw),
                                      model_identity=declared["model_identity"]))
        else:
            equal = digest(model_raw) == primary_model_hashes[family]
            if not equal:
                raise ValueError(f"measurement replay changed frozen model bytes: {family}")
            equality.append(dict(fit=fit, family=family, model_sha256=digest(model_raw), byte_identical_to_primary=True))
        receipts[family] = _pack(evidence/f"{family}_training.json.gz", receipt_raw)
    data_archive = _pack(evidence/f"fit_{fit}_data.json.gz", data_raw)
    complete_archive = _pack(evidence/"COMPLETE.json.gz", complete_raw)
    snapshot, members = _snapshot(root, fit)
    full_archive = _pack(evidence/"full_fit.tar.gz", snapshot)
    record = dict(schema="digital-completed-fit-packaging-v1", fit=fit, stage=stage,
                  models=model_records, replay_model_equality=equality,
                  training_data_sha256=digest(data_raw), training_data=data_archive,
                  receipts=receipts, complete=complete_archive, full_fit=full_archive, full_fit_members=members,
                  source_sha256=freeze["source_sha256"], training_source_sha256=complete["source_sha256"],
                  source_commit=freeze["source_commit"], source_freeze_sha256=freeze_sha,
                  packer_sha256=digest(Path(__file__).read_bytes()), zlib_version=zlib.ZLIB_RUNTIME_VERSION,
                  observed_training_total=complete["total"],
                  preservation="All original fit files, including actual train/validation/calibration packet/public/evaluator bytes, labels, raw receipts, model files and available per-fit external logs. Missing injected packets remain absent and are described by the original evaluator records.",
                  deterministic_metadata="gzip mtime=0 and empty filename; sorted USTAR members with uid/gid/mtime=0 and file mode0644",
                  parameter_count_scope="Effective parameter count means active trainable coordinates; independent statistical identifiability of all physical parameters is not established.")
    index = _write(evidence/"PACKAGING_INDEX.json", canonical(record)+b"\n")
    return dict(**record, index=index)


def pack_fit(training_root, fit, timed_root=None):
    primary = _pack_stage(training_root, int(fit), "primary")
    if timed_root is not None:
        primary["measurement_replay"] = _pack_stage(timed_root, int(fit), "measurement_replay",
            {r["family"]: r["model_sha256"] for r in primary["models"]})
    return primary


def pack_all(training_root, timed_root=None):
    protocol = json.loads((HERE/"protocol.json").read_bytes())
    fits = [pack_fit(training_root, fit, timed_root) for fit in protocol["fits"]]
    result = dict(schema="digital-all-fits-packaging-v1", fits=fits,
                  models=[m for fit in fits for m in fit["models"]],
                  training_data_sha256={str(fit["fit"]): fit["training_data_sha256"] for fit in fits},
                  source_sha256=fits[0]["source_sha256"], source_commit=fits[0]["source_commit"],
                  source_freeze_sha256=fits[0]["source_freeze_sha256"], confirmation_generated=False)
    # Large per-file inventories already have their per-fit indices.
    summary = {k: v for k, v in result.items() if k != "fits"}
    summary["fits"] = [dict(fit=r["fit"], index=r["index"],
                            measurement_replay_index=r.get("measurement_replay", {}).get("index")) for r in fits]
    filename = "PACKAGING_WITH_TIMED_REPLAY.json" if timed_root is not None else "PACKAGING_ALL_PRIMARY.json"
    result["index"] = _write(HERE/"evidence"/"training"/filename, canonical(summary)+b"\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-root", type=Path, required=True)
    parser.add_argument("--timed-root", type=Path)
    parser.add_argument("--fit", type=int)
    args = parser.parse_args()
    result = (pack_all(args.training_root, args.timed_root) if args.fit is None else
              pack_fit(args.training_root, args.fit, args.timed_root))
    print(json.dumps(dict(index=result["index"], models=result["models"], training_data_sha256=result["training_data_sha256"]), indent=2))


if __name__ == "__main__":
    main()
