"""Retain original completed layout evaluation and its read-only audits."""

import hashlib
import json
import os
from pathlib import Path
import tarfile
import time

ROOT = Path(
    "/home/qian-qi/work/hepta-upstream-layout-learning-20261118-2e9b-checkpoint2"
)
SOURCE = ROOT / "source/qualification/cell-upstream-layout-learning-20261118"
COLLECTION = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b")
OUT = ROOT / "evaluation-publication-1"
RAW = OUT / "raw"
PROTOCOL_SHA = "c71f8348977e955b1d5b6b98e8780ff13188b88b141fad683efb6f08bb03814f"
READOUT_SOURCE_SHA = "997feb483dc25dd4e5a138f29cd5ef07d386794c00a02b8eedd5eedaffa8ebd7"


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(
            json.dumps(
                value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
            + b"\n"
        )


def main():
    os.nice(19)
    require(sha(SOURCE / "prepared/PROTOCOL.json") == PROTOCOL_SHA, "protocol changed")
    protocol = read(SOURCE / "prepared/PROTOCOL.json")
    readout_source = ROOT / "postprocess-preparation-2/readout.py"
    require(sha(readout_source) == READOUT_SOURCE_SHA, "published readout code changed")
    result = read(ROOT / "analysis-1/READOUT.json")
    calls = read(ROOT / "analysis-1/CALLS.json")
    require(
        result["new_generation_calls"] == 56
        and result["reused_generation_calls"] == 8
        and len(calls) == 64
        and result[
            "strict_original_receipts_recomputed_without_model_or_verifier_calls"
        ],
        "complete original 56 plus eight readout required",
    )
    for phase in ("training", "evaluation_A", "evaluation_B3"):
        owner = read(ROOT / ("owned-" + phase + "-1/COMPLETE.json"))
        require(
            owner["status"] == "COMPLETE"
            and all(
                x["wait_returncode"] == 0 and not x["timed_out"]
                for x in owner["stage_exits"]
            ),
            "original owner did not complete: " + phase,
        )
    OUT.mkdir(exist_ok=False)
    RAW.mkdir()
    entries = []
    copied = set()

    def copy(original, relative):
        original = Path(original)
        relative = Path(relative)
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "unsafe archive path",
        )
        require(
            original.is_file() and not original.is_symlink(),
            "ordinary original required",
        )
        target = RAW / relative
        original_bytes = original.read_bytes()
        expected = hashlib.sha256(original_bytes).hexdigest()
        if str(relative) in copied:
            require(sha(target) == expected, "conflicting duplicate original")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(original_bytes)
        require(
            sha(target) == expected == sha(original),
            "original changed during retention",
        )
        entries.append(
            {
                "path": str(relative),
                "source_path": str(original),
                "bytes": len(original_bytes),
                "sha256": expected,
            }
        )
        copied.add(str(relative))

    def copy_tree(original, relative):
        original = Path(original)
        for path in sorted(original.rglob("*")):
            if "__pycache__" in path.parts:
                continue
            require(not path.is_symlink(), "unexpected evidence symlink: " + str(path))
            if path.is_file():
                copy(path, Path(relative) / path.relative_to(original))

    for directory in (
        "evaluation/A",
        "evaluation/B3",
        "owned-evaluation_A-1",
        "owned-evaluation_B3-1",
        "analysis-1",
        "a-mechanism-1",
        "a-mechanism-preparation-1",
        "structured-interface-survey-1",
    ):
        copy_tree(ROOT / directory, directory)
    for name, expected in protocol["candidate_files"].items():
        require(sha(SOURCE / name) == expected, "frozen candidate changed: " + name)
        copy(SOURCE / name, Path("execution-source") / name)
    copy(SOURCE / "prepared/PROTOCOL.json", "execution-source/prepared/PROTOCOL.json")
    for original, expected in protocol["A_parent_reuse_files"].items():
        require(sha(original) == expected, "precommitted parent original changed")
    copy_tree(COLLECTION / "results/P", "reused-A-P/results")
    for name in (
        "B3_BINDING.json",
        "TRAINING_DEPLOYMENT.json",
        "TRAINING_ADMISSION.json",
    ):
        copy(ROOT / name, name)
    binding = read(ROOT / "B3_BINDING.json")
    for name in ("tasks", "protocol", "loader", "release"):
        original = Path(binding[name + "_path"])
        expected = (
            binding["release_sha256"]
            if name == "release"
            else protocol["B3_commitment"][name + "_sha256"]
        )
        require(sha(original) == expected, "B3 binding changed: " + name)
        copy(original, Path("released-B3") / original.name)
    for mode in ("document_evidence", "native_feedback"):
        for name in ("manifest.json", "TRAINING.json"):
            copy(ROOT / "retained" / mode / name, Path("frozen-training") / mode / name)
    copy(ROOT / "retained/WEIGHTS_FROZEN.json", "frozen-training/WEIGHTS_FROZEN.json")
    copy(ROOT / "training-publication-1/ARCHIVE.json", "frozen-training/ARCHIVE.json")
    copy(ROOT / "owned-training-1/COMPLETE.json", "frozen-training/OWNER_COMPLETE.json")
    copy(readout_source, "postprocess/readout.py")
    copy(Path(__file__), "collection-source/collect_evaluation.py")
    for label, session in (
        ("A", "dpty-0fbb3f468c0137386392046705b2cb3ce46757b22c717842a1a174cd06bebf8b"),
        ("B3", "dpty-1d99d9214c6f77a4d6234c0d77a9f33b2e43f60de1135fd1157b346ca82f0f59"),
    ):
        original = (
            Path("/home/qian-qi/.local/state/hepta-runtime-mac-worker/terminals")
            / session
            / "output.log"
        )
        copy(original, Path("original-owner-terminals") / label / "output.log")
    entries.sort(key=lambda row: row["path"])
    index = {
        "schema": "hepta.layout-evaluation-complete-raw-index.v1",
        "files": len(entries),
        "entries": entries,
        "uncompressed_bytes": sum(x["bytes"] for x in entries),
        "excluded_generated_caches": ["__pycache__"],
        "no_original_scores_changed": True,
        "new_model_calls": 0,
        "new_verifier_calls": 0,
    }
    write(OUT / "INDEX.json", index)
    archive = OUT / "ACTUAL_EVALUATION.tar.xz"
    with tarfile.open(archive, "x:xz", preset=6) as stream:
        for row in entries:
            stream.add(RAW / row["path"], arcname=row["path"], recursive=False)
    with tarfile.open(archive, "r:xz") as stream:
        members = stream.getmembers()
        require(len(members) == len(entries), "archive member count differs")
        actual = {member.name: member for member in members}
        require(set(actual) == copied, "archive membership differs")
        for row in entries:
            payload = stream.extractfile(actual[row["path"]]).read()
            require(
                len(payload) == row["bytes"]
                and hashlib.sha256(payload).hexdigest() == row["sha256"],
                "archive member changed",
            )
    payload = archive.read_bytes()
    metadata = {
        "schema": "hepta.layout-evaluation-complete-archive.v1",
        "created_at_ns": str(time.time_ns()),
        "path": str(archive),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "git_blob_sha1": hashlib.sha1(
            b"blob " + str(len(payload)).encode() + b"\0" + payload
        ).hexdigest(),
        "index_sha256": sha(OUT / "INDEX.json"),
        "readout_sha256": sha(ROOT / "analysis-1/READOUT.json"),
        "all_archive_members_verified": True,
        "new_model_calls": 0,
        "new_verifier_calls": 0,
        "original_new_generations": 56,
        "original_reused_generations": 8,
        "research_decision": result["research_decision"],
        "full_system_cost_known": False,
    }
    write(OUT / "ARCHIVE.json", metadata)
    print(json.dumps(metadata, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
