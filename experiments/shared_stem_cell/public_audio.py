"""Explicit public speech acquisition -> existing frozen Whisper/Cell pipeline.

A speaker-disjoint FSDD development profile, NOT the dataset's standard split,
independent future evidence, speaker identification, or speech generation.
The released class labels stratify the fixed manifest but NEVER enter a tower.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
from pathlib import Path
import stat
from urllib.request import Request, urlopen
import wave
from zipfile import ZipFile

import numpy as np
import torch

from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell.public_smoke import stage_model

DATA_REPO = "Jakobovski/free-spoken-digit-dataset"
DATA_REVISION = "d6938f9bf1545aa66d8489fc9f1385a7abd64282"  # v1.0.10
RECORDINGS_TREE = "d04322e322a9f937f6f4f7c8546693755184df5b"
README_BLOB = "2c847156ef920ba39431a5c5c8825b4e8b5bd852"
MODEL = "openai/whisper-tiny.en"
MODEL_REVISION = "60c8e2222f9c090f473c11c73926baf0a56ed3f9"
SPEAKERS = {"train": ("george", "jackson", "lucas", "nicolas"),
            "calibration": ("theo",), "holdout": ("yweweler",)}
SCOPE = "public-fsdd-spoken-content-research"
MAX_ARCHIVE = 64 * 1024**2
MAX_WAV = 256 * 1024


def git_blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def fixed_rows():
    """Declared class-balanced indices, no selection based on audio/model results."""
    rows = []
    for split, speakers in SPEAKERS.items():
        for speaker in speakers:
            for digit in range(10):
                for index in range(5, 9):
                    name = f"{digit}_{speaker}_{index}.wav"
                    rows.append({"source_name": name, "speaker": speaker, "split": split,
                                 "case_id": e.sha((DATA_REVISION + ":" + name).encode())})
    return rows


def verify_tree(record, expected=RECORDINGS_TREE):
    """Recompute the publisher's entire flat recordings Git tree before download."""
    if (not isinstance(record, dict) or record.get("truncated") is not False
            or not isinstance(record.get("tree"), list) or not 1 <= len(record["tree"]) <= 4096):
        raise e.InputError("complete bounded recordings tree required")
    entries, tree = {}, bytearray()
    for item in sorted(record["tree"], key=lambda row: row["path"].encode()):
        name, digest = item["path"], item["sha"]
        if (not isinstance(name, str) or not name.isascii() or Path(name).name != name
                or not name.endswith(".wav") or "\0" in name or name in entries
                or item.get("type") != "blob" or item.get("mode") != "100644"
                or type(item.get("size")) is not int or not 44 <= item["size"] <= MAX_WAV
                or not isinstance(digest, str) or len(digest) != 40
                or any(c not in "0123456789abcdef" for c in digest)):
            raise e.InputError("ordinary bounded WAV tree member required")
        entries[name] = item
        tree.extend(b"100644 " + name.encode() + b"\0" + bytes.fromhex(digest))
    actual = hashlib.sha1(b"tree " + str(len(tree)).encode() + b"\0" + tree).hexdigest()
    if actual != expected or record.get("sha") != expected:
        raise e.InputError("publisher recordings tree identity drift")
    return entries


def convert_wav(raw):
    """Declared 8k -> 16k polyphase FIR and PCM16 requantization, no trimming."""
    from scipy.signal import resample_poly
    import scipy
    if not isinstance(raw, bytes) or not 44 <= len(raw) <= MAX_WAV:
        raise e.InputError("bounded source WAV required")
    with wave.open(io.BytesIO(raw), "rb") as source:
        n = source.getnframes()
        if (source.getnchannels() != 1 or source.getsampwidth() != 2
                or source.getframerate() != 8000 or source.getcomptype() != "NONE"
                or not 160 <= n <= 32000):
            raise e.InputError("source must be 20ms..4s mono 8kHz PCM16")
        pcm = source.readframes(n)
        if len(pcm) != 2 * n:
            raise e.InputError("truncated source PCM")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768.0
    result = resample_poly(samples, 2, 1, window=("kaiser", 5.0), padtype="constant")
    if len(result) != 2 * n or not np.isfinite(result).all():
        raise e.InputError("invalid explicit resampling output")
    quantized = np.rint(result * 32768)
    clipped = int(((quantized < -32768) | (quantized > 32767)).sum())
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1); target.setsampwidth(2); target.setframerate(16000)
        target.writeframes(np.clip(quantized, -32768, 32767).astype("<i2").tobytes())
    converted = output.getvalue()
    media.audio_bytes(converted)  # keep the original strict inference contract
    return converted, {"source_sha256": e.sha(raw), "source_pcm_sha256": e.sha(pcm),
        "converted_sha256": e.sha(converted), "source_samples": n, "samples": 2*n,
        "source_rate_hz": 8000, "rate_hz": 16000, "clipped_samples": clipped,
        "method": "scipy.resample_poly(up=2,down=1,kaiser=5,zero_padding); round+clip_PCM16",
        "scipy_version": scipy.__version__, "amplitude_normalization": False}


def read_url(url, maximum):
    request = Request(url, headers={"User-Agent": "hepta-public-audio-research"})
    with urlopen(request, timeout=60) as response:
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise e.InputError("public acquisition exceeds byte budget")
    return payload


