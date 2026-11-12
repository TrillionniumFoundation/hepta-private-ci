"""Read-only independent arithmetic check of original native experiment bytes."""

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import struct
import time

SOURCE = "b0ea141de2d5218869823b2d9e075db6d7b215dd"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def read(path, expected=None):
    raw = path.read_bytes()
    if expected is not None:
        require(
            sha256(raw).hexdigest() == expected, "original SHA mismatch: " + path.name
        )
    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def array_hash(weights):
    dimensions = (len(weights), len(weights[0]))
    return sha256(
        str(dimensions).encode()
        + b"".join(struct.pack("<d", v) for row in weights for v in row)
    ).hexdigest()


def journal(path, result):
    require(
        sha256(path.read_bytes()).hexdigest() == result["rows_sha256"], "journal SHA"
    )
    entries = [
        json.loads(line, object_pairs_hook=unique)
        for line in path.read_text().splitlines()
    ]
    require(len(entries) == 2 * len(result["rows"]), "journal event denominator")
    recovered = []
    for start, end in zip(entries[::2], entries[1::2]):
        require(
            start["event"] == "attempt_started" and end["event"] == "row_completed",
            "journal event pairing",
        )
        row = end["row"]
        require(
            (start["condition"], start["id"]) == (row["condition"], row["id"]),
            "journal task pairing",
        )
        recovered.append(row)
    require(recovered == result["rows"], "RESULT rows differ from original journal")


def counts(rows):
    completed = sum(row["status"] == "completed" for row in rows)
    require(
        all(r["status"] in ("completed", "failed") for r in rows), "unknown row status"
    )
    return {
        "generation_attempts": len(rows),
        "completed_generations": completed,
        "failed_generations": len(rows) - completed,
        "actual_generations": completed,
    }


def answer(row):
    if row["status"] != "completed":
        return None
    value = row["text"].strip().casefold()
    if value.endswith((".", "!")):
        value = value[:-1]
    return value if value in ("yes", "no") else None


