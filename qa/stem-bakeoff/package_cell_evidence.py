"""Deterministic, deduplicated DATA archive with immutable Git code references.

No repository files or checkpoint weights are copied into the download. Every
logical evidence path is recoverable from a content-addressed object, and an
external index binds the complete archive. All operations use the standard lib.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

SCHEMA = "hepta.cell-next-stage-evidence.v1"
MAX_ARCHIVE_BYTES = 500_000_000
MAX_OBJECT_BYTES = 128 * 1024**2
REPOSITORY = "https://github.com/TrillionniumFoundation/hepta-private-ci"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_name(value):
    if type(value) is not str:
        raise ValueError("archive path must be a string")
    path = PurePosixPath(value)
    if (not value or len(value.encode()) > 4096 or path.is_absolute() or ".." in path.parts
            or str(path) != value or "\\" in value or ":" in value or any(ord(c) < 32 for c in value)):
        raise ValueError("noncanonical or escaping archive path")
    return value


def inventory_digest(root):
    files = [[str(p.relative_to(root)), p.stat().st_size, sha_file(p)]
             for p in sorted(root.rglob("*")) if p.is_file()]
    return hashlib.sha256(canonical(files).rstrip(b"\n")).hexdigest()


def verify_studies(run_root, dataset):
    dataset_sha = sha_file(dataset)
    tasks = json.loads(Path(dataset).read_bytes())["selected_tasks"]
    receipts = {}
    for candidate in ("granite97m", "embeddinggemma2"):
        root = run_root / candidate / "study"
        plan = json.loads((root / "study-plan.json").read_bytes())
        summary = json.loads((root / "summary.json").read_bytes())
        final = json.loads((root / "finalization.json").read_bytes())
        binding = hashlib.sha256(canonical(plan).rstrip(b"\n")).hexdigest()
        if plan["dataset_sha256"] != dataset_sha or plan["selected_tasks"] != tasks or summary["plan"] != plan:
            raise ValueError("study dataset, task or completion plan differs")
        for task in tasks:
            seal = json.loads((root / "completed" / (task + ".json")).read_bytes())
            if (seal["task"] != task or seal["plan_sha256"] != binding
                    or seal["inventory_sha256"] != inventory_digest(root / "curves" / task)):
                raise ValueError("original completed-task inventory does not verify")
        if (any(sha_file(root / name) != digest for name, digest in final["reports"].items())
                or inventory_digest(root / "queue") != final["queue_inventory_sha256"]):
            raise ValueError("finalized scale or queue evidence changed")
        feature_root = run_root / candidate / "features"
        feature = json.loads((feature_root / "report.json").read_bytes())
        if (sha_file(feature_root / "report.json") != plan["feature_receipt_sha256"]
                or sha_file(feature_root / "features.npz") != plan["feature_archive_sha256"]
                or feature["feature_identity"] != plan["feature_identity"]):
            raise ValueError("feature archive or receipt differs from the completed study")
        receipts[candidate] = {"task_count": len(tasks), "feature_identity": plan["feature_identity"],
            "study_plan_sha256": sha_file(root / "study-plan.json"),
            "summary_sha256": sha_file(root / "summary.json"),
            "required_code": {**plan["source_code_sha256"], **final["plan"]["code"]}}
    return receipts


def git_code_manifest(repo, commit, tree, studies):
    if any(re.fullmatch(r"[0-9a-f]{40}", value) is None for value in (commit, tree)):
        raise ValueError("immutable full Git commit and tree SHA required")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])
    if git("rev-parse", commit + "^{tree}").decode().strip() != tree:
        raise ValueError("Git commit/tree relation differs")
    names = git("ls-tree", "-r", "--name-only", commit, "qa/stem-bakeoff").decode().splitlines()
    names = [name for name in names if PurePosixPath(name).parent == PurePosixPath("qa/stem-bakeoff")
             and (name.endswith((".py", ".json")) or name.endswith("requirements-real.txt"))]
    hashes = {name: hashlib.sha256(git("show", f"{commit}:{name}")).hexdigest() for name in names}
    if "qa/stem-bakeoff/package_cell_evidence.py" not in hashes:
        raise ValueError("immutable code commit must include the evidence verification/restore tool")
    if hashes["qa/stem-bakeoff/package_cell_evidence.py"] != sha_file(__file__):
        raise ValueError("running packager differs from the immutable code commit")
    for receipt in studies.values():
        for name, expected in receipt["required_code"].items():
            if hashes.get("qa/stem-bakeoff/" + name) != expected:
                raise ValueError("provided Git commit does not contain the exact measured implementation")
    return {"repository": REPOSITORY, "commit": commit, "tree": tree, "code_sha256": hashes}


def collect_files(repo, roots):
    entries = {}
    for label, source in roots.items():
        safe_name(label)
        source = Path(source)
        if source.is_symlink():
            raise ValueError("evidence input roots may not be links")
        source = source.resolve()
        if source.is_relative_to(Path(repo).resolve()):
            raise ValueError("repository-backed files must remain in Git, not the data download")
        paths = [source] if source.is_file() else sorted(source.rglob("*"))
        if not source.exists():
            raise ValueError("missing evidence input root")
        for path in paths:
            if path.is_symlink():
                raise ValueError("evidence may not contain links")
            if not path.is_file():
                continue
            if path.suffix in (".py", ".rs", ".safetensors", ".pt", ".bin") or "__pycache__" in path.parts:
                raise ValueError("source code, checkpoint weights or caches are excluded from this data archive")
            name = label if source.is_file() else label + "/" + path.relative_to(source).as_posix()
            safe_name(name)
            if name in entries or path.stat().st_size > MAX_OBJECT_BYTES:
                raise ValueError("duplicate logical path or oversized evidence object")
            entries[name] = path
    return entries


def _tar_member(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def recipe(git):
    return ("# Reproduce and verify this evidence\n\n"
        "This is an immutable data snapshot. Repository source and public model checkpoints are excluded.\n\n"
        f"Code repository: {git['repository']}\n\nCommit: `{git['commit']}`\n\nTree: `{git['tree']}`\n\n"
        "1. Check out that commit and install its pinned research dependencies.\n"
        "2. Run `qa/stem-bakeoff/package_cell_evidence.py verify --archive FILE --index INDEX`.\n"
        "3. Run the same tool with `restore --archive FILE --index INDEX --output RESTORED`.\n"
        "4. `RESTORED/dataset` contains the prepared corpus and protocol; `RESTORED/run` contains both\n"
        "   feature archives, complete curves, private weights, training inputs and source recovery evidence.\n"
        "5. Re-run `real_cell_study.py` with the restored dataset/features and a NEW output directory.\n"
        "   Existing receipts retain original absolute source paths as provenance and are not rewritten.\n"
        "6. Individual heads replay using `cell_learning_curve.py replay` with their saved manifest identity\n"
        "   and holdout_features.npy. Full Encoder regeneration uses the checkpoint revision/hash pins\n"
        "   in feature receipts and real_encoder_candidates.json at the pinned Git commit.\n\n"
        "Logical paths that shared identical bytes use one archive object. Restore recreates ordinary\n"
        "independent files; it does not create symlinks, hardlinks, or rewrite recorded receipts.\n").encode()


def package(entries, output, provenance):
    output = Path(output)
    stem = output.name.removesuffix(".tar.gz")
    index_path, manifest_path = output.with_name(stem + ".index.json"), output.with_name(stem + ".manifest.json.gz")
    if not entries or any(path.exists() for path in (output, index_path, manifest_path)):
        raise ValueError("nonempty evidence and new archive/index destinations required")
    objects, files = {}, []
    for name, path in sorted(entries.items()):
        safe_name(name)
        digest, size = sha_file(path), path.stat().st_size
        if size > MAX_OBJECT_BYTES:
            raise ValueError("evidence object exceeds bound")
        objects.setdefault(digest, (path, size))
        files.append({"path": name, "sha256": digest, "bytes": size})
    manifest = {"schema": SCHEMA, **provenance, "files": files, "file_count": len(files),
        "object_count": len(objects), "logical_file_bytes": sum(item["bytes"] for item in files),
        "unique_object_bytes": sum(size for _, size in objects.values()),
        "archive_kind": "lossless experiment data; no repository source or public checkpoint weights"}
    manifest_bytes, instructions = canonical(manifest), recipe(provenance["git"])
    created = []
    try:
        raw = output.open("xb")
        created.append(output)
        with raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
                _tar_member(tar, "manifest.json", manifest_bytes)
                _tar_member(tar, "REPRODUCE.md", instructions)
                for digest, (path, size) in sorted(objects.items()):
                    data = path.read_bytes()
                    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("evidence source changed while packaging")
                    _tar_member(tar, "objects/" + digest, data)
        if output.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("compressed data archive exceeds the 500 MB limit")
        if any(sha_file(entries[item["path"]]) != item["sha256"] for item in files):
            raise ValueError("evidence sources changed before the archive was sealed")
        raw = manifest_path.open("xb")
        created.append(manifest_path)
        with raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(manifest_bytes)
        index = {"schema": SCHEMA, "archive": {"name": output.name, "bytes": output.stat().st_size, "sha256": sha_file(output)},
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "manifest_gzip": {"name": manifest_path.name, "bytes": manifest_path.stat().st_size, "sha256": sha_file(manifest_path)},
            "recipe_sha256": hashlib.sha256(instructions).hexdigest(), "git": provenance["git"],
            **{key: manifest[key] for key in ("file_count", "object_count", "logical_file_bytes", "unique_object_bytes")}}
        with index_path.open("xb") as stream:
            created.append(index_path)
            stream.write(canonical(index))
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return index


def verify(archive, index_path, restore=None):
    archive, index_path = Path(archive), Path(index_path)
    if index_path.stat().st_size > 4 * 1024**2:
        raise ValueError("oversized external evidence index")
    index = json.loads(index_path.read_bytes())
    if (index.get("schema") != SCHEMA or archive.stat().st_size != index["archive"]["bytes"]
            or archive.stat().st_size > MAX_ARCHIVE_BYTES or sha_file(archive) != index["archive"]["sha256"]):
        raise ValueError("archive differs from the external hash index")
    destination = None if restore is None else Path(restore)
    if destination is not None and destination.exists():
        raise ValueError("restoration requires a new destination")
    seen, expected, manifest = set(), {}, None
    with tarfile.open(archive, "r|gz") as tar:
        for position, member in enumerate(tar):
            if not member.isfile() or not 0 <= member.size <= MAX_OBJECT_BYTES:
                raise ValueError("unexpected archive member type or size")
            data = tar.extractfile(member).read()
            digest = hashlib.sha256(data).hexdigest()
            if position == 0:
                if member.name != "manifest.json" or digest != index["manifest_sha256"]:
                    raise ValueError("archive manifest changed")
                manifest = json.loads(data)
                if manifest.get("schema") != SCHEMA or manifest["git"] != index["git"]:
                    raise ValueError("manifest provenance differs from index")
                if not 1 <= len(manifest["files"]) <= 100000:
                    raise ValueError("evidence file count exceeds bound")
                names = set()
                for record in manifest["files"]:
                    name = safe_name(record["path"])
                    if (name in names or type(record["bytes"]) is not int or not 0 <= record["bytes"] <= MAX_OBJECT_BYTES
                            or type(record["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", record["sha256"]) is None):
                        raise ValueError("duplicate restoration path or malformed file identity")
                    names.add(name)
                    expected.setdefault(record["sha256"], []).append(record)
            elif position == 1:
                if member.name != "REPRODUCE.md" or digest != index["recipe_sha256"]:
                    raise ValueError("reproduction recipe changed")
            else:
                if member.name != "objects/" + digest or digest not in expected or digest in seen:
                    raise ValueError("unexpected, duplicated or corrupt evidence object")
                seen.add(digest)
                for record in expected[digest]:
                    if record["bytes"] != len(data):
                        raise ValueError("object size differs from file index")
                    if destination is not None:
                        target = destination / record["path"]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("xb") as stream:
                            stream.write(data)
    if (manifest is None or seen != set(expected)
            or type(index["file_count"]) is not int or type(index["object_count"]) is not int
            or len(manifest["files"]) != index["file_count"] or len(seen) != index["object_count"]
            or manifest["file_count"] != index["file_count"] or manifest["object_count"] != index["object_count"]):
        raise ValueError("incomplete evidence archive")
    return {"verified_files": len(manifest["files"]), "verified_objects": len(seen),
            "archive_sha256": index["archive"]["sha256"], "restored": destination is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("repo", "run-root", "dataset-root", "output", "git-commit", "git-tree"):
        build.add_argument("--" + name, required=True)
    build.add_argument("--extra", action="append", default=[], help="logical-path=external-file-or-directory")
    for command in ("verify", "restore"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("--archive", required=True)
        command_parser.add_argument("--index", required=True)
        if command == "restore":
            command_parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command != "build":
        print(json.dumps(verify(args.archive, args.index, getattr(args, "output", None)), sort_keys=True))
        return
    run_root, dataset_root = Path(args.run_root), Path(args.dataset_root)
    studies = verify_studies(run_root, dataset_root / "dataset.json")
    git = git_code_manifest(args.repo, args.git_commit, args.git_tree, studies)
    roots = {"run": run_root, "dataset": dataset_root}
    for value in args.extra:
        label, source = value.split("=", 1)
        if label in roots:
            raise ValueError("duplicate evidence root label")
        roots[label] = Path(source)
    entries = collect_files(args.repo, roots)
    index = package(entries, args.output, {"git": git, "studies": studies})
    if collect_files(args.repo, roots) != entries or verify_studies(run_root, dataset_root / "dataset.json") != studies:
        raise ValueError("input tree changed while packaging; archive is not approved for delivery")
    print(json.dumps(index, sort_keys=True))


if __name__ == "__main__":
    main()