def acquire(root, *, _read=read_url):
    """No downloaded code is executed. Only pinned selected audio/README is copied."""
    tree_raw = _read(f"https://api.github.com/repos/{DATA_REPO}/git/trees/{RECORDINGS_TREE}", 2*1024**2)
    entries = verify_tree(e.decode(tree_raw))
    (root / "recordings-tree.json").write_bytes(tree_raw)
    rows = fixed_rows()
    if any(row["source_name"] not in entries for row in rows):
        raise e.InputError("predeclared recording missing; no replacement")
    e.write_once(root / "source-selection.json", rows)
    payload = _read(f"https://codeload.github.com/{DATA_REPO}/zip/{DATA_REVISION}", MAX_ARCHIVE)
    prefix = f"free-spoken-digit-dataset-{DATA_REVISION}/"
    records, receipts, seen_pcm = [], [], set()
    audio = root / "audio"
    audio.mkdir(exist_ok=False)
    with ZipFile(io.BytesIO(payload)) as archive:
        info = archive.infolist()
        if (len(info) > 4096 or len({i.filename for i in info}) != len(info)
                or sum(i.file_size for i in info) > 128*1024**2
                or any(i.file_size > MAX_WAV or not i.filename.startswith(prefix)
                       or ".." in Path(i.filename).parts or "\\" in i.filename
                       or stat.S_ISLNK(i.external_attr >> 16) for i in info)):
            raise e.InputError("unsafe or oversized public archive inventory")
        readme = archive.read(prefix + "README.md")
        if git_blob(readme) != README_BLOB:
            raise e.InputError("source attribution identity drift")
        (root / "FSDD-README.txt").write_bytes(readme)
        for row in rows:
            raw = archive.read(prefix + "recordings/" + row["source_name"])
            declared = entries[row["source_name"]]
            if len(raw) != declared["size"] or git_blob(raw) != declared["sha"]:
                raise e.InputError("publisher audio blob drift")
            converted, receipt = convert_wav(raw)
            if receipt["source_pcm_sha256"] in seen_pcm:
                raise e.InputError("duplicated decoded audio; no answer-informed replacement")
            seen_pcm.add(receipt["source_pcm_sha256"])
            path = audio / (row["case_id"] + ".wav")
            path.write_bytes(converted)
            receipts.append({**row, **receipt, "publisher_git_blob": declared["sha"]})
            records.append({"case_id": row["case_id"], "group": "speaker:" + row["speaker"],
                "split": row["split"], "scope": SCOPE, "observed_at": None,
                "inputs": {"audio": {"path": path.relative_to(root).as_posix(),
                                      "sha256": receipt["converted_sha256"]}},
                "label": int(row["source_name"][0])})
    if Counter(r["split"] for r in records) != {"train": 160, "calibration": 40, "holdout": 40}:
        raise e.InputError("fixed speaker-stratified denominator changed")
    raw = b"".join(e.canonical(r) for r in records)
    (root / "dataset.jsonl").write_bytes(raw)
    e.write_once(root / "audio-provenance.json", {"archive_sha256": e.sha(payload),
        "recordings_tree": RECORDINGS_TREE, "license": "CC-BY-SA-4.0",
        "source": f"https://github.com/{DATA_REPO}/tree/{DATA_REVISION}",
        "records": receipts, "source_speaker_disjoint": True, "independent_evaluation": False,
        "pretraining_clean": False, "production_accepted": False})
    return {"path": "dataset.jsonl", "sha256": e.sha(raw)}


def run(root, *, _acquire=acquire, _stage=stage_model, _towers=media.LocalTowers):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.public-audio-plan.v1", "model": MODEL, "model_revision": MODEL_REVISION,
        "dataset_revision": DATA_REVISION, "recordings_tree": RECORDINGS_TREE,
        "speakers": SPEAKERS, "indices_per_digit_per_speaker": [5, 6, 7, 8],
        "fixed_cohort": {"train": 160, "calibration": 40, "holdout": 40},
        "classes": 10, "steps": 80, "seed": 20261014,
        "classification_target": "spoken digit content, not speaker identity",
        "released_class_balanced_sampling": True, "source_filenames_enter_model": False,
        "checkpoint_selection": "existing calibrated_checkpoints_v1, audio-only",
        "not_standard_fsdd_split": True, "new_speech_generation": False,
        "independent_evaluation": False, "production_accepted": False}
    e.write_once(root / "plan.json", plan)
    try:
        with e.measured() as acquisition:
            data = _acquire(root)
            model_root = root / "whisper"
            model_root.mkdir()
            model = _stage(model_root, MODEL, MODEL_REVISION, kind="whisper", allow_conversion=False)
        model["path"] = "whisper/model"
        manifest = {"schema": "hepta.shared-stem-media.v1", "classes": 10, "steps": 80,
            "seed": 20261014, "temporal": False, "fusion_profile": "calibrated_checkpoints_v1",
            "dataset": data, "models": {"whisper": model}}
        e.write_once(root / "manifest.json", manifest)
        result = media.run(root / "manifest.json", root / "execution", _tower_factory=_towers)
        report = {"schema": "hepta.public-audio-executed.v1", "acquisition": acquisition,
            "execution_report_sha256": e.sha((root / "execution/report.json").read_bytes()),
            "dataset_sha256": data["sha256"], "scores": result["scores"],
            "source_speaker_disjoint": True, "simulated_towers": result["simulated_towers"],
            "not_standard_fsdd_split": True, "independent_evaluation": False,
            "general_audio_understanding_established": False, "speech_generation_completed": False,
            "production_accepted": False}
        e.write_once(root / "report.json", report)
        return report
    except Exception as error:
        e.write_once(root / "failure.json", {"error": type(error).__name__, "message": str(error),
                                            "production_accepted": False})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    torch.set_num_threads(2)
    run(arguments.output)