def replay_training(condition, run_dir, tasks, training_labels, features, plan):
    records = read(run_dir / ("train-" + condition["condition"] + ".json"))
    receipts = records["receipts"]
    require(len(receipts) == 256, "training update denominator")
    teacher = [(r["action_id"], r["teacher_input"]) for r in receipts]
    pin = sha256(json.dumps(teacher, separators=(",", ":")).encode()).hexdigest()
    require(
        pin == records["feedback_sha256"] == condition["feedback_sha256"],
        "external feedback hash",
    )
    actual = read(run_dir / condition["weights_file"], condition["weights_sha256"])[
        "weights"
    ]
    w = [[0.0] * len(actual[0]) for _ in range(2)]
    grouped = {(t["pair"], t["group"]): t for t in tasks if t["split"] == "train"}
    pending = {}
    coefficient_error = 0.0
    previous = array_hash(w)
    for sequence in range(259):
        if sequence < 256:
            row = receipts[sequence]
            seed, action, pair = map(int, row["action_id"].split(":"))
            require(
                seed == condition["seed"] and action == sequence and 0 <= pair < 32,
                "action identity",
            )
            vectors, expectations, signs = [], [], []
            for group in range(2):
                task = grouped[(pair, group)]
                f = features[task["id"]]
                e = f["feature"]
                delta = math.fsum(a * b for a, b in zip(w[group], e))
                by, bn, other = f["normalizer"]
                logits = [by + delta, bn - delta, other]
                maximum = max(logits)
                exp = [math.exp(z - maximum) for z in logits]
                expectations.append((exp[0] - exp[1]) / sum(exp))
                vectors.append(e)
                signs.append(1 if training_labels[task["id"]] == "yes" else -1)
            require(
                signs == row["teacher_input"], "feedback does not match training label"
            )
            pending[sequence + 3] = (vectors, expectations, signs, row)
        if sequence in pending:
            vectors, expectations, signs, row = pending.pop(sequence)
            require(
                array_hash(vectors) == row["eligibility_sha256"],
                "recorded action-time feature identity",
            )
            require(
                row["sequence"] == sequence and row["action_sequence"] == sequence - 3,
                "feedback availability",
            )
            require(row["before_sha256"] == previous, "recorded state chain")
            previous = row["after_sha256"]
            routed = (
                signs[::-1]
                if condition["arm"] == "shuffled"
                else [sum(signs) / 2] * 2
                if condition["arm"] == "scalar"
                else signs
            )
            require(routed == row["teacher_routed"], "feedback permutation")
            for group in range(2):
                c = routed[group] - expectations[group]
                coefficient_error = max(
                    coefficient_error, abs(c - row["coefficient"][group])
                )
                if condition["arm"] != "no_eligibility":
                    scale = plan["learning_rate"] * plan["decay"] ** 3 * c
                    w[group] = [a + scale * b for a, b in zip(w[group], vectors[group])]
                    norm = math.sqrt(math.fsum(x * x for x in w[group]))
                    if norm > plan["head_norm_limit"]:
                        w[group] = [
                            x * plan["head_norm_limit"] / norm for x in w[group]
                        ]
    require(
        not pending and previous == array_hash(actual),
        "terminal checkpoint state identity",
    )
    error = max(abs(a - b) for row, other in zip(w, actual) for a, b in zip(row, other))
    require(
        error < 1e-9 and coefficient_error < 1e-9, "independent analytic replay differs"
    )
    return {
        "final_max_abs_error": error,
        "coefficient_max_abs_error": coefficient_error,
        "feedback_sha256": pin,
        "recorded_updates": len(receipts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("main", "cold", "source"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("main-sha256", "cold-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--paired-out", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    primary = read(args.main / "RESULT.json", args.main_sha256)
    cold = read(args.cold / "RESULT.json", args.cold_sha256)
    plan = read(args.source / "PLAN.json")
    tasks = read(args.source / "TASKS.json")["tasks"]
    labels = read(args.source / "EVAL_LABELS.json")
    train_labels = read(args.source / "TRAIN_FEEDBACK.json")
    publication = read(args.source / "PUBLICATION.json")
    require(publication["commit"] == SOURCE, "published source identity")
    require(len(publication["sources"]) == 7, "runtime source roster")
    for name, pin in publication["sources"].items():
        require(
            sha256((args.source / name).read_bytes()).hexdigest() == pin,
            "original runtime source hash",
        )
    for original, directory, denominator in (
        (primary, args.main, 1632),
        (cold, args.cold, 204),
    ):
        require(original["source_publication"] == SOURCE, "source commit")
        require(
            original["independent_future_B"] is False
            and original["decision"] == "HOLD_NO_GO",
            "unqualified promotion",
        )
        require(len(original["rows"]) == denominator, "fixed attempt denominator")
        require(
            all(original[k] == v for k, v in counts(original["rows"]).items()),
            "attempt/completion arithmetic",
        )
        pre = read(directory / "PREEXECUTION.json", original["preexecution_sha256"])
        require(
            pre["source_publication"] == publication
            and pre["source_sha256"] == publication["sources"],
            "native source bindings",
        )
        require(pre["assets"] == plan["model_sha256"], "native model asset binding")
        require(
            pre["evaluation_labels_parsed_before_training"] is False
            and pre["evaluation_label_bytes_hashed_before_training"] is True,
            "evaluation label access semantics",
        )
        journal(directory / "ROWS.jsonl", original)
    require(cold["original_result_sha256"] == args.main_sha256, "cold original binding")
    conditions = primary["conditions"]
    frozen = read(
        args.main / "FROZEN_CANDIDATES.json", primary["frozen_candidates_sha256"]
    )
    require(
        [
            {k: v for k, v in c.items() if k != "evaluation_wall_seconds"}
            for c in conditions
        ]
        == frozen,
        "candidate roster changed after freeze",
    )
    require(
        {c["condition"] for c in conditions}
        == {"base"}
        | {f"seed{seed}-{arm}" for seed in plan["seeds"] for arm in plan["arms"]},
        "condition roster",
    )
    source_tasks = {t["id"]: t for t in tasks if t["split"] != "train"}
    lookup, scores, training = {}, {}, {}
    features = read(args.main / "TRAIN_FEATURES.json")
    for condition in conditions:
        name = condition["condition"]
        rows = [r for r in primary["rows"] if r["condition"] == name]
        require(
            len(rows) == 96 and {r["id"] for r in rows} == set(source_tasks),
            "condition task roster",
        )
        scores[name] = {}
        for row in rows:
            task = source_tasks[row["id"]]
            require(
                all(row[k] == task[k] for k in ("group", "split", "source_cluster")),
                "task provenance",
            )
            lookup[(name, row["id"])] = row
        for split in ("content", "retention"):
            sub = [r for r in rows if r["split"] == split]
            valid = sum(answer(r) is not None for r in sub)
            correct = sum(answer(r) == labels[r["id"]] for r in sub)
            scores[name][split] = {
                "n": len(sub),
                "valid": valid,
                "correct": correct,
                "accuracy_including_invalid": correct / len(sub),
            }
        require(scores[name] == primary["scores"][name], "original score arithmetic")
        if name != "base":
            training[name] = replay_training(
                condition, args.main, tasks, train_labels, features, plan
            )
    for seed in plan["seeds"]:
        pins = {
            training[f"seed{seed}-{arm}"]["feedback_sha256"] for arm in plan["arms"]
        }
        require(len(pins) == 1, "same seed received unequal external feedback")
        for task_id in source_tasks:
            base, unchanged = (
                lookup[("base", task_id)],
                lookup[(f"seed{seed}-no_eligibility", task_id)],
            )
            require(
                (base["status"], base["text"], base["tokens"])
                == (unchanged["status"], unchanged["text"], unchanged["tokens"]),
                "no-eligibility content changed",
            )
    paired_rows = []
    paired_counts = {}
    for seed in plan["seeds"]:
        paired_counts[str(seed)] = {}
        for split in ("content", "retention"):
            rows = []
            for task_id, task in source_tasks.items():
                if task["split"] != split:
                    continue
                r, s = (
                    lookup[(f"seed{seed}-routed", task_id)],
                    lookup[(f"seed{seed}-shuffled", task_id)],
                )
                row = {
                    "seed": seed,
                    "id": task_id,
                    "source_cluster": task["source_cluster"],
                    "split": split,
                    "group": task["group"],
                    "pair": task.get("pair"),
                    "label": labels[task_id],
                }
                for arm, original in (("routed", r), ("shuffled", s)):
                    parsed = answer(original)
                    row[arm] = {
                        "status": original["status"],
                        "text": original["text"],
                        "tokens": original["tokens"],
                        "parsed": parsed,
                        "valid": parsed is not None,
                        "correct": parsed == labels[task_id],
                    }
                row["correct_difference_routed_minus_shuffled"] = int(
                    row["routed"]["correct"]
                ) - int(row["shuffled"]["correct"])
                rows.append(row)
            paired_rows.extend(rows)
            paired_counts[str(seed)][split] = {
                "n": len(rows),
                "both_correct": sum(
                    r["routed"]["correct"] and r["shuffled"]["correct"] for r in rows
                ),
                "routed_only_correct": sum(
                    r["routed"]["correct"] and not r["shuffled"]["correct"]
                    for r in rows
                ),
                "shuffled_only_correct": sum(
                    not r["routed"]["correct"] and r["shuffled"]["correct"]
                    for r in rows
                ),
                "neither_correct": sum(
                    not r["routed"]["correct"] and not r["shuffled"]["correct"]
                    for r in rows
                ),
                "routed_invalid": sum(not r["routed"]["valid"] for r in rows),
                "shuffled_invalid": sum(not r["shuffled"]["valid"] for r in rows),
                "correct_difference_routed_minus_shuffled": sum(
                    r["correct_difference_routed_minus_shuffled"] for r in rows
                ),
            }
    exact = 0
    for row in cold["rows"]:
        prior = lookup[(row["condition"], row["id"])]
        equal = row["status"] == prior["status"] == "completed" and all(
            row[k] == prior[k]
            for k in ("tokens", "text", "feature_sha256", "first_token_head_delta")
        )
        require(equal == row["exact_replay"], "cold equality flag")
        exact += equal
    require(cold["all_exact"] == (exact == 204), "cold aggregate equality")
    report = {
        "schema": "hpca-native-original-arithmetic-recheck-v1",
        "source": SOURCE,
        "original_main_sha256": args.main_sha256,
        "original_cold_sha256": args.cold_sha256,
        "main_counts": counts(primary["rows"]),
        "cold_counts": counts(cold["rows"]),
        "scores": scores,
        "training_arithmetic": training,
        "cold_exact": exact,
        "same_external_feedback_vectors": True,
        "no_eligibility_equals_base_rows": 384,
        "paired_routing_counts": paired_counts,
        "observation_unit": {
            "content_unique_tasks": 64,
            "content_source_cluster_strings": len(
                {t["source_cluster"] for t in tasks if t["split"] == "content"}
            ),
            "content_paired_blocks": 32,
            "repeated_training_seeds": len(plan["seeds"]),
            "retention_unique_tasks": 32,
            "retention_source_clusters": len(
                {t["source_cluster"] for t in tasks if t["split"] == "retention"}
            ),
            "seeds_do_not_create_new_tasks": True,
        },
        "new_model_calls": 0,
        "new_model_training": 0,
        "arithmetic_replayed_recorded_update_steps": sum(
            r["recorded_updates"] for r in training.values()
        ),
        "arithmetic_tolerance": 1e-9,
        "independent_future_B": False,
        "decision": "HOLD_NO_GO",
        "wall_seconds": time.perf_counter() - started,
    }
    if args.paired_out:
        with args.paired_out.open("x") as stream:
            json.dump(
                {
                    "schema": "hpca-routed-shuffled-paired-originals-v1",
                    "original_main_sha256": args.main_sha256,
                    "observation_unit": report["observation_unit"],
                    "counts": paired_counts,
                    "rows": paired_rows,
                },
                stream,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
        report["paired_originals_sha256"] = sha256(
            args.paired_out.read_bytes()
        ).hexdigest()
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
