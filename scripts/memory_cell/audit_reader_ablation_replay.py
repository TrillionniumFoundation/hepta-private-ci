"""Replay archived matched-reader and literal-survival conclusions, without models.

Usage: python audit_reader_ablation_replay.py INPUTS.zip SMOL.zip QWEN.zip RECEIPT.json
All three source ZIPs are exact original GitHub Actions artifacts. No retraining.
"""

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
SCORE_ONLY = {
    "parsed_identifier",
    "strict_task_success",
    "required_sources_covered",
    "procedure_verification",
}


def require(test, message):
    if not test:
        raise ValueError(message)


def load_zip(path, expected):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink() and path.stat().st_size < 4_000_000,
        "missing or oversized original ZIP",
    )
    require(
        hashlib.sha256(path.read_bytes()).hexdigest() == expected,
        "original ZIP SHA-256 drift",
    )
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        require(
            1 < len(entries) < 100 and sum(x.file_size for x in entries) < 16_000_000,
            "ZIP population/size bound",
        )
        files = {}
        for e in entries:
            pos = PurePosixPath(e.filename)
            require(
                not e.is_dir()
                and not pos.is_absolute()
                and ".." not in pos.parts
                and "\\" not in e.filename
                and str(pos) == e.filename
                and not stat.S_ISLNK(e.external_attr >> 16)
                and e.filename not in files,
                "duplicate, traversal or symlink member",
            )
            files[e.filename] = z.read(e.filename)
    manifest = {}
    for line in files["SHA256SUMS"].decode().splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        require(m is not None, "malformed signed member census")
        sha, name = m.groups()
        require(name not in manifest, "repeated member digest")
        manifest[name] = sha
    require(set(manifest) == set(files) - {"SHA256SUMS"}, "incomplete inner census")
    for name, checksum in manifest.items():
        require(
            hashlib.sha256(files[name]).hexdigest() == checksum,
            "original member bytes drift: " + name,
        )
    return files


def original_rows(files):
    raw_data = files["run/raw-answers.jsonl"]
    require(raw_data.endswith(b"\n"), "torn original raw answer journal")
    raw = [json.loads(line) for line in raw_data.splitlines()]
    scored = json.loads(files["run/scored-answers.json"])
    require(len(raw) == len(scored) == 48, "incomplete eight-by-six real reader run")
    rows = {}
    for a, b in zip(raw, scored):
        require(
            a == {k: v for k, v in b.items() if k not in SCORE_ONLY},
            "answer, prompt or evidence changed in post-generation scoring",
        )
        key = b["question_id"], b["arm"]
        require(
            key not in rows
            and key[1] in ARMS
            and b["status"] == "succeeded"
            and type(b["strict_task_success"]) is bool,
            "duplicate or unverifiable original inference",
        )
        require(
            b["receipt"]["token_limit"] == 2048
            and b["receipt"]["semantic_sufficiency"] is None
            and b["receipt"]["independent_semantic_review"] is False,
            "token/reviewer provenance drift",
        )
        rows[key] = b
    require(
        len(rows) == 48
        and Counter(arm for _, arm in rows) == Counter({arm: 8 for arm in ARMS}),
        "incomplete registered arms",
    )
    return (
        json.loads(files["run/execution.json"]),
        rows,
        hashlib.sha256(raw_data).hexdigest(),
    )


def replay(sources, small, reference, receipt):
    artifacts = receipt["exact_artifact_sha256"]
    files = (
        load_zip(sources, artifacts["authored_source"]),
        load_zip(small, artifacts["smollm2_1_7b"]),
        load_zip(reference, artifacts["qwen2_5_3b"]),
    )
    a, smol, smol_hash = original_rows(files[1])
    b, qwen, qwen_hash = original_rows(files[2])
    require(
        a["plan_sha"] == b["plan_sha"] == receipt["inherited_plan_sha256"],
        "not a matched originally frozen plan",
    )
    labels = {
        item["id"]: item
        for item in json.loads(files[0]["observations/labels.json"])
        if item["phase"] == "test"
    }
    require(
        len(labels) == 8
        and {q for q, _ in smol} == set(labels)
        and set(smol) == set(qwen),
        "original eight evaluation labels drift",
    )
    require(
        smol_hash == receipt["original_raw_journal_sha256"]["smollm2_1_7b"]
        and qwen_hash == receipt["original_raw_journal_sha256"]["qwen2_5_3b"],
        "source raw journal identity mismatch",
    )
    paired = 0
    for key in smol:
        left, right = smol[key], qwen[key]
        require(
            left["selected"] == right["selected"]
            and left["candidate_digest"] == right["candidate_digest"]
            and left["receipt"]["bundle_digest"] == right["receipt"]["bundle_digest"]
            and left["receipt"]["delivered_evidence"]
            == right["receipt"]["delivered_evidence"]
            and left["receipt"]["derived_evidence"]
            == right["receipt"]["derived_evidence"],
            "reader capacity comparison changed delivered evidence",
        )
        paired += 1
    require(
        paired == receipt["paired_delivered_evidence_identical"] == 48,
        "lost matched source identity",
    )
    results = {}
    observations = []
    for model, rows in (("smollm2_1_7b", smol), ("qwen2_5_3b", qwen)):
        scores = {}
        for arm in ARMS:
            scores[arm] = 0
            for q in labels:
                row = rows[q, arm]
                require(
                    row["kind"] == labels[q]["kind"]
                    and (
                        not row["strict_task_success"]
                        or row["parsed_identifier"] == labels[q]["expected"]
                    ),
                    "scored task contradicts original observed program label",
                )
                scores[arm] += row["strict_task_success"]
        require(
            scores == receipt["correctness_by_arm_on_eight_authored_cases"][model],
            "reported original task successes differ",
        )
        results[model] = scores
    for q, label in sorted(labels.items()):
        view = qwen[q, "without_prerequisite"]["receipt"]["delivered_evidence"]
        literal = any(label["expected"] in item["excerpt"] for item in view)
        alternatives = set(
            re.findall(
                r"(?:site|mode)_[0-9a-f]{8}", "\n".join(e["excerpt"] for e in view)
            )
        )
        observations.append(
            {
                "id": q,
                "kind": label["kind"],
                "answer_literal_survives": literal,
                "source_count": len(view),
                "smol_correct": smol[q, "without_prerequisite"]["strict_task_success"],
                "qwen_correct": qwen[q, "without_prerequisite"]["strict_task_success"],
            }
        )
        require(
            len(alternatives) == (1 if literal else 0),
            "more/less literal alternatives than historically reported",
        )
    require(
        observations
        == sorted(receipt["ablation_original_evidence_cases"], key=lambda x: x["id"]),
        "original answer visibility confound not reproducible",
    )
    return {
        "model_calls": 0,
        "matched_original_evidence_rows": paired,
        "matched_reader_successes": results,
        "literal_mask_cases": observations,
        "production_accepted": False,
    }


def main():
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: audit_reader_ablation_replay.py "
            "SOURCES.zip SMOL.zip QWEN.zip RECEIPT.json"
        )
    receipt = json.loads(Path(sys.argv[4]).read_bytes())
    print(json.dumps(replay(*sys.argv[1:4], receipt), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
