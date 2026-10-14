"""Read-only, source-bound audit of the completed 200-call Qwen label placebo.

This is a finite, exposed synthetic task family: no new model calls, trained
parameters, semantic review, risk waiver, or production qualification.
"""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.system2.qwen-e-label-postseal-audit.v1"
ZIP_SHA256 = "90094839a30638f8d47b9047520c455af1a41974e61f3bfbde64b02a10a74802"
PRODUCER_SHA = "10fce5ee7f8f1fc97b59fc17ad719b1a888c2c1b"
PRODUCER_TREE = "fa68a95bfbcbfcad3e6c1656cea9215c3153a7e5"
PARENT_SHA256 = "853afed48368b2c4e562191c7ed6d6bf28492bd80ec95634119b8afc7d43ab37"
RAW_SEAL = "578098efc9e0dad7ee387538fd07eb10a9ce6e3de0f1492723dfe9f6dbd601a5"
INPUT_SEAL = "6ae1cb8cbfd78700ebb86eed4646925984280e93a5c0606fea1dce261fe567a9"
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "a338b55dd21219a5f4da42bc11a9313d1a27d4cc"
READER_ID = "ee402c424e3843108772cfb5e20798e858ff5fd38b9204d39539608c522b5301"
ARMS = ("target_decoy_first", "target_decoy_last", "decoy_only", "no_evidence")
POSITIONS = tuple(
    (arm, view)
    for arm in ARMS[:3]
    for view in ("e_label", "neutral_alias", "unlabeled")
) + (("no_evidence", "unlabeled"),)
ABSTAIN = "I do not have enough evidence."
FACT = re.compile(
    r"Device (DEV-[0-9A-F]{7}) requires clearance token (TAG-[0-9A-F]{7})\."
)
LABEL_ONLY = re.compile(r"(?:[A-Z][0-9]+)(?:[\s,;]+[A-Z][0-9]+)*", re.I)
SHA = re.compile(r"[0-9a-f]{64}\Z")


def digest(obj):
    """Original model's deterministic JSON digest; not the raw-byte SHA."""
    b = json.dumps(
        obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(b).hexdigest()


def load_json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON field")
            obj[key] = value
        return obj

    def reject_constant(_):
        raise ValueError("nonfinite JSON constant")

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)


