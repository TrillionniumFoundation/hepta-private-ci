"""Preserve every new natural-task path once per verified content identity."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import time


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def package(workspace, output, limit):
    code = Path(__file__).resolve().parent
    previous_code = code.parents[1] / "continuation_20261027/natural"
    recovery = json.loads((code / "evidence/MODEL_RECOVERY.json").read_text())
    for name in ("video-qualification-001", "document-qualification-001", "speech-qualification-001", "document-replication-001", "speech-timer-correction-001"):
        result = json.loads((workspace / "natural-v2-runs" / name / "RESULT.json").read_text())
        if result["status"] != "completed":
            raise ValueError("Cannot package an unfinished scientific run")
    for name in ("INDEPENDENT_OUTPUT_AUDIT.json", "INDEPENDENT_REPLICATION_AUDIT.json"):
        if json.loads((code / "evidence" / name).read_text())["status"] != "passed":
            raise ValueError("Independent delivered-output verification is required")
    for name in ("INDEPENDENT_TIMER_CORRECTION_AUDIT.json", "PEER_NATURAL.json", "PEER_MERCHANT_MAPPING_REVIEW.json", "PEER_ALIAS_STATISTICS.json"):
        if not json.loads((code / "evidence" / name).read_text())["passed"]:
            raise ValueError("Timer or entity-identity review is not complete")
    for row in recovery["models"]:
        path = workspace / row["relative_path"]
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise ValueError("External model recovery identity does not match executed bytes")
    external = {r["relative_path"] for r in recovery["models"]}
    paths = set()
    for root in (workspace / "natural-v2-assets", workspace / "natural-v2-runs", code):
        paths.update(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths.update(workspace.glob("natural-v2-*.log"))
    paths.update(workspace.glob("natural-v2-media-deduplication-*.json"))
    for filename in ("common.py", "speech_engine.py", "video_generator.py", "document_engine.py",
            "document_decoder.py", "document_study.py", "restore_evidence.py", "recover_models.py"):
        paths.add(previous_code / filename)
    repair = code.parents[1] / "repair_20261026/natural"
    paths.update([repair / "speech.py", repair / "document/ocr.py", repair / "document/run.py",
        repair / "document/evidence/SOURCE_MANIFEST.json"])
    # Include every original source actually used by this development, plus its
    # frozen manifest and original video containers. Historical qualification
    # outputs are already separately archived and are not dependencies here.
    old_assets = workspace / "natural-continuation-assets"
    for kind in ("document", "video", "speech", "cascade"):
        manifest_path = old_assets / kind / "MANIFEST.json"
        paths.add(manifest_path)
        manifest = json.loads(manifest_path.read_text())
        if kind == "document":
            paths.update(Path(r["path"]) for r in manifest["documents"] if r["role"] in ("fit", "validation"))
        elif kind == "video":
            for row in manifest["samples"]:
                if row["role"] in ("train", "validation"):
                    paths.update(Path(row[k]) for k in ("left", "right", "private_target"))
            paths.update(Path(r["path"]) for r in manifest["clips"] if r["role"] == "development")
        elif kind == "cascade":
            paths.update(Path(r["path"]) for r in manifest["speech"] if r["role"] in ("train", "validation"))
            paths.update(p for p in Path(manifest["base_model_directory"]).iterdir() if p.is_file() and p.name != "model.bin")
    language = workspace / "natural-v2-dependencies/eng.traineddata"
    language.parent.mkdir(parents=True, exist_ok=True)
    original_language = Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata")
    expected_language = json.loads((code / "evidence/RUNTIME.json").read_text())["ocr_language"]
    if original_language.stat().st_size != expected_language["bytes"] or digest(original_language) != expected_language["sha256"]:
        raise ValueError("OCR language checkpoint no longer matches the executed runtime")
    if not language.exists():
        shutil.copyfile(original_language, language)
    if digest(language) != digest(original_language):
        raise ValueError("OCR language checkpoint identity differs")
    paths.add(language)
    records, blobs = [], {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file() or not path.is_relative_to(workspace):
            raise ValueError("Evidence path is missing, a symlink or outside the workspace")
        relative = str(path.relative_to(workspace))
        if relative in external:
            raise ValueError("External model accidentally included in package set")
        identity = digest(path)
        records.append({"path": relative, "sha256": identity, "bytes": path.stat().st_size})
        blobs.setdefault(identity, path)
    index = {"schema": "hepta.ndu.natural.content-addressed-archive.v1", "created_ns": time.time_ns(),
        "recorded_workspace": str(workspace), "paths": records, "external_models": recovery["models"],
        "restore_helper_logical_path": str((previous_code / "restore_evidence.py").relative_to(workspace)),
        "scope": "All new source media including official DAVIS range evidence, new development and all qualifications, one fixed 128-merchant replication, exact executed-source snapshots, checkpoints, logs and audits; original development inputs and source dependencies are included. One public 145 MB Whisper model remains explicitly external. The separate native-owner study referenced by PEER_CONTROL has its own evidence package."}
    encoded = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode()
    if output.exists():
        raise FileExistsError("Preserve existing evidence archives")
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        member = tarfile.TarInfo("INDEX.json")
        member.size, member.mtime = len(encoded), 0
        archive.addfile(member, io.BytesIO(encoded))
        for identity, path in sorted(blobs.items()):
            member = tarfile.TarInfo("blobs/" + identity)
            member.size, member.mtime = path.stat().st_size, 0
            with path.open("rb") as stream:
                archive.addfile(member, stream)
            if output.stat().st_size > limit:
                raise ValueError("Archive size bound exceeded; partial archive retained")
    sidecar = output.with_suffix(output.suffix + ".index.json")
    sidecar.write_bytes(encoded)
    return {"archive": str(output), "archive_bytes": output.stat().st_size, "archive_sha256": digest(output),
        "index": str(sidecar), "index_sha256": hashlib.sha256(encoded).hexdigest(), "logical_paths": len(records),
        "unique_blobs": len(blobs), "logical_bytes": sum(r["bytes"] for r in records),
        "unique_blob_bytes": sum(p.stat().st_size for p in blobs.values()),
        "external_model_bytes": sum(r["bytes"] for r in recovery["models"])}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit-bytes", type=int, default=225000000)
    args = parser.parse_args()
    print(json.dumps(package(args.workspace.resolve(), args.output.resolve(), args.limit_bytes), indent=2))
