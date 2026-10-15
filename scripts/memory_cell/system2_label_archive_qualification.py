"""Independently re-check completed 140-call label ablation, without inference.

The generating archive and the parent evidence are externally SHA256 pinned.
Each member is bounded and independently checked against its SHA256SUMS.
Full source/evidence/model/score semantics are delegated to the pre-existing
repository post-seal audit, never to the generating run's claimed summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile

PARENT_ZIP_SHA256 = "9f4a4ed9429212b98befffca27a297780d61317eaed8be519b1cb6880037f121"
LABEL_ZIP_SHA256 = "a278014bae564336fc4d63335154cadbf14febc73620d958f45648b17ca0622a"
LABEL_COMMIT = "24a1175958870816e40c7c62bbe1421b83e55dbd"
LABEL_TREE = "84689f6c75dc35b8e9ff515be32094182438fa05"
LABEL_SOURCE_BLOB = "2bda45fffb874ab7b9ea122c16f2a5caf166031a"
EXPECTED_RAW_SHA256 = "6f630a86d374658049377d4611f92fd6c0dd6626c267eef7c37d77f07f5aeaa2"
REQUIRED_TRIAL = (
    "trial/plan.json",
    "trial/starts.jsonl",
    "trial/raw-answers.jsonl",
    "trial/raw-seal.json",
    "trial/scored.json",
    "trial/summary.json",
)
SCHEMA = "hepta.system2.completed-label-archive-independent.v1"


def strict_json(blob):
    def unique(pairs):
        answer = {}
        for key, value in pairs:
            if key in answer:
                raise ValueError("duplicate JSON key")
            answer[key] = value
        return answer

    def invalid(_value):
        raise ValueError("nonfinite JSON value")

    return json.loads(blob, object_pairs_hook=unique, parse_constant=invalid)


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verified_zip(path, expected_hash):
    """Refuse unknown, modified, linked, duplicated, oversized ZIP contents."""
    path = Path(path)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        or path.is_symlink()
        or any(p.is_symlink() for p in path.parents)
        or not path.is_file()
        or path.stat().st_size > 64 * 1024**2
    ):
        raise ValueError("untrusted or oversized evidence archive")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("external evidence ZIP SHA256 mismatch")
    files = {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > 256 or sum(x.file_size for x in infos) > 256 * 1024**2:
            raise ValueError("archive member/expanded-byte budget exceeded")
        for info in infos:
            name = info.filename
            p = PurePosixPath(name)
            file_type = stat.S_IFMT(info.external_attr >> 16)
            if (
                name in files
                or not p.parts
                or p.is_absolute()
                or p.as_posix() != name
                or ".." in p.parts
                or "\\" in name
                or info.is_dir()
                or any(ord(c) < 32 for c in name)
                or file_type not in (0, stat.S_IFREG)
            ):
                raise ValueError("unsafe or duplicate archived path")
            files[name] = z.read(info)
    if "SHA256SUMS" not in files:
        raise ValueError("missing member manifest")
    manifest = {}
    for line in files["SHA256SUMS"].decode().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if match is None or match[2] in manifest:
            raise ValueError("duplicate or malformed member manifest")
        manifest[match[2]] = match[1]
    if set(manifest) != set(files) - {"SHA256SUMS"}:
        raise ValueError("manifest member census mismatch")
    if any(
        hashlib.sha256(files[name]).hexdigest() != sha for name, sha in manifest.items()
    ):
        raise ValueError("modified archive member")
    return files


def archive_receipt(label_files):
    """Census and seal are checked BEFORE importing semantic scoring code."""
    if (
        label_files.get("tested-commit.txt", b"").decode().strip() != LABEL_COMMIT
        or label_files.get("tested-tree.txt", b"").decode().strip() != LABEL_TREE
        or any(key not in label_files for key in REQUIRED_TRIAL)
        or git_blob(label_files.get("source/system2_onehop_label_ablation.py", b""))
        != LABEL_SOURCE_BLOB
    ):
        raise ValueError("original generating commit/tree/source drift")
    raw = label_files["trial/raw-answers.jsonl"]
    if hashlib.sha256(raw).hexdigest() != EXPECTED_RAW_SHA256 or strict_json(
        label_files["trial/raw-seal.json"]
    ) != dict(sha256=EXPECTED_RAW_SHA256, rows=140, scoring_started=False):
        raise ValueError("original label-answer SHA256 seal drift")
    rows = [strict_json(line) for line in raw.splitlines()]
    starts = [
        strict_json(line) for line in label_files["trial/starts.jsonl"].splitlines()
    ]
    keys = [(r.get("qid"), r.get("arm"), r.get("presentation")) for r in rows]
    start_keys = [(r.get("qid"), r.get("arm"), r.get("presentation")) for r in starts]
    if (
        len(rows) != 140
        or len(starts) != 140
        or len(set(keys)) != 140
        or len(set(start_keys)) != 140
        or set(keys) != set(start_keys)
        or len({r["qid"] for r in rows}) != 20
        or any(r.get("status") != "succeeded" for r in rows)
        or any(r.get("status") != "started" for r in starts)
    ):
        raise ValueError("incomplete or failed model execution census")
    plan = strict_json(label_files["trial/plan.json"])
    claimed = strict_json(label_files["trial/summary.json"])
    if (
        plan.get("source_commit") != LABEL_COMMIT
        or plan.get("parent_sha256") != PARENT_ZIP_SHA256
        or claimed.get("raw_sha256") != EXPECTED_RAW_SHA256
        or claimed.get("planned") != 140
        or claimed.get("recorded") != 140
        or claimed.get("failed") != 0
        or claimed.get("production_accepted") is not False
        or claimed.get("candidate_disposition") != "reader_answer_only_not_qualified"
    ):
        raise ValueError("completed label experiment plan/claim drift")
    return rows


def run(parent_zip, label_zip, output_path, *, audit_fn=None):
    """No Reader calls; the injected audit_fn is for hermetic tests only."""
    parent = verified_zip(parent_zip, PARENT_ZIP_SHA256)
    label = verified_zip(label_zip, LABEL_ZIP_SHA256)
    rows = archive_receipt(label)
    if audit_fn is None:
        from system2_onehop_label_pair_audit import audit as audit_fn
    with tempfile.TemporaryDirectory(prefix="hepta-label-audit-") as tmp:
        source = Path(tmp)
        for name in REQUIRED_TRIAL:
            path = source / name.removeprefix("trial/")
            path.write_bytes(label[name])
        semantic = audit_fn(source, parent_zip, generating_commit=LABEL_COMMIT)
    if (
        semantic.get("planned_model_calls") != 140
        or semantic.get("source_pairs") != 60
        or semantic.get("source_commit") != LABEL_COMMIT
        or semantic.get("original_seal") != EXPECTED_RAW_SHA256
        or semantic.get("candidate_disposition") != "reader_answer_only_not_qualified"
        or semantic.get("production_accepted") is not False
    ):
        raise ValueError("semantic/source audit rejected completed output")
    group = {}
    for arm in ("single_fact", "target_decoy_two_first", "decoy_one"):
        for presentation in ("labeled", "unlabeled"):
            subset = [
                r for r in rows if r["arm"] == arm and r["presentation"] == presentation
            ]
            if len(subset) != 20:
                raise ValueError("incomplete labeled or unlabeled condition")
            group[arm + ":" + presentation] = dict(
                completed=len(subset),
                decoder_at_64=sum(
                    r["reader"]["generated_tokens"] == 64 for r in subset
                ),
                input_tokens=sum(r["reader"]["input_tokens"] for r in subset),
                generated_tokens=sum(r["reader"]["generated_tokens"] for r in subset),
            )
    token_diff = {}
    for arm in ("single_fact", "target_decoy_two_first", "decoy_one"):
        by_key = {(r["qid"], r["presentation"]): r for r in rows if r["arm"] == arm}
        diffs = [
            by_key[qid, "labeled"]["reader"]["input_tokens"]
            - by_key[qid, "unlabeled"]["reader"]["input_tokens"]
            for qid in sorted({k[0] for k in by_key})
        ]
        token_diff[arm] = diffs
    result = dict(
        schema=SCHEMA,
        original_model_calls=140,
        new_model_calls=0,
        distinct_questions=20,
        source_artifact_sha256=LABEL_ZIP_SHA256,
        original_source_artifact_sha256=PARENT_ZIP_SHA256,
        original_raw_answer_sha256=EXPECTED_RAW_SHA256,
        verified_completed_member_files=len(label) - 1,
        verified_parent_member_files=len(parent) - 1,
        conditions=group,
        labeled_minus_unlabeled_input_token_diff=token_diff,
        paired_semantic_report=semantic,
        disposition="reject_no_answer_or_refusal_gain",
        causal_label_effect_established=False,
        decoder_saturation_establishes_reader_adequacy=False,
        independent_natural_language_verification=False,
        production_accepted=False,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parent_archive", type=Path)
    parser.add_argument("label_archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(args.parent_archive, args.label_archive, args.output)
    print(
        json.dumps(
            dict(
                original_model_calls=result["original_model_calls"],
                new_model_calls=result["new_model_calls"],
                verified_members=result["verified_completed_member_files"],
                disposition=result["disposition"],
            )
        )
    )


if __name__ == "__main__":
    main()
