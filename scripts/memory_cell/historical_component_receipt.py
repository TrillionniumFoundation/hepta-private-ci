"""Read-only, pinned attribution of prior real reader answers.

This does NOT generate new model answers, rejudge semantic correctness, or
establish independent source-family evidence. An authored program-support
control is diagnostic, not a human-certified oracle or minimal proof.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SOURCE_COMMIT = "59f9eadd5cc919359079e04442f7343838a60057"
RUN_ID = 38063870516
ARCHIVES = {
    "smol-1.7b": "67d46247bd1881c8fb3f73ec6122415d0d15a0ec24b02f193fb1294e7ea63bae",
    "qwen-3b": "831ce9658bafcbaf04f4a15879982e58317322f7cd5137724498d7d20df7bb98",
}
ARMS = (
    "empty",
    "hybrid",
    "entity_time",
    "organized",
    "program_support",
    "without_prerequisite",
)
CONTRASTS = (
    ("entity_time_minus_hybrid", "hybrid", "entity_time"),
    ("organized_minus_entity_time", "entity_time", "organized"),
    ("program_support_minus_organized", "organized", "program_support"),
    ("organized_minus_hybrid", "hybrid", "organized"),
)
KIND = ("new_fact", "correction", "composition", "procedure")
SCORER_FIELDS = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_INNER_BYTES = 64 * 1024 * 1024


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def archive_records(path, expected_sha):
    """Validate complete transport + file census and restore original answers."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular historical archive required")
    if not 1 <= path.stat().st_size <= MAX_ZIP_BYTES:
        raise ValueError("historical archive byte bound")
    if sha(path.read_bytes()) != expected_sha:
        raise ValueError("historical transport digest drift")
    with zipfile.ZipFile(path) as artifact:
        inventory = artifact.infolist()
        if (
            not 1 <= len(inventory) <= 128
            or sum(item.file_size for item in inventory) > MAX_INNER_BYTES
        ):
            raise ValueError("historical extraction budget")
        seen = set()
        for item in inventory:
            name = item.filename
            location = PurePosixPath(name)
            if (
                location.is_absolute()
                or ".." in location.parts
                or "\\" in name
                or name.startswith("./")
                or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or str(location) in seen
                or item.file_size < 0
            ):
                raise ValueError("unsafe or duplicate historical ZIP member")
            seen.add(str(location))
        hashes = {}
        for line in artifact.read("SHA256SUMS").decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if match is None:
                raise ValueError("invalid archived SHA256SUMS")
            digest, name = match.groups()
            if (
                name in hashes
                or name not in seen
                or name == "SHA256SUMS"
                or sha(artifact.read(name)) != digest
            ):
                raise ValueError("historical file digest drift")
            hashes[name] = digest
        if set(hashes) != seen - {"SHA256SUMS"}:
            raise ValueError("partial historical archive manifest")
        if artifact.read("tested-commit.txt").decode().strip() != SOURCE_COMMIT:
            raise ValueError("wrong source of historical model generation")
        scored = json.loads(artifact.read("run/scored-answers.json"))
        original = [
            json.loads(line)
            for line in artifact.read("run/raw-answers.jsonl").decode().splitlines()
        ]
    if len(scored) != 48 or len(original) != 48:
        raise ValueError("expected every original 8x6 model answer")
    for before, after in zip(original, scored, strict=True):
        if (
            not isinstance(before, dict)
            or not isinstance(after, dict)
            or any(after.get(key) != value for key, value in before.items())
            or not set(after).difference(before).issubset(SCORER_FIELDS)
        ):
            raise ValueError("post-scoring source, prompt or answer mutation")
    return scored, dict(
        zip_sha256=expected_sha,
        scored_sha256=hashes["run/scored-answers.json"],
        raw_sha256=hashes["run/raw-answers.jsonl"],
        archived_files=len(hashes),
    )


def compare(records):
    """Decompose paired outcomes on the full authored census only."""
    groups = {}
    profile = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("non-object historical answer")
        qid, arm = row["question_id"], row["arm"]
        if (
            arm not in ARMS
            or row["status"] != "succeeded"
            or type(row.get("strict_task_success")) is not bool
            or type(row.get("required_sources_covered")) is not bool
            or not isinstance(row.get("selected"), list)
            or len(row["selected"]) != len(set(row["selected"]))
        ):
            raise ValueError("invalid original model attempt")
        receipt = row["receipt"]
        profile.add(
            (
                receipt["reader_identity"],
                receipt["reader_profile"],
                receipt["token_limit"],
            )
        )
        cohort = groups.setdefault(qid, {})
        if arm in cohort:
            raise ValueError("duplicate historical question/arm")
        cohort[arm] = row
    if (
        len(groups) != 8
        or len(profile) != 1
        or any(set(rows) != set(ARMS) for rows in groups.values())
    ):
        raise ValueError("incomplete or mixed reader profile")
    kinds = Counter(rows["hybrid"]["kind"] for rows in groups.values())
    if any(kinds[category] != 2 for category in KIND) or set(kinds) != set(KIND):
        raise ValueError("changed authored task strata")
    for rows in groups.values():
        if (
            len({row["kind"] for row in rows.values()}) != 1
            or len({row["candidate_digest"] for row in rows.values()}) != 1
        ):
            raise ValueError("unmatched reader task or retrieval pool")
    contrasts = {}
    for name, left, right in CONTRASTS:
        pairs = [(rows[left], rows[right]) for rows in groups.values()]
        contrasts[name] = dict(
            wins=sum(
                not a["strict_task_success"] and b["strict_task_success"]
                for a, b in pairs
            ),
            losses=sum(
                a["strict_task_success"] and not b["strict_task_success"]
                for a, b in pairs
            ),
            identical_ordered_selection=sum(
                a["selected"] == b["selected"] for a, b in pairs
            ),
            selection_changed=sum(a["selected"] != b["selected"] for a, b in pairs),
            answer_changed=sum(a["answer"] != b["answer"] for a, b in pairs),
            left_support_already_covered=sum(
                a["required_sources_covered"] for a, b in pairs
            ),
        )
    return dict(
        planned_questions=8,
        actual_model_attempts=48,
        model_profile=next(iter(profile)),
        by_kind=dict(sorted(kinds.items())),
        success_by_arm={
            arm: sum(rows[arm]["strict_task_success"] for rows in groups.values())
            for arm in ARMS
        },
        contrasts=contrasts,
        significance_established=False,
        independent_human_review=False,
        stage4_qualification=False,
    )


def receipt(smol, qwen):
    models = {}
    for name, path in (("smol-1.7b", smol), ("qwen-3b", qwen)):
        rows, provenance = archive_records(path, ARCHIVES[name])
        models[name] = compare(rows) | dict(provenance=provenance)
    return dict(
        schema="hepta.memory-cell.historical-component-effects.v1",
        historical_workflow_run=RUN_ID,
        generating_source_commit=SOURCE_COMMIT,
        previous_model_answers_only=True,
        new_model_generations=0,
        independently_collected_families=0,
        semantic_citation_precision=None,
        graph_specific_superiority_established=False,
        parametric_memory_gain_established=False,
        production_accepted=False,
        models=models,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("smol_archive", type=Path)
    parser.add_argument("qwen_archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = receipt(args.smol_archive, args.qwen_archive)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
