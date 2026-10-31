"""Restore the frozen AV cache from Git-tracked bounded transport objects.

Standard-library-only bootstrap, separate from frozen model/analysis sources.
For sparse checkout, first obtain this package and the original transport index,
then run --print-sparse-paths and feed its output to git sparse-checkout set
--no-cone --stdin. The default command verifies the 162 baseline files, restores
only four AV logical files, runs the original train reconstruction, and verifies
DATASET identities without decoding any NPZ arrays or downloading media.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tempfile
import time

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[3]
PACKAGE = "experiments/hcsn_conservative_acceleration_v1"
BASELINE = PACKAGE + "/SOURCE_BASELINE.json"
DATA = "experiments/hcsn_real_av_v1/data"
INDEX = "experiments/hcsn_sixstage_v1/transport_indexes/initial_text_bounded.json"
TRANSPORT = "experiments/hcsn_sixstage_v1/transport.py"
TRAIN_RESTORE = DATA + "/transport/restore_train.py"
PARENT = "63fd568b177c0456ddd8b590e3ac77d35307c0c4"
PINS = {
    INDEX: "c32e955be03e2d8206070eac436534c1c28c2ee8",
    TRANSPORT: "de6c0425e21ec498c328beacd6ea5a2b5521cf1b",
    TRAIN_RESTORE: "75083a1b48957ff07a1bffcde8da58773101ddb0",
    DATA + "/transport/TRAIN_MANIFEST.json": "020f06a3c5a89d454c4c3678230d9944226d5167",
    DATA + "/DATASET.json": "c653426ac9fd9f36dd8176ae0bb2b058b30e62e1",
}
LOGICAL = {
    DATA + "/test.npz",
    DATA + "/validation.npz",
    DATA + "/transport/train.npz.part000",
    DATA + "/transport/train.npz.part001",
}
METADATA = (
    "ACQUISITION.json", "COHORT_PLAN.json", "CREMA_D_LICENSE.txt",
    "DATASET.json", "DECODE.json", "MANIFEST.json", "PREPARATION_COST.json",
    "normalization.npz", "transport/TRAIN_MANIFEST.json",
    "transport/TRANSPORT_VALIDATION.json", "transport/restore_train.py",
)


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts or "\\" in name:
        raise ValueError("Unsafe repository path: " + name)
    return path


def inside(root, name):
    path = root.joinpath(*relative(name).parts)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Repository path escapes or is a symlink: " + name)
    return path


def digest(path, git=False):
    size = path.stat().st_size
    value = hashlib.sha1(b"blob " + str(size).encode() + b"\0") if git else hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read_json(root, name):
    return json.loads(inside(root, name).read_text(encoding="utf-8"))


def baseline_files(root):
    baseline = read_json(root, BASELINE)
    rows = baseline["files"]
    if baseline["remote_parent"] != PARENT or len(rows) != 162:
        raise ValueError("Unexpected frozen source baseline identity/count")
    names = [str(relative(row["path"])) for row in rows]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate baseline source path")
    return rows


def av_registry(root):
    path = inside(root, INDEX)
    if digest(path, git=True) != PINS[INDEX]:
        raise ValueError("Original transport index identity mismatch")
    original = read_json(root, INDEX)
    if original["schema"] != "hcsn-bounded-exact-transport.v2" or original["maximum_git_blob_bytes"] != 512000:
        raise ValueError("Unexpected original transport contract")
    rows = [row for row in original["logical_files"] if row["path"] in LOGICAL]
    if len(rows) != 4 or {row["path"] for row in rows} != LOGICAL:
        raise ValueError("Missing or duplicate AV logical file")
    parts = {}
    for row in rows:
        for item in row["parts"]:
            relative(item["path"])
            if not item["path"].startswith("experiments/hcsn_sixstage_v1/transport_objects/"):
                raise ValueError("Unexpected AV transport object location")
            if item["bytes"] > 512000 or item.get("encoding") != "base64":
                raise ValueError("Transport object violates original blob contract")
            if item["path"] in parts and parts[item["path"]] != item:
                raise ValueError("Inconsistent duplicate transport object")
            parts[item["path"]] = item
    subset = dict(original, logical_files=rows,
                  logical_bytes=sum(row["bytes"] for row in rows),
                  unique_part_bytes=sum(item["bytes"] for item in parts.values()),
                  unique_parts=len(parts))
    return subset, parts


def sparse_patterns(root):
    registry, parts = av_registry(root)
    names = {row["path"] for row in baseline_files(root)}
    names.update(PINS)
    names.update(DATA + "/" + name for name in METADATA)
    names.update(parts)
    names.add(PACKAGE + "/")
    names.add("experiments/hcsn_free_boundary_v1/native_vendor/")
    names.add("experiments/hcsn_free_boundary_v1/restore_native.py")
    names.add(".github/workflows/hcsn-conservative-hosted.yml")
    return ["/" + name for name in sorted(names)]


def load_original(root, name, module_name):
    path = inside(root, name)
    if digest(path, git=True) != PINS[name]:
        raise ValueError("Original restore source identity mismatch: " + name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def restore(root):
    started_cpu, started_wall = time.process_time(), time.perf_counter()
    root = root.resolve()
    rows = baseline_files(root)
    for row in rows:
        path = inside(root, row["path"])
        if digest(path) != row["sha256"] or digest(path, git=True) != row["git_blob"]:
            raise ValueError("Frozen source mismatch: " + row["path"])
    for name, expected in PINS.items():
        if digest(inside(root, name), git=True) != expected:
            raise ValueError("Pinned source/manifest mismatch: " + name)
    registry, parts = av_registry(root)
    transport = load_original(root, TRANSPORT, "hcsn_original_bounded_transport")
    train_restore = load_original(root, TRAIN_RESTORE, "hcsn_original_train_restore")
    with tempfile.TemporaryDirectory(prefix="hcsn-av-index-") as temporary:
        selected = Path(temporary) / "av_subset.json"
        selected.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
        bounded = transport.restore(selected, object_root=root, destination=root)
    training = train_restore.restore(destination=inside(root, DATA + "/train.npz"))
    dataset = read_json(root, DATA + "/DATASET.json")
    if set(dataset["splits"]) != {"train", "validation", "test"}:
        raise ValueError("Unexpected dataset split contract")
    files = []
    for split, record in sorted(dataset["splits"].items()):
        if record["path"] != split + ".npz":
            raise ValueError("Unexpected original split path")
        path = inside(root, DATA + "/" + record["path"])
        actual = digest(path)
        if actual != record["sha256"]:
            raise ValueError("Frozen dataset SHA256 mismatch: " + split)
        files.append(dict(split=split, path=str(path.relative_to(root)),
                          bytes=path.stat().st_size, sha256=actual,
                          git_blob_sha=digest(path, git=True)))
    for name, key in (("MANIFEST.json", "manifest_sha256"),
                      ("DECODE.json", "decode_receipt_sha256"),
                      ("normalization.npz", "normalization_sha256")):
        if digest(inside(root, DATA + "/" + name)) != dataset[key]:
            raise ValueError("Dataset metadata identity mismatch: " + name)
    for row in registry["logical_files"]:
        if digest(inside(root, row["path"]), git=True) != row["git_blob_sha"]:
            raise ValueError("Restored logical Git blob identity mismatch")
    train_manifest = read_json(root, DATA + "/transport/TRAIN_MANIFEST.json")
    if digest(inside(root, DATA + "/train.npz"), git=True) != train_manifest["git_blob_sha"]:
        raise ValueError("Reconstructed training Git blob identity mismatch")
    return dict(schema="hcsn-hosted-av-bootstrap.v1", passed=True,
                bootstrap_source=str(Path(__file__).resolve()),
                bootstrap_sha256=digest(Path(__file__).resolve()),
                bootstrap_is_frozen_model_or_analysis_source=False,
                published_parent_commit=PARENT, source_baseline_sha256=digest(inside(root, BASELINE)),
                baseline_sources_verified=len(rows),
                original_source_and_manifest_git_pins=PINS,
                original_index_sha256=digest(inside(root, INDEX)),
                dataset_manifest_sha256=digest(inside(root, DATA + "/DATASET.json")),
                transport_parts_verified=len(parts),
                maximum_git_blob_bytes=512000,
                bounded_restore=bounded, training_restore=training, files=files,
                heldout_arrays_decoded=False, media_downloaded=False,
                cpu_seconds=time.process_time()-started_cpu,
                wall_seconds=time.perf_counter()-started_wall,
                timing_scope="Local bootstrap body; excludes Git checkout, dependencies and later training.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO)
    parser.add_argument("--print-sparse-paths", action="store_true",
                        help="Print root-anchored git sparse-checkout --no-cone patterns.")
    parser.add_argument("--receipt", type=Path,
                        help="Optionally create a new receipt; existing receipts are never overwritten.")
    args = parser.parse_args()
    if args.print_sparse_paths:
        print("\n".join(sparse_patterns(args.repo.resolve())))
        return
    result = restore(args.repo)
    text = json.dumps(result, indent=2, allow_nan=False) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.receipt.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