def read_archive(raw, expected_sha256=ZIP_SHA256):
    if (
        not isinstance(raw, bytes)
        or len(raw) > 8 * 1024 * 1024
        or not SHA.fullmatch(expected_sha256 or "")
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("externally pinned ZIP digest or size mismatch")
    out = {}
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        if len(members) > 64 or sum(x.file_size for x in members) > 8 * 1024 * 1024:
            raise ValueError("archive member/expanded-byte bound")
        for info in members:
            name = info.filename
            p = PurePosixPath(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if (
                name in out
                or info.is_dir()
                or p.is_absolute()
                or not p.parts
                or p.as_posix() != name
                or ".." in p.parts
                or "\\" in name
                or any(ord(c) < 32 for c in name)
                or mode not in (0, stat.S_IFREG)
            ):
                raise ValueError("unsafe or duplicate archive member")
            out[name] = archive.read(info)
    manifest = {}
    for line in out["SHA256SUMS"].decode("ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if not match or match[2] in manifest:
            raise ValueError("bad or repeated internal digest entry")
        manifest[match[2]] = match[1]
    if set(manifest) != set(out) - {"SHA256SUMS"}:
        raise ValueError("unmanifested archive members")
    for name, sha in manifest.items():
        if hashlib.sha256(out[name]).hexdigest() != sha:
            raise ValueError("internal artifact digest drift")
    return out


def rows(file_bytes, planned=200):
    lines = file_bytes.splitlines()
    if len(lines) != planned:
        raise ValueError("incomplete or expanded planned-row census")
    return [load_json(line) for line in lines]


def index(items, expected, *, fields=("qid", "arm", "view")):
    found = {}
    for item in items:
        key = tuple(item[k] for k in fields)
        if key in found or key not in expected:
            raise ValueError("duplicate or unplanned input/answer cell")
        found[key] = item
    if set(found) != expected:
        raise ValueError("missing registered input/answer cells")
    return found


def fact_from_source(item):
    if (
        type(item.get("excerpt")) is not str
        or type(item.get("source_start")) is not int
        or item["source_start"] != 0
        or item.get("source_end") != len(item["excerpt"].encode("utf-8"))
        or item.get("source_digest") != digest(item["excerpt"])
    ):
        raise ValueError("detached source bytes or forged excerpt digest")
    match = FACT.fullmatch(item["excerpt"])
    if not match:
        raise ValueError("unregistered synthetic relation in evidence")
    return match.groups()


def validate_replay(files):
    if (
        files["tested-commit.txt"].decode().strip() != PRODUCER_SHA
        or files["tested-tree.txt"].decode().strip() != PRODUCER_TREE
    ):
        raise ValueError("generating commit/tree mismatch")
    plan = load_json(files["trial/plan.json"])
    if (
        plan.get("schema") != "hepta.system2.qwen-e-label-placebo.v1"
        or plan.get("source_commit") != PRODUCER_SHA
        or plan.get("parent_sha256") != PARENT_SHA256
        or plan.get("reader_identity") != READER_ID
        or plan.get("model_id") != MODEL_ID
        or plan.get("model_revision") != MODEL_REVISION
        or plan.get("planned_model_calls") != 200
        or plan.get("no_training_or_gold_dependent_label_selection") is not True
        or plan.get("pretrained_weights_frozen") is not True
        or plan.get("production_accepted") is not False
        or len(plan.get("positions", [])) != len(POSITIONS)
        or set(map(tuple, plan.get("positions", []))) != set(POSITIONS)
        or len(plan.get("question_ids", [])) != 20
        or len(set(plan["question_ids"])) != 20
    ):
        raise ValueError("registration/model/freezing/source drift")
    expected = {
        (qid, arm, view) for qid in plan["question_ids"] for arm, view in POSITIONS
    }
    originals = files["trial/raw-answers.jsonl"]
    preflight = files["trial/input-preflight.jsonl"]
    if (
        hashlib.sha256(originals).hexdigest() != RAW_SEAL
        or hashlib.sha256(preflight).hexdigest() != INPUT_SEAL
    ):
        raise ValueError("original sealed answer/input bytes changed")
    answer_seal = load_json(files["trial/raw-seal.json"])
    input_seal = load_json(files["trial/input-seal.json"])
    if answer_seal != {
        "rows": 200,
        "scoring_started": False,
        "sha256": RAW_SEAL,
    } or input_seal != {
        "rows": 200,
        "model_calls_started": False,
        "sha256": INPUT_SEAL,
    }:
        raise ValueError("raw-answer or before-model seal mismatch")
    answers = index(rows(originals), expected)
    inputs = index(rows(preflight), expected)
    starts = index(rows(files["trial/starts.jsonl"]), expected)
    seen_reader_profiles = set()
    qdigests = {}
    evaluated = {}
    for key, row in answers.items():
        qid, arm, view = key
        rec = row["reader"]
        inp, started = inputs[key], starts[key]
        if (
            row.get("status") != "succeeded"
            or inp.get("status") != "frozen"
            or started.get("status") != "started"
            or row.get("qid") != qid
            or row.get("arm") != arm
            or row.get("view") != view
            or row.get("alias") != inp.get("alias")
            or row.get("alias") != started.get("alias")
            or rec.get("reader_identity") != READER_ID
            or rec.get("model_id") != MODEL_ID
            or rec.get("revision") != MODEL_REVISION
            or rec.get("trainable_parameters") != 0
            or rec.get("answer_postprocessed") is not False
            or rec.get("production_accepted") is not False
            or rec.get("original_evidence_labels_preserved_in_receipt") is not True
            or rec.get("input_tokens") != inp.get("token_count")
            or row.get("input_sha256") != inp.get("input_sha256")
            or row.get("input_sha256") != started.get("input_sha256")
            or row.get("input_sha256") != rec.get("input_ids_digest")
            or not isinstance(row.get("answer"), str)
            or not row["answer"].strip()
        ):
            raise ValueError("input/source/model/result provenance drift")
        for t in ("input_tokens", "generated_tokens", "cpu_time_ns", "wall_time_ns"):
            if type(rec.get(t)) is not int or rec[t] <= 0:
                raise ValueError("missing or invalid actual model cost")
        if not 1 <= rec["generated_tokens"] <= 64:
            raise ValueError("unexpected output-token allowance")
        seen_reader_profiles.add(rec.get("reader_profile"))
        if qid in qdigests and qdigests[qid] != rec.get("question_digest"):
            raise ValueError("question identity changed across arms")
        qdigests[qid] = rec.get("question_digest")
        delivered = rec["delivered_evidence"]
        selected = row.get("selected")
        n_expected = 0 if arm == "no_evidence" else 1 if arm == "decoy_only" else 2
        if (
            not isinstance(delivered, list)
            or len(delivered) != n_expected
            or len(selected) != n_expected
            or [d.get("original_id") for d in delivered] != selected
            or len(set(selected)) != len(selected)
            or any(d.get("scope") != delivered[0].get("scope") for d in delivered)
            or [d.get("label") for d in delivered]
            != [f"E{i + 1}" for i in range(n_expected)]
        ):
            raise ValueError("source delivery/labels/registered capacity drift")
        facts = [fact_from_source(d) for d in delivered]
        if len({d[0] for d in facts}) != len(facts):
            raise ValueError("duplicate device relation in synthetic evidence")
        evaluated[key] = dict(
            answer=row["answer"].strip(),
            input_tokens=rec["input_tokens"],
            output_tokens=rec["generated_tokens"],
            cpu_ns=rec["cpu_time_ns"],
            source_ids=tuple(selected),
            fact_tokens=tuple(x[1] for x in facts),
            output_digest=rec["generated_ids_digest"],
            label_echo=bool(LABEL_ONLY.fullmatch(row["answer"].strip())),
        )
    if len(seen_reader_profiles) != 1 or None in seen_reader_profiles:
        raise ValueError("mixed or missing frozen reader profile")
    # Prove the fact identities and the true target are invariant under label
    # aliases, source-order swaps and deliberate evidence removal.
    for qid in plan["question_ids"]:
        indexed = {key[1:]: value for key, value in evaluated.items() if key[0] == qid}
        first = indexed["target_decoy_first", "e_label"]
        last = indexed["target_decoy_last", "e_label"]
        decoy = indexed["decoy_only", "e_label"]
        if (
            len(first["source_ids"]) != 2
            or tuple(reversed(last["source_ids"])) != first["source_ids"]
            or first["fact_tokens"][0] != last["fact_tokens"][1]
            or first["fact_tokens"][1] != last["fact_tokens"][0]
            or decoy["source_ids"] != (first["source_ids"][1],)
            or decoy["fact_tokens"] != (first["fact_tokens"][1],)
            or first["fact_tokens"][0] == first["fact_tokens"][1]
        ):
            raise ValueError("counterfactual answer/decoy source identity drift")
        for arm, view in POSITIONS:
            trial = indexed[arm, view]
            original = indexed[arm, "e_label"] if arm != "no_evidence" else trial
            if (
                trial["source_ids"] != original["source_ids"]
                or trial["fact_tokens"] != original["fact_tokens"]
            ):
                raise ValueError("label intervention mutated original evidence")
        for arm in ARMS[:3]:
            p = indexed[arm, "e_label"]
            a = indexed[arm, "neutral_alias"]
            u = indexed[arm, "unlabeled"]
            if (
                p["input_tokens"] != a["input_tokens"]
                or u["input_tokens"] >= p["input_tokens"]
            ):
                raise ValueError("claimed alias-matched token count drift")
    return plan, evaluated


def summarize(plan, evaluated, source_file_count):
    groups = []
    results = {}
    for arm, view in POSITIONS:
        qrows = []
        for qid in plan["question_ids"]:
            cell = evaluated[qid, arm, view]
            if arm == "target_decoy_first":
                expected = cell["fact_tokens"][0]
            elif arm == "target_decoy_last":
                expected = cell["fact_tokens"][1]
            else:
                expected = None
            answer = cell["answer"]
            success = (answer == expected) if expected else (answer == ABSTAIN)
            refusal = answer == ABSTAIN
            unsupported = expected is None and answer in cell["fact_tokens"]
            qrows.append(
                dict(
                    qid=qid,
                    exact_success=success,
                    exact_answer=bool(expected and success),
                    appropriate_refusal=bool(expected is None and refusal),
                    label_echo=cell["label_echo"],
                    unsupported_copy=unsupported,
                    input_tokens=cell["input_tokens"],
                    output_tokens=cell["output_tokens"],
                    cpu_ns=cell["cpu_ns"],
                )
            )
        group = dict(
            arm=arm,
            view=view,
            planned=len(qrows),
            exact_answers=sum(x["exact_answer"] for x in qrows),
            exact_refusals=sum(x["appropriate_refusal"] for x in qrows),
            label_echoes=sum(x["label_echo"] for x in qrows),
            unsupported_copies=sum(x["unsupported_copy"] for x in qrows),
            success=sum(x["exact_success"] for x in qrows),
            input_tokens=sum(x["input_tokens"] for x in qrows),
            output_tokens=sum(x["output_tokens"] for x in qrows),
            cpu_ns=sum(x["cpu_ns"] for x in qrows),
        )
        groups.append(group)
        results[arm, view] = {x["qid"]: x for x in qrows}
    pairwise = []
    for arm in ARMS[:3]:
        for first, second in (
            ("e_label", "neutral_alias"),
            ("neutral_alias", "unlabeled"),
        ):
            a, b = results[arm, first], results[arm, second]
            pairwise.append(
                dict(
                    arm=arm,
                    first=first,
                    second=second,
                    both=sum(
                        a[q]["exact_success"] and b[q]["exact_success"] for q in a
                    ),
                    first_only=sum(
                        a[q]["exact_success"] and not b[q]["exact_success"] for q in a
                    ),
                    second_only=sum(
                        b[q]["exact_success"] and not a[q]["exact_success"] for q in a
                    ),
                    neither=sum(
                        not a[q]["exact_success"] and not b[q]["exact_success"]
                        for q in a
                    ),
                    input_token_delta=sum(
                        b[q]["input_tokens"] - a[q]["input_tokens"] for q in a
                    ),
                    cpu_ns_delta=sum(b[q]["cpu_ns"] - a[q]["cpu_ns"] for q in a),
                )
            )
    return dict(
        schema=SCHEMA,
        source_commit=PRODUCER_SHA,
        generating_tree=PRODUCER_TREE,
        archive_sha256=ZIP_SHA256,
        archive_verified_entries=source_file_count,
        answer_seal=RAW_SEAL,
        input_seal=INPUT_SEAL,
        source_task_family="twenty synthetic one-hop device-to-TAG questions",
        model=MODEL_ID,
        model_revision=MODEL_REVISION,
        completed=200,
        unique_questions=20,
        new_model_calls=0,
        groups=groups,
        pairwise=pairwise,
        no_go_reason=(
            "insufficient-evidence token copying in every decoy-only condition"
        ),
        safe_reader_adequacy=False,
        independent_natural_validation=False,
        full_cpu_cost_matched=False,
        trained_NDU_FBSDE_gain=False,
        production_accepted=False,
    )


def audit(path, expected_sha256=ZIP_SHA256):
    files = read_archive(Path(path).read_bytes(), expected_sha256)
    plan, evaluated = validate_replay(files)
    summary = summarize(plan, evaluated, len(files) - 1)
    producer = load_json(files["trial/summary.json"])
    if (
        producer.get("schema") != "hepta.system2.qwen-e-label-placebo.v1"
        or producer.get("source_commit") != PRODUCER_SHA
        or producer.get("planned") != 200
        or producer.get("completed") != 200
        or producer.get("failed") != 0
        or producer.get("disposition") != "no_safe_reader_adequacy_gain"
        or producer.get("input_sha256") != INPUT_SEAL
        or producer.get("raw_sha256") != RAW_SEAL
    ):
        raise ValueError("producer score or disposition drift")
    by_group = {(x["arm"], x["view"]): x for x in producer["conditions"]}
    if len(by_group) != 10 or set(by_group) != set(POSITIONS):
        raise ValueError("producer condition census drift")
    for group in summary["groups"]:
        original = by_group[group["arm"], group["view"]]
        for local, published in (
            ("exact_answers", "answers"),
            ("exact_refusals", "refusals"),
            ("label_echoes", "label_echoes"),
            ("unsupported_copies", "unsupported_copies"),
            ("success", "strict_success"),
            ("input_tokens", "input_tokens"),
            ("output_tokens", "output_tokens"),
            ("cpu_ns", "cpu_ns"),
        ):
            if group[local] != original[published]:
                raise ValueError("post-seal independent score/cost replay drift")
    return summary


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("archive", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    result = audit(args.archive)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "completed",
                    "unique_questions",
                    "no_go_reason",
                    "safe_reader_adequacy",
                )
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
