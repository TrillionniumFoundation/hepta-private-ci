"""Train-only tiny evidence-sufficiency Head against sealed frozen-Qwen answers.

Research ONLY. Forty pre-exposed synthetic question identities train;
twenty separately exposed synthetic identities evaluate. No model/Encoder inference is
performed. The 'saved decoder CPU' is a REPLAY counterfactual, not observed savings.
Every learned intervention is compared with a zero-fit literal-source rule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import re
import stat
import time
import zipfile

from system2_multihop_evidence import digest, make_case, parse_relation

SCHEMA = "hepta.system2.cell-support-gate.v1"
PINS = {
    "train_lexical": dict(
        sha="0fd2a2aa60c0c28bdd61a2566262558410bb66c6997355aa610fe98b89aabc19",
        commit="4fe8ac3d75132a21abf2c3e9d172c637e1bb6f91",
        tree="a128abb8082e86734aa0d573176a74d20fc0dcce",
        raw="3a13ba9b8a6d6deef21d3bc0aa8d29c3e5a61e668e60a2b9c7c7812e9b0e268f",
        count=320,
        indices=range(60, 80),
    ),
    "train_label": dict(
        sha="8da46b3965f8a6aa9919877c8165e6a2d06f3298921e645d91f7cddfcf9b8761",
        commit="56968236c1281908674101568b229c6a1c03359d",
        tree="9d5651917c858bb0b875779f6057f4b15327340c",
        raw="26736efaedab0f49197011b76190e29dfd241fccfb08d1257c259c9b9b7f5e7f",
        count=180,
        indices=range(80, 100),
    ),
    "eval_placebo": dict(
        sha="6f10c884f949a8518294b1b320cb2d5374232edbe3bafc881826a96e1723e9b6",
        commit="3e5bf3697524bdb81bafe23344dbe4520eaf3e28",
        tree="bdbe12d89e24aaac8970b0091c5788ec8a14a778",
        raw="eb3dca574fa64e0ebdb4b4b4a400e25f10914369121a8038bf23a415da37ab23",
        count=200,
        indices=range(100, 120),
    ),
}
MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "a338b55dd21219a5f4da42bc11a9313d1a27d4cc"
READER_ID = "ee402c424e3843108772cfb5e20798e858ff5fd38b9204d39539608c522b5301"
ABSTAIN = "I do not have enough evidence."
LINE = re.compile(
    r"^Device (DEV-[A-F0-9]{7}) requires clearance token (TAG-[A-F0-9]{7})\.$"
)
TAG = re.compile(r"\bTAG-[A-F0-9]{7}\b")
HEX = re.compile(r"^[0-9a-f]{64}$")
FEATURES = (
    "bias",
    "matched_fact",
    "source_count",
    "other_fact_count",
    "has_tag",
    "no_sources",
)
ARMS_OLD = ("single_fact", "target_decoy_two_first", "decoy_one", "no_evidence")
ARMS_LABEL = (
    "single_fact",
    "target_decoy_first",
    "target_decoy_last",
    "decoy_only",
    "no_evidence",
)
ARMS_NEW = ("target_decoy_first", "target_decoy_last", "decoy_only", "no_evidence")
VIEWS_NEW = ("e_label", "neutral_alias", "unlabeled")
EVAL_POSITIONS = tuple((a, v) for a in ARMS_NEW[:-1] for v in VIEWS_NEW) + (
    ("no_evidence", "unlabeled"),
)
PARAMETERS = len(FEATURES)
UPDATES = 240
LEARNING_RATE = 0.40
WEIGHT_DECAY = 0.002
SEED = 827


def strict_json(blob):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result

    def bad(_):
        raise ValueError("nonfinite JSON value")

    return json.loads(blob, object_pairs_hook=pairs, parse_constant=bad)


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def write(path, data):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(
            data, f, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
        f.write("\n")


def archive(path, pin):
    """Externally pinned ZIP; bounded regular safe paths and complete inner hashes."""
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024**2:
        raise ValueError("unavailable/unbounded input archive")
    if sha(path.read_bytes()) != pin["sha"]:
        raise ValueError("source archive external SHA mismatch")
    result = {}
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if len(entries) > 64 or sum(i.file_size for i in entries) > 8 * 1024**2:
            raise ValueError("archive inflation limit")
        for item in entries:
            name = item.filename
            p = PurePosixPath(name)
            mode = stat.S_IFMT(item.external_attr >> 16)
            if (
                name in result
                or p.as_posix() != name
                or p.is_absolute()
                or ".." in p.parts
                or "\\" in name
                or not p.parts
                or any(ord(x) < 32 for x in name)
                or item.is_dir()
                or mode not in (0, stat.S_IFREG)
            ):
                raise ValueError("unsafe archive path")
            result[name] = z.read(item)
    members = {}
    for line in result["SHA256SUMS"].decode("utf8").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
        if m is None or m[2] in members:
            raise ValueError("invalid archive member manifest")
        members[m[2]] = m[1]
    if set(members) != set(result) - {"SHA256SUMS"} or any(
        sha(result[n]) != s for n, s in members.items()
    ):
        raise ValueError("inner member hash drift")
    if result["tested-commit.txt"].decode().strip() != pin["commit"] or (
        result["tested-tree.txt"].decode().strip() != pin["tree"]
    ):
        raise ValueError("generating source/tree drift")
    raw = result["trial/raw-answers.jsonl"]
    receipt = strict_json(result["trial/raw-seal.json"])
    if (
        receipt
        != {"rows": pin["count"], "scoring_started": False, "sha256": pin["raw"]}
        or sha(raw) != pin["raw"]
    ):
        raise ValueError("model output seal drift")
    rows = [strict_json(x) for x in raw.splitlines()]
    if len(rows) != pin["count"]:
        raise ValueError("original answer count drift")
    plan = strict_json(result["trial/plan.json"])
    if plan["source_commit"] != pin["commit"]:
        raise ValueError("plan/source generating commit drift")
    starts = [strict_json(x) for x in result["trial/starts.jsonl"].splitlines()]
    if len(starts) != len(rows):
        raise ValueError("missing original start journal rows")
    row_fields = (
        ("qid", "arm", "profile")
        if pin["count"] == 320
        else (
            ("qid", "arm", "presentation")
            if pin["count"] == 180
            else ("qid", "arm", "view")
        )
    )
    starts_index = {tuple(s[k] for k in row_fields) for s in starts}
    raw_index = {tuple(r[k] for k in row_fields) for r in rows}
    if (
        len(starts_index) != len(starts)
        or starts_index != raw_index
        or any(s.get("status") != "started" for s in starts)
    ):
        raise ValueError("orphaned/missing start journal identity")
    if pin["count"] == 200:
        preflight = [
            strict_json(x) for x in result["trial/input-preflight.jsonl"].splitlines()
        ]
        preseal = strict_json(result["trial/input-seal.json"])
        if len(preflight) != 200 or preseal != {
            "rows": 200,
            "model_calls_started": False,
            "sha256": sha(result["trial/input-preflight.jsonl"]),
        }:
            raise ValueError("model input not frozen before new results")
        mapped = {(r["qid"], r["arm"], r["view"]): r for r in preflight}
        if len(mapped) != 200 or set(mapped) != raw_index:
            raise ValueError("missing or duplicate frozen input position")
        for row in rows:
            key = tuple(row[k] for k in row_fields)
            before = mapped[key]
            if (
                row["reader"]["input_tokens"] != before["token_count"]
                or row["reader"]["input_ids_digest"] != before["input_sha256"]
                or row.get("input_sha256") != before["input_sha256"]
                or row.get("alias") != before["alias"]
                or before.get("status") != "frozen"
            ):
                raise ValueError("changed frozen model input/alias")
        if any(
            s.get("input_sha256")
            != mapped[tuple(s[k] for k in row_fields)]["input_sha256"]
            for s in starts
        ):
            raise ValueError("started inference differs from input seal")
    return dict(
        rows=rows, plan=plan, files=len(members), sha=pin["sha"], manifest=result
    )


def cohort(indices):
    """Generate *question-visible* device identity; never expose target code to Head."""
    output = {}
    for i in indices:
        old = make_case(i)
        targets = [
            (doc, relation[1])
            for doc in old.documents
            if (relation := parse_relation(doc))
            and relation[0] == "device"
            and relation[2] == "token"
            and relation[3] == old.answer
        ]
        if len(targets) != 1:
            raise ValueError("ambiguous synthetic question")
        _, device = targets[0]
        qid = "onehop:" + digest((old.question.identity, device))[:24]
        output[qid] = dict(
            index=i,
            device=device,
            target=old.answer.replace("TOK-", "TAG-"),
            docs=old.documents,
            question_id=qid,
        )
    if len(output) != len(indices):
        raise ValueError("nonunique question identities")
    return output


def validated_row(row, *, kind, cases):
    if row.get("status") != "succeeded" or row.get("qid") not in cases:
        raise ValueError("missing/failed/unknown question model output")
    rec = row["reader"]
    if (
        rec.get("reader_identity") != READER_ID
        or rec.get("model_id") != MODEL_ID
        or rec.get("revision") != REVISION
        or rec.get("trainable_parameters") != 0
        or rec.get("answer_postprocessed") is not False
        or rec.get("production_accepted") is not False
        or any(
            not isinstance(rec.get(k), int) or isinstance(rec[k], bool) or rec[k] < 0
            for k in ("input_tokens", "generated_tokens", "cpu_time_ns")
        )
        or not isinstance(row.get("answer"), str)
        or not row["answer"].strip()
        or not isinstance(rec.get("input_ids_digest"), str)
        or not HEX.fullmatch(rec["input_ids_digest"])
        or not isinstance(rec.get("generated_ids_digest"), str)
        or not HEX.fullmatch(rec["generated_ids_digest"])
    ):
        raise ValueError("unqualified Reader identity, raw output or real cost")
    sources = rec["delivered_evidence"]
    if (
        not isinstance(sources, list)
        or len(sources) > 2
        or len(sources) != len(row["selected"])
    ):
        raise ValueError("unbounded source census")
    case = cases[row["qid"]]
    transformed = {
        "doc:"
        + digest((d.identity, "credential_tag", d.content.replace("TOK-", "TAG-")))[
            :24
        ]: (d, d.content.replace("TOK-", "TAG-"))
        for d in case["docs"]
    }
    matched = []
    for index, span in enumerate(sources):
        original_id = span["original_id"]
        if (
            original_id != row["selected"][index]
            or original_id not in transformed
            or span.get("source_start") != 0
            or span.get("label") != f"E{index + 1}"
        ):
            raise ValueError("detached or reordered original source")
        original, text = transformed[original_id]
        if (
            span["excerpt"] != text
            or span["source_end"] != len(text.encode("utf8"))
            or span.get("root")
            != "root:" + digest((original.root, "credential_tag", text))
            or span.get("source_digest") != digest(text)
        ):
            raise ValueError("source content/root/provenance mismatch")
        m = LINE.fullmatch(text)
        if m:
            matched.append((m.group(1), m.group(2)))
    if kind == "train_lexical":
        if row["profile"] != "credential_tag" or row["arm"] not in ARMS_OLD:
            raise ValueError("not registered training arm/profile")
    elif kind == "train_label":
        if row["presentation"] != "unlabeled" or row["arm"] not in ARMS_LABEL:
            raise ValueError("not registered training presentation")
    else:
        if (row["arm"], row["view"]) not in EVAL_POSITIONS:
            raise ValueError("not registered evaluation position")
    support = sum(entity == case["device"] for entity, _ in matched) == 1
    # For this closed grammar only, the actual source path is one literal fact.
    return dict(
        qid=row["qid"],
        arm=row["arm"],
        view=row.get("view", row.get("presentation", row.get("profile"))),
        reader_answer=row["answer"],
        reader_cost_ns=rec["cpu_time_ns"],
        generated_tokens=rec["generated_tokens"],
        input_tokens=rec["input_tokens"],
        sources=len(sources),
        question_device=case["device"],
        matched_facts=matched,
        target=case["target"],
        support=support,
    )


def feature(x):
    """Fixed 6-number lexical stem; no gold answer, arm name or label text."""
    count = len(x["matched_facts"])
    matches = sum(device == x["question_device"] for device, _ in x["matched_facts"])
    other = count - matches
    return [
        1.0,
        float(matches > 0),
        x["sources"] / 2.0,
        min(other, 2) / 2.0,
        float(count > 0),
        float(x["sources"] == 0),
    ]


def sigmoid(t):
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, t))))


def fit(rows, *, shuffled=False):
    """6 scalar weights, fixed full-batch SGD, dataset qid macro weighting."""
    if not rows or any(len(feature(r)) != PARAMETERS for r in rows):
        raise ValueError("missing bounded Head inputs")
    qids = {r["qid"] for r in rows}
    if len(qids) != 40:
        raise ValueError("training only 40 registered source-question IDs")
    rng = random.Random(SEED)
    labels = [float(r["support"]) for r in rows]
    if shuffled:
        rng.shuffle(labels)
    weights = [0.0] * PARAMETERS
    # Each independent question ID receives total weight 1 regardless of arms.
    sizes = {qid: sum(r["qid"] == qid for r in rows) for qid in qids}
    weights_by_row = [1.0 / (len(qids) * sizes[r["qid"]]) for r in rows]
    started = time.process_time_ns()
    for _ in range(UPDATES):
        grad = [WEIGHT_DECAY * v for v in weights]
        for r, y, wt in zip(rows, labels, weights_by_row, strict=True):
            x = feature(r)
            pred = sigmoid(sum(w * v for w, v in zip(weights, x, strict=True)))
            for j in range(PARAMETERS):
                grad[j] += wt * (pred - y) * x[j]
        weights = [w - LEARNING_RATE * g for w, g in zip(weights, grad, strict=True)]
    consumed = time.process_time_ns() - started
    if any(not math.isfinite(w) for w in weights):
        raise ValueError("nonfinite trained Head")
    return dict(
        weights=weights,
        train_cpu_ns=consumed,
        optimizer_updates=UPDATES,
        train_subjects=len(qids),
        rows=len(rows),
        shuffled=shuffled,
        parameters=PARAMETERS,
    )


def decision(row, head):
    probability = sigmoid(
        sum(w * x for w, x in zip(head["weights"], feature(row), strict=True))
    )
    return probability >= 0.5, probability


def frozen_matcher(row):
    return any(dev == row["question_device"] for dev, _ in row["matched_facts"])


def prepare(archives):
    snapshots = {key: archive(archives[key], pin) for key, pin in PINS.items()}
    case_tables = {key: cohort(pin["indices"]) for key, pin in PINS.items()}
    if any(
        set(case_tables[x]) & set(case_tables[y])
        for x, y in (
            ("train_lexical", "train_label"),
            ("train_lexical", "eval_placebo"),
            ("train_label", "eval_placebo"),
        )
    ):
        raise ValueError("training/evaluation source question overlap")
    train = []
    held = []
    for key, blob in snapshots.items():
        cases = case_tables[key]
        plan = blob["plan"]
        rows = blob["rows"]
        registered_questions = plan.get("questions", plan.get("question_ids"))
        if (
            not isinstance(registered_questions, list)
            or len(registered_questions) != len(cases)
            or set(registered_questions) != set(cases)
        ):
            raise ValueError("plan question census differs")
        if key == "train_lexical":
            rows = [r for r in rows if r["profile"] == "credential_tag"]
            registered = {(qid, a) for qid in cases for a in ARMS_OLD}
            actual = {(r["qid"], r["arm"]) for r in rows}
        elif key == "train_label":
            rows = [r for r in rows if r["presentation"] == "unlabeled"]
            registered = {(qid, a) for qid in cases for a in ARMS_LABEL}
            actual = {(r["qid"], r["arm"]) for r in rows}
        else:
            registered = {(qid, a, v) for qid in cases for a, v in EVAL_POSITIONS}
            actual = {(r["qid"], r["arm"], r["view"]) for r in rows}
        if len(rows) != len(registered) or actual != registered:
            raise ValueError("incomplete selected training/test positions")
        for r in rows:
            parsed = validated_row(r, kind=key, cases=cases)
            (held if key == "eval_placebo" else train).append(parsed)
    if len(train) != 180 or len(held) != 200:
        raise ValueError("expected 180 train and 200 evaluation positions")
    return snapshots, train, held


def summarize(trials, eval_rows, head_models):
    lookup = {r["qid"]: r["target"] for r in eval_rows}
    expected = {(r["qid"], r["arm"], r["view"]) for r in eval_rows}
    if len(expected) != 200 or len(trials) != 200 * len(head_models):
        raise ValueError("missing a scheduled Cell-action arm")
    outcome = {}
    for action in trials:
        key = action["qid"], action["arm"], action["view"], action["head"]
        if key in outcome:
            raise ValueError("duplicate scheduled action")
        outcome[key] = action
    if set(outcome) != {(q, a, v, h) for q, a, v in expected for h in head_models}:
        raise ValueError("missing scheduled action")
    result = []
    per_head = {}
    eval_lookup = {(r["qid"], r["arm"], r["view"]): r for r in eval_rows}
    if len(eval_lookup) != 200:
        raise ValueError("duplicate held-out frozen Reader positions")
    for name in head_models:
        part = [r for r in trials if r["head"] == name]
        approved = correct_answer = correct_refusal = unsupported = 0
        paid_cpu_ns = would_avoid_cpu_ns = 0
        for action in part:
            source = eval_lookup[action["qid"], action["arm"], action["view"]]
            if action["call_reader"]:
                approved += 1
                paid_cpu_ns += source["reader_cost_ns"]
                answer = source["reader_answer"].strip()
                if source["support"]:
                    correct_answer += int(answer == lookup[source["qid"]])
                else:
                    correct_refusal += int(answer == ABSTAIN)
                    unsupported += int(answer != ABSTAIN)
            else:
                would_avoid_cpu_ns += source["reader_cost_ns"]
                correct_refusal += int(not source["support"])
                # Suppression with sufficient evidence is a missed real answer,
                # not a correctness benefit from abstention.
        record = dict(
            head=name,
            planned=len(part),
            would_call_reader=approved,
            would_abstain=len(part) - approved,
            correct_supported_answers=correct_answer,
            correct_insufficient_refusals=correct_refusal,
            unsupported_reader_outputs=unsupported,
            correct_total=correct_answer + correct_refusal,
            hypothetical_avoided_decoder_cpu_ns=would_avoid_cpu_ns,
            historical_decoder_cpu_paid_in_full=True,
            archived_decoder_cpu_ns_for_selected_actions=paid_cpu_ns,
        )
        per_head[name] = record
        result.append(record)
    frozen = per_head["frozen_exact_match"]
    learned = per_head["learned_head"]
    by_condition = []
    for name in head_models:
        for arm, view in EVAL_POSITIONS:
            matched = [
                r
                for r in trials
                if r["head"] == name and r["arm"] == arm and r["view"] == view
            ]
            if len(matched) != 20:
                raise ValueError("missing matched fixed condition")
            supported = arm in ("target_decoy_first", "target_decoy_last")
            passed = sum(
                (
                    eval_lookup[r["qid"], arm, view]["reader_answer"].strip()
                    == lookup[r["qid"]]
                )
                if r["call_reader"] and supported
                else (
                    eval_lookup[r["qid"], arm, view]["reader_answer"].strip() == ABSTAIN
                )
                if r["call_reader"] and not supported
                else not supported
                for r in matched
            )
            by_condition.append(
                dict(
                    head=name,
                    arm=arm,
                    view=view,
                    distinct_questions=20,
                    correct=passed,
                    reader_calls=sum(r["call_reader"] for r in matched),
                )
            )
    gain = learned["correct_total"] > frozen["correct_total"]
    learned_actions = {
        (r["qid"], r["arm"], r["view"]): r["call_reader"]
        for r in trials
        if r["head"] == "learned_head"
    }
    frozen_actions = {
        (r["qid"], r["arm"], r["view"]): r["call_reader"]
        for r in trials
        if r["head"] == "frozen_exact_match"
    }
    disagreements = sum(
        learned_actions[key] != frozen_actions[key] for key in learned_actions
    )
    return dict(
        arms=result,
        conditions=by_condition,
        learned_exceeds_frozen_in_safe_correct_total=gain,
        learned_vs_frozen_action_disagreements=disagreements,
        candidate_disposition=(
            "independent_natural_domain_confirmation_required"
            if gain
            and learned["unsupported_reader_outputs"]
            <= frozen["unsupported_reader_outputs"]
            else "reject_learned_cell_no_incremental_value"
        ),
        production_accepted=False,
        actual_new_inference_calls=0,
        actual_inference_cpu_saved=0,
        cross_family_semantics_validated=False,
        general_ndu_fbsde_gain=False,
    )


def run(archives, output, *, source_commit):
    if not re.fullmatch("[0-9a-f]{40}", source_commit or ""):
        raise ValueError("exact generating code commit required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "plan.json",
        dict(
            schema=SCHEMA,
            source_commit=source_commit,
            pins={
                k: {j: v for j, v in p.items() if j != "indices"}
                for k, p in PINS.items()
            },
            train_indices=[[60, 80], [80, 100]],
            eval_indices=[100, 120],
            sources="actual sealed Qwen frozen Reader archives",
            deterministic_6_scalar_head_on_fixed_lexical_features=True,
            no_neural_reader_inference=True,
            train_only_original_40_subjects=True,
            evaluation_previously_exposed_synthetic_family=True,
            planned_eval_questions=20,
            planned_eval_reader_positions=200,
            action_arms=(
                "always_call",
                "never_call",
                "frozen_exact_match",
                "learned_head",
                "shuffled_labels",
            ),
            original_3_archives_verified_before_training=True,
            actual_compute_saved=False,
            production_accepted=False,
        ),
    )
    started = time.process_time_ns()
    try:
        snapshots, train, held = prepare(archives)
        true_head = fit(train)
        shuffled_head = fit(train, shuffled=True)
        models = dict(learned_head=true_head, shuffled_labels=shuffled_head)
        write(
            output / "frozen-heads.json",
            dict(
                models=models,
                train_ids=sorted({x["qid"] for x in train}),
                training_finished_before_evaluation=True,
                archive_pins={k: x["sha"] for k, x in snapshots.items()},
            ),
        )
        rows = []
        for item in held:
            actions = dict(
                always_call=True,
                never_call=False,
                frozen_exact_match=frozen_matcher(item),
            )
            for name, model in models.items():
                actions[name] = decision(item, model)[0]
            for name, call in actions.items():
                rows.append(
                    dict(
                        qid=item["qid"],
                        arm=item["arm"],
                        view=item["view"],
                        head=name,
                        call_reader=call,
                        status="sealed_action",
                    )
                )
        # Predicted actions and frozen Head SHA are recorded BEFORE scoring.
        with (output / "sealed-actions.jsonl").open("x", encoding="utf8") as f:
            for row in rows:
                f.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        raw = (output / "sealed-actions.jsonl").read_bytes()
        receipt = dict(sha256=sha(raw), rows=len(rows), scoring_started=False)
        write(output / "prediction-seal.json", receipt)
        report = summarize(rows, held, tuple(actions))
        if sha((output / "sealed-actions.jsonl").read_bytes()) != receipt["sha256"]:
            raise ValueError("post-score mutation")
        report.update(
            schema=SCHEMA,
            source_commit=source_commit,
            planned_questions=20,
            train_subjects=40,
            train_contexts=len(train),
            eval_contexts=len(held),
            event_count=len(rows),
            total_cpu_ns=time.process_time_ns() - started,
            original_archive_manifest_members={
                k: x["files"] for k, x in snapshots.items()
            },
            prediction_sha256=receipt["sha256"],
            head_parameter_count=PARAMETERS,
            claim="archived-model replay only, no serving-time savings",
        )
        write(output / "summary.json", report)
        return report
    except BaseException as error:
        write(
            output / "failure.json",
            dict(
                error_type=type(error).__name__,
                error=str(error)[:512],
                failed=True,
                missing_work_not_imputed=True,
            ),
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lexical_320", type=Path)
    parser.add_argument("tag_180", type=Path)
    parser.add_argument("equal_token_200", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(
        dict(
            train_lexical=args.lexical_320,
            train_label=args.tag_180,
            eval_placebo=args.equal_token_200,
        ),
        args.output,
        source_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", ""),
    )
    print(
        json.dumps(
            dict(
                count=result["event_count"],
                learned_incremental_gain=result[
                    "learned_exceeds_frozen_in_safe_correct_total"
                ],
                heads=result["arms"],
            ),
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
