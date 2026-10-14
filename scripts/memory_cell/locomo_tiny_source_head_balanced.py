"""Corrected genuine six-family LoCoMo 10-param source-only SGD transfer.

New post-audit **exploratory** family-balanced protocol. Does not reuse or
silently overwrite original one-family v1 checkpoint. 192 updates = 32 for
EACH of six TRAIN conversation-family proxies; source-only labels are excerpt
self-reconstruction, never published QA targets. Two original SELECTION
families constitute a retrospective held-out proxy, not prospective evidence.
"""

from collections import Counter, defaultdict
import argparse
import math
from pathlib import Path

from locomo_tiny_source_head_transfer import (
    ARMS, DEC_SHA, FEATURES, GENERATING, POP_SHA, PUB_SHA, STEPS,
    canonical, choose8, idf_from_train, loaded_public,
    pseudo_training_data, regular, sha, strict,
)

SCHEMA = "hepta.memorycell.locomo-six-family-balanced-source-head.v2"
SPLIT = "selection"  # original 2-family selection cut; no previous eval target reused.


def schedule_six_families(population, training_rows):
    groups = defaultdict(list)
    for row in training_rows:
        original_id = row[0]
        scope = original_id.split("/")[0]
        groups[scope].append(row)
    train_scopes = sorted({item["scope"] for item in population["splits"]["train"]})
    if set(groups) != set(train_scopes) or len(train_scopes) != 6:
        raise ValueError("six actual disjoint original TRAIN families required")
    schedule = []
    for step in range(STEPS):
        family = train_scopes[step % len(train_scopes)]
        candidates = groups[family]
        selected = candidates[(step // len(train_scopes)) % len(candidates)]
        schedule.append((family, selected))
    counts = Counter(family for family, _ in schedule)
    if len(counts) != 6 or set(counts.values()) != {32}:
        raise ValueError("192 updates must sample all six families equally")
    return schedule, dict(sorted(counts.items()))


def train(public_zip, decision_zip, out):
    import torch

    population, docs, _ = loaded_public(public_zip, decision_zip)
    idf = idf_from_train(population, docs)
    rows = pseudo_training_data(population, docs, idf)
    schedule, counts = schedule_six_families(population, rows)
    learned = {}
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(20261014)
        for arm in ("trained_head_k8", "shuffled_null_k8"):
            theta = torch.nn.Parameter(torch.zeros(len(FEATURES), dtype=torch.float64))
            optimizer = torch.optim.AdamW([theta], lr=0.035, weight_decay=0.01)
            first = theta.detach().clone()
            losses = []
            for step, (_, (key, query, vectors)) in enumerate(schedule):
                logits = torch.tensor(vectors, dtype=torch.float64) @ theta
                wanted = 0 if arm == "trained_head_k8" else step % 7 + 1
                loss = torch.logsumexp(logits, 0) - logits[wanted]
                loss = loss + 0.001 * (theta - first).square().sum()
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite source-only TRAIN loss")
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(
                    [theta], 1.0, error_if_nonfinite=True
                )
                optimizer.step()
                losses.append(float(loss.detach()))
            weights = theta.detach().tolist()
            l2 = sum(x * x for x in weights)
            if not l2 > 0 or not all(math.isfinite(x) and abs(x) < 100 for x in weights):
                raise ValueError("no actual finite learned Head parameter update")
            learned[arm] = dict(
                weights=weights, gradient_updates=STEPS, parameters=len(FEATURES),
                source_family_update_counts=counts,
                real_optimization=True, shuffled_placebo=arm == "shuffled_null_k8",
                delta_squared_l2=l2, first_loss=losses[0], final_loss=losses[-1],
            )
    result = dict(
        schema=SCHEMA, published_source_sha256=PUB_SHA,
        published_frozen_retrieval_sha256=DEC_SHA,
        original_public_generating_commit=GENERATING,
        trained_on_original_family_proxies=6,
        training_source_examples=len(rows),
        actual_optimizer_source_family_count=6,
        total_gradient_updates=2 * STEPS,
        label_free_self_supervision=True,
        original_benchmark_QA_labels_read=False,
        test_or_selection_questions_used_in_gradient_updates=False,
        model_answers_generated=0, feature_keys=FEATURES,
        torch_runtime=str(torch.__version__), weights=learned,
        production_accepted=False,
    )
    with Path(out).open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    return result


def predict(public_zip, decision_zip, policy_file, out):
    population, docs, catalog = loaded_public(public_zip, decision_zip)
    policy = strict(regular(policy_file))
    if (
        policy.get("schema") != SCHEMA
        or policy.get("published_source_sha256") != PUB_SHA
        or policy.get("published_frozen_retrieval_sha256") != DEC_SHA
        or policy.get("actual_optimizer_source_family_count") != 6
        or policy.get("total_gradient_updates") != 2 * STEPS
        or policy.get("original_benchmark_QA_labels_read") is not False
        or policy.get("test_or_selection_questions_used_in_gradient_updates") is not False
        or set(policy.get("weights", {})) != {"trained_head_k8", "shuffled_null_k8"}
        or any(
            len(policy["weights"][key]["source_family_update_counts"]) != 6
            or set(policy["weights"][key]["source_family_update_counts"].values())
            != {32}
            for key in ("trained_head_k8", "shuffled_null_k8")
        )
    ):
        raise ValueError("not a six-family-balanced before-target actual Head")
    idf = idf_from_train(population, docs)
    cases = population["splits"][SPLIT]
    recorded = []
    for item in cases:
        for arm in ARMS:
            if arm.startswith("frozen_"):
                prior = "lexical_k8" if arm == "frozen_lexical_k8" else "recent_k8"
                selected = catalog[item["question_id"], prior]["selected"]
            else:
                selected = choose8(
                    item["question"], item["source_ids"], docs, idf,
                    policy["weights"][arm]["weights"],
                )
            recorded.append(dict(
                question_id=item["question_id"], arm=arm,
                family_proxy_digest=item["family_proxy_digest"],
                scope=item["scope"],
                source_census_sha256=item["source_census_sha256"],
                selected=selected,
                selected_source_bytes=sum(
                    len(docs[source]["content"].encode()) for source in selected
                ),
                heldout_annotated_targets_opened=False,
                model_answer_calls=0,
            ))
    if len(recorded) != 16 * len(ARMS):
        raise ValueError("incomplete original sixteen-question selected candidates")
    result = dict(
        schema=SCHEMA, split=SPLIT,
        published_source_sha256=PUB_SHA,
        original_retrieval_sha256=DEC_SHA,
        frozen_policy_sha256=sha(regular(policy_file)),
        original_source_family_proxy_count=2,
        source_only_before_annotated_target=True,
        model_answer_calls=0, predictions=recorded,
        published_benchmark_not_prospective=True,
        production_accepted=False,
    )
    with Path(out).open("xb") as stream:
        stream.write(canonical(result) + b"\n")
    return result


def seal(policy_file, predictions_file, output):
    policy, pred = [strict(regular(p)) for p in (policy_file, predictions_file)]
    if (
        policy.get("schema") != SCHEMA or pred.get("schema") != SCHEMA
        or pred.get("split") != SPLIT
        or pred.get("source_only_before_annotated_target") is not True
        or pred.get("model_answer_calls") != 0
        or len(pred.get("predictions", [])) != 16 * len(ARMS)
        or pred.get("frozen_policy_sha256") != sha(regular(policy_file))
        or policy.get("total_gradient_updates") != 384
        or policy.get("original_benchmark_QA_labels_read") is not False
    ):
        raise ValueError("pre-target source-only selection was not sealed")
    receipt = dict(
        schema=SCHEMA, original_source_sha256=PUB_SHA,
        original_frozen_retrieval_sha256=DEC_SHA,
        original_generating_commit=GENERATING,
        scored_split=SPLIT,
        train_family_proxy_count=6,
        evaluation_family_proxy_count=2,
        original_target_zip_opened=False,
        source_only_gradient_updates=384,
        files={Path(policy_file).name: sha(regular(policy_file)),
               Path(predictions_file).name: sha(regular(predictions_file))},
        new_model_answers=0,
        already_published_benchmark_not_future=True,
        production_accepted=False,
    )
    with Path(output).open("xb") as stream:
        stream.write(canonical(receipt) + b"\n")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)
    for phase in ("train", "predict", "seal"):
        command = sub.add_parser(phase)
        if phase != "seal":
            command.add_argument("public_zip", type=Path)
            command.add_argument("decision_zip", type=Path)
        if phase != "train":
            command.add_argument("policy", type=Path)
        if phase == "seal":
            command.add_argument("predictions", type=Path)
        command.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.phase == "train":
        train(args.public_zip, args.decision_zip, args.output)
    elif args.phase == "predict":
        predict(args.public_zip, args.decision_zip, args.policy, args.output)
    else:
        seal(args.policy, args.predictions, args.output)


if __name__ == "__main__":
    main()
