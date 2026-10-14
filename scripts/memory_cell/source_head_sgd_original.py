"""Actual tiny source-supervised SGD head; matched authored heldout source test.

No Reader weights or generation, no test-label use before sealed predictions.
Four strict phases: prepare public data, fit source-only CALIBRATION relations,
predict with fixed CPU weights, THEN open author labels to score evidence choices.
This is a weak-label development mechanism probe, never learned Reader proof.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import zipfile

SOURCE_SHA = "31c6f191ecf62095779f7c9a5dd6c5b2f89c6ae408fe9c26f74e017a2d62c47a"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
PROFILE = "hepta.memory-cell.source-only-tiny-sgd-heldout.v1"
FEATURES = (
    "entity_matches_current_path_cursor",
    "attribute_matches_current_path_step",
    "entity_and_attribute_match",
    "not_future_revision",
    "is_retired_by_visible_supersession",
    "is_latest_visible_revision_for_entity_attribute",
    "has_supersession_edges",
    "has_later_future_revision",
    "candidate_order_reciprocal",
    "intercept",
)
ARMS = ("frozen_rank_only", "teacher_sgd", "shuffled_sgd", "frozen_organized")
STEPS = 192
REVISION = 2
INITIAL = (0., 0., 0., 0., 0., 0., 0., 0., 1., 0.)
QUERY = re.compile(
    r"\AFor ([a-zA-Z0-9_-]{1,96}) at logical revision ([0-9]+), what is "
    r"(the location|the location of the assigned component|"
    r"the mode that actually succeeded for the assigned component)\? "
)
PATHS = {
    "the location": ("location",),
    "the location of the assigned component": ("component", "location"),
    "the mode that actually succeeded for the assigned component": (
        "component", "successful_mode"
    ),
}


def h(raw):
    return hashlib.sha256(raw).hexdigest()


def strict(raw):
    def pairs(items):
        value = {}
        for key, val in items:
            if key in value:
                raise ValueError("duplicate original JSON key")
            value[key] = val
        return value

    def bad(value):
        raise ValueError("nonfinite original JSON " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def dump(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False,
                  sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def from_file(path, sha=None):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("bounded regular frozen artifact required")
    raw = path.read_bytes()
    if sha is not None and h(raw) != sha:
        raise ValueError("externally frozen artifact checksum changed")
    return strict(raw)


def source_bytes(path):
    if path.is_symlink() or not path.is_file() or h(path.read_bytes()) != SOURCE_SHA:
        raise ValueError("wrong original external source archive")
    with zipfile.ZipFile(path) as archive:
        entries = archive.namelist()
        if len(entries) != 36 or len(entries) != len(set(entries)):
            raise ValueError("changed original source ZIP member count")
        found = {}
        for line in archive.read("SHA256SUMS").decode().splitlines():
            match = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?([a-zA-Z0-9_.\-/]+)", line)
            if not match or match[2] in found or match[2] == "SHA256SUMS":
                raise ValueError("invalid source manifest")
            found[match[2]] = match[1]
        if set(found) != set(entries) - {"SHA256SUMS"}:
            raise ValueError("missing original ZIP member")
        for name, digest in found.items():
            if h(archive.read(name)) != digest:
                raise ValueError("source inner file checksum mismatch")
        if h(archive.read("plan/plan.json")) != PLAN_SHA:
            raise ValueError("original heldout plan changed")
        return {
            "plan": archive.read("plan/plan.json"),
            "documents": archive.read("plan/source-view.json"),
            # Intentionally never read observations/labels.json here.
        }


def parse_query(question):
    matched = QUERY.match(question["content"])
    if not matched or int(matched[2]) != REVISION:
        raise ValueError("unregistered public question grammar")
    return matched[1], PATHS[matched[3]], int(matched[2])


def events(documents):
    output = {}
    for doc in documents:
        if doc["identity"] in output:
            raise ValueError("duplicate original event")
        row = strict(doc["content"].encode())
        if (
            row.get("id") != doc["identity"]
            or row.get("schema") != "hepta.controlled-event.v1"
            or type(row.get("revision")) is not int
            or not 0 <= row["revision"] <= 10000
            or not isinstance(row.get("supersedes"), list)
            or len(set(row["supersedes"])) != len(row["supersedes"])
        ):
            raise ValueError("invalid original event projection")
        output[row["id"]] = row
    return output


def effective(rows, cursor, attribute, revision):
    """Source-only semantic relation teacher; not a human answer oracle."""
    retired = {
        old for e in rows.values() if e["revision"] <= revision
        for old in e["supersedes"]
    }
    candidates = [
        (key, row) for key, row in rows.items()
        if row["entity"] == cursor and row["attribute"] == attribute
        and row["revision"] <= revision and key not in retired
    ]
    if not candidates:
        raise ValueError("incomplete source-defined calibration relation")
    best = max(row["revision"] for _, row in candidates)
    newest = [key for key, row in candidates if row["revision"] == best]
    if len(newest) != 1:
        raise ValueError("ambiguous current original source event")
    return newest[0]


def source_path(rows, entity, path, *, revision=REVISION):
    cursor, answer = entity, []
    for attr in path:
        key = effective(rows, cursor, attr, revision)
        answer.append(key)
        cursor = rows[key]["value"]
    return answer


def factors(rows, ordered, cursor, attr, revision):
    retired = {
        old for event in rows.values() if event["revision"] <= revision
        for old in event["supersedes"]
    }
    features = []
    for index, key in enumerate(ordered):
        row = rows[key]
        visible = row["revision"] <= revision
        all_versions = [
            e["revision"] for other_key, e in rows.items()
            if e["entity"] == row["entity"]
            and e["attribute"] == row["attribute"]
            and e["revision"] <= revision and other_key not in retired
        ]
        values = (
            float(row["entity"] == cursor),
            float(row["attribute"] == attr),
            float(row["entity"] == cursor and row["attribute"] == attr),
            float(visible),
            float(key in retired),
            float(visible and key not in retired and all_versions
                  and row["revision"] == max(all_versions)),
            float(bool(row["supersedes"])),
            float(row["revision"] > revision),
            1.0 / (index + 1),
            1.0,
        )
        if len(values) != len(FEATURES):
            raise ValueError("feature dimension drift")
        features.append(values)
    return features


def prepare(source, out):
    archive = source_bytes(source)
    plan, docs = strict(archive["plan"]), strict(archive["documents"])
    heldout = {x["query"]["identity"] for x in plan["cases"]}
    scopes = {d["scope"] for d in docs}
    training = scopes - heldout
    if (
        len(heldout) != 8 or len(training) != 8 or len(docs) != 108
        or plan["schema"] != "hepta.event-organization.plan.v1"
        or plan["independent_human_review"] is not False
        or plan["token_limit"] != 2048
        or len({d["identity"] for d in docs}) != len(docs)
    ):
        raise ValueError("incorrect original 8/8 source split")
    by_scope = defaultdict(list)
    for d in docs:
        by_scope[d["scope"]].append(d)
    train_rows = []
    for scope in sorted(training):
        docs_one = by_scope[scope]
        rows = events(docs_one)
        entity = "service_" + scope.removeprefix("controlled_")
        components = [r for r in rows.values() if r["entity"] == entity
                      and r["attribute"] == "component" and r["revision"] <= REVISION]
        if components:
            first = effective(rows, entity, "component", REVISION)
            target = rows[first]["value"]
            path = ("component", "successful_mode") if any(
                r["entity"] == target and r["attribute"] == "successful_mode"
                for r in rows.values()
            ) else ("component", "location")
        else:
            path = ("location",)
        gold = source_path(rows, entity, path)
        train_rows.append(dict(scope=scope, docs=docs_one, entity=entity,
                               path=list(path), support=gold, revision=REVISION))
    test_rows = []
    for case in plan["cases"]:
        scope = case["query"]["scope"]
        entity, path, rev = parse_query(case["query"])
        if scope not in heldout or entity != "service_" + scope.removeprefix("controlled_"):
            raise ValueError("original query scope changed")
        selected = case["controls"]["organized"]["selected"]
        cand = case["candidate_ids"]
        if len(set(cand)) != len(cand) or not set(selected).issubset(cand):
            raise ValueError("incompatible frozen control sources")
        test_rows.append(dict(scope=scope, docs=by_scope[scope], entity=entity,
                              path=list(path), revision=rev, candidate_ids=cand,
                              organized=selected, kind=case["kind"]))
    out.mkdir()
    train_dest = out / "calibration-source-only.json"
    test_dest = out / "heldout-public-input.json"
    dump(train_dest, dict(profile=PROFILE, source_zip_sha256=SOURCE_SHA,
                          training_scopes=sorted(training), cases=train_rows,
                          test_queries_present=False, test_labels_present=False))
    dump(test_dest, dict(profile=PROFILE, source_zip_sha256=SOURCE_SHA,
                         heldout_scopes=sorted(heldout), cases=test_rows,
                         target_labels_present=False, calibration_sources_present=False))
    dump(out / "split-manifest.json", dict(
        profile=PROFILE, source_zip_sha256=SOURCE_SHA,
        original_plan_sha256=PLAN_SHA, training_cases=8, heldout_cases=8,
        calibration_sha256=h(train_dest.read_bytes()),
        heldout_public_sha256=h(test_dest.read_bytes()),
        author_generated_development_tasks=True, independent_source_families=0,
        independent_sufficient_evidence_review=False,
        original_label_member_sha256_verified_but_not_parsed=True,
        original_label_content_not_exported_to_training=True,
        model_calls=0, production_accepted=False))


def train(path, output, *, expected_sha):
    import torch
    torch.set_num_threads(1)
    x = from_file(path, expected_sha)
    if (
        set(x) != {"profile", "source_zip_sha256", "training_scopes", "cases",
                   "test_queries_present", "test_labels_present"}
        or x["profile"] != PROFILE
        or x["source_zip_sha256"] != SOURCE_SHA
        or x["test_labels_present"] is not False
        or x["test_queries_present"] is not False
        or len(x["cases"]) != 8
        or len(set(x["training_scopes"])) != 8
        or {c["scope"] for c in x["cases"]} != set(x["training_scopes"])
        or any(set(c) != {"scope", "docs", "entity", "path", "support", "revision"}
               or c["revision"] != REVISION
               or not c["docs"]
               or any(d["scope"] != c["scope"] for d in c["docs"])
               for c in x["cases"])
    ):
        raise ValueError("train-only admitted source corpus required")
    examples = []
    for case in x["cases"]:
        rows = events(case["docs"])
        if source_path(rows, case["entity"], case["path"]) != case["support"]:
            raise ValueError("calibration labels not a property of original sources")
        cursor = case["entity"]
        ordered = sorted(rows)
        for target, attr in zip(case["support"], case["path"], strict=True):
            features = torch.tensor(
                factors(rows, ordered, cursor, attr, case["revision"]),
                dtype=torch.float64,
            )
            examples.append((features, ordered.index(target)))
            cursor = rows[target]["value"]
    if not len(examples) == 12:
        raise ValueError("expected 8 authored train tasks / 12 path hops")
    initial = torch.tensor(INITIAL, dtype=torch.float64)
    learned = {}
    statistics = {}
    for arm in ("teacher_sgd", "shuffled_sgd"):
        weights = torch.nn.Parameter(initial.clone())
        optimizer = torch.optim.AdamW([weights], lr=0.05)
        started = time.perf_counter()
        losses = []
        for step in range(STEPS):
            features, target = examples[step % len(examples)]
            if arm == "shuffled_sgd":
                target = (target + 1) % len(features)
            logits = features @ weights
            loss = torch.logsumexp(logits, dim=0) - logits[target]
            loss = loss + 0.001 * (weights - initial).square().sum()
            if not torch.isfinite(loss):
                raise ValueError("nonfinite actual SGD loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_([weights], 1.0)
            optimizer.step()
            losses.append(float(loss.detach()))
        observed = weights.detach().tolist()
        if not all(math.isfinite(w) and abs(w) < 100 for w in observed):
            raise ValueError("unstable actual learning parameters")
        delta = sum((w - i) ** 2 for w, i in zip(observed, INITIAL))
        if not delta > 0:
            raise ValueError("no real gradient-based parameter update")
        learned[arm] = observed
        statistics[arm] = dict(
            objective="source-event-path-next-hop-cross-entropy",
            steps=STEPS, parameter_count=len(FEATURES),
            gradient_updates=STEPS, actual_update_squared_l2=delta,
            train_loss_first=losses[0], train_loss_final=losses[-1],
            observed_train_cpu_seconds=time.perf_counter() - started,
            constructed_feature_examples=len(examples),
            labels="source-only-teacher" if arm == "teacher_sgd" else "rotated-null-control",
        )
    dump(output, dict(
        profile=PROFILE, calibration_sha256=expected_sha,
        weights=dict(frozen_rank_only=list(INITIAL), **learned),
        frozen_before_test=True, tested_questions_exposed=False,
        feature_keys=FEATURES, training=statistics,
        train_source_bytes=path.stat().st_size,
        heldout_task_metric=None, actual_model_generations=0,
        params_learned_not_same_as_reader_weights=True,
        independent_source_family_count=0, production_accepted=False,
        torch_runtime=str(torch.__version__),
    ))


def predict(data, policy, output, *, data_sha, policy_sha):
    input_set, trained = from_file(data, data_sha), from_file(policy, policy_sha)
    if (
        set(input_set) != {"profile", "source_zip_sha256", "heldout_scopes",
                           "cases", "target_labels_present",
                           "calibration_sources_present"}
        or input_set.get("profile") != PROFILE
        or input_set.get("source_zip_sha256") != SOURCE_SHA
        or trained.get("profile") != PROFILE
        or input_set.get("calibration_sources_present") is not False
        or input_set.get("target_labels_present") is not False
        or trained.get("frozen_before_test") is not True
        or trained.get("tested_questions_exposed") is not False
        or len(input_set.get("cases", [])) != 8
        or len(set(input_set.get("heldout_scopes", []))) != 8
        or {c["scope"] for c in input_set["cases"]}
        != set(input_set["heldout_scopes"])
        or any(set(c) != {"scope", "docs", "entity", "path", "revision",
                              "candidate_ids", "organized", "kind"}
               for c in input_set["cases"])
        or set(trained["weights"]) != {"teacher_sgd", "shuffled_sgd", "frozen_rank_only"}
        or trained.get("feature_keys") != list(FEATURES)
        or any(len(trained["weights"][arm]) != len(FEATURES)
               for arm in trained["weights"])
    ):
        raise ValueError("unfrozen read policy or leaked heldout targets")
    predictions = []
    for case in input_set["cases"]:
        rows = events(case["docs"])
        candidates = case["candidate_ids"]
        if len(set(candidates)) != len(candidates) or set(candidates) != set(rows):
            raise ValueError("candidate set changed after source freezing")
        for arm in ARMS:
            cursor = case["entity"]
            chosen = []
            if arm == "frozen_organized":
                chosen = case["organized"]
            else:
                for attr in case["path"]:
                    keys = [key for key in candidates if key not in chosen]
                    feats = factors(rows, keys, cursor, attr, case["revision"])
                    weights = trained["weights"][arm]
                    scores = [sum(a * b for a, b in zip(v, weights, strict=True))
                              for v in feats]
                    winner = min(range(len(keys)), key=lambda i: (-scores[i], keys[i]))
                    chosen.append(keys[winner])
                    cursor = rows[keys[winner]]["value"]
            predictions.append(dict(
                scope=case["scope"], kind=case["kind"], arm=arm,
                selected=chosen,
                evidence_candidate_pool_sha256=h(canonical(candidates)),
                trainable_parameters=(len(FEATURES) if "sgd" in arm else 0),
                actual_reader_model_calls=0,
                independent_semantic_review=False,
            ))
    if len(predictions) != 32:
        raise ValueError("32 frozen source-only test selections required")
    dump(output, dict(profile=PROFILE, predictions=predictions,
                      public_test_data_sha256=data_sha, policy_sha256=policy_sha,
                      heldout_label_bytes_opened=False, original_model_calls=0,
                      no_future_window_independence=True,
                      production_accepted=False))


def score(source, preds, policy, output, *, predictions_sha, policy_sha):
    data = from_file(preds, predictions_sha)
    trained = from_file(policy, policy_sha)
    if (
        data.get("policy_sha256") != policy_sha
        or trained.get("profile") != PROFILE
        or trained.get("frozen_before_test") is not True
        or trained.get("tested_questions_exposed") is not False
        or trained.get("actual_model_generations") != 0
        or trained.get("feature_keys") != list(FEATURES)
        or set(trained.get("training", {})) != {"teacher_sgd", "shuffled_sgd"}
        or any(
            item.get("steps") != STEPS
            or item.get("gradient_updates") != STEPS
            or item.get("parameter_count") != len(FEATURES)
            or not item.get("actual_update_squared_l2", 0) > 0
            for item in trained["training"].values()
        )
    ):
        raise ValueError("missing real frozen gradient-update provenance")
    if (
        data.get("profile") != PROFILE
        or data.get("heldout_label_bytes_opened") is not False
        or data.get("original_model_calls") != 0
        or len(data.get("predictions", [])) != 32
    ):
        raise ValueError("unsealed or incomplete before-gold selection journal")
    if source.is_symlink() or not source.is_file() or h(source.read_bytes()) != SOURCE_SHA:
        raise ValueError("wrong original gold source ZIP")
    with zipfile.ZipFile(source) as archive:
        plan_data = archive.read("plan/plan.json")
        if h(plan_data) != PLAN_SHA:
            raise ValueError("original candidate plan drift after prediction")
        plan = strict(plan_data)
        truth = strict(archive.read("observations/labels.json"))
    original_by_id = {case["query"]["identity"]: case for case in plan["cases"]}
    test_gold = {row["id"]: row for row in truth if row["phase"] == "test"}
    if len(test_gold) != 8:
        raise ValueError("source phase partition moved")
    expected = {(scope, arm) for scope in test_gold for arm in ARMS}
    seen = set()
    correct, recall = defaultdict(int), defaultdict(int)
    per_case = []
    for row in data["predictions"]:
        key = (row["scope"], row["arm"])
        if key not in expected or key in seen or row["kind"] != test_gold[row["scope"]]["kind"]:
            raise ValueError("unknown or duplicate author development task arm")
        case = original_by_id[row["scope"]]
        candidates = case["candidate_ids"]
        if (
            row.get("evidence_candidate_pool_sha256") != h(canonical(candidates))
            or not isinstance(row.get("selected"), list)
            or len(row["selected"]) != len(test_gold[row["scope"]]["path"])
            or len(set(row["selected"])) != len(row["selected"])
            or any(key not in candidates for key in row["selected"])
            or (row["arm"] == "frozen_organized"
                and row["selected"] != case["controls"]["organized"]["selected"])
            or row.get("trainable_parameters")
            != (len(FEATURES) if "sgd" in row["arm"] else 0)
            or row.get("actual_reader_model_calls") != 0
            or row.get("independent_semantic_review") is not False
        ):
            raise ValueError("predictions not bound to same frozen evidence pool")
        seen.add(key)
        support = test_gold[row["scope"]]["support"]
        exact = row["selected"] == support
        covered = set(support).issubset(row["selected"])
        correct[row["arm"]] += exact
        recall[row["arm"]] += covered
        per_case.append(dict(scope=row["scope"], kind=row["kind"],
                             arm=row["arm"], selected=row["selected"],
                             support_exact=exact, support_covered=covered))
    if seen != expected:
        raise ValueError("missing before-gold paired source selectors")
    stats = {arm:dict(support_exact=correct[arm], support_covered=recall[arm],
                      tasks=8) for arm in ARMS}
    dump(output, dict(
        profile=PROFILE,
        source_zip_sha256=SOURCE_SHA,
        frozen_before_gold_prediction_sha256=predictions_sha,
        source_only_support_metric=True, gold_kind="author_development_support",
        original_frozen_strong_organizer_ceiling=stats["frozen_organized"],
        arms=stats, per_case=per_case,
        actual_new_model_generations=0,
        actual_torch_parameter_updates_verified_from_frozen_policy=True,
        frozen_sgd_policy_sha256=policy_sha,
        model_output_quality_measured=False,
        trained_head_replaces_reader_weights=False,
        independent_future_project_families=0,
        claimed_production_generalization=False,
        production_accepted=False,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("source", type=Path)
    prepare_cmd.add_argument("output", type=Path)
    fit_cmd = sub.add_parser("fit")
    fit_cmd.add_argument("train", type=Path)
    fit_cmd.add_argument("output", type=Path)
    fit_cmd.add_argument("--input-sha", required=True)
    pred = sub.add_parser("predict")
    pred.add_argument("public", type=Path)
    pred.add_argument("model", type=Path)
    pred.add_argument("output", type=Path)
    pred.add_argument("--public-sha", required=True)
    pred.add_argument("--model-sha", required=True)
    scorer = sub.add_parser("score")
    scorer.add_argument("source", type=Path)
    scorer.add_argument("predictions", type=Path)
    scorer.add_argument("policy", type=Path)
    scorer.add_argument("output", type=Path)
    scorer.add_argument("--predictions-sha", required=True)
    scorer.add_argument("--policy-sha", required=True)
    args = parser.parse_args()
    if args.cmd == "prepare":
        prepare(args.source, args.output)
    elif args.cmd == "fit":
        train(args.train, args.output, expected_sha=args.input_sha)
    elif args.cmd == "predict":
        predict(args.public, args.model, args.output,
                data_sha=args.public_sha, policy_sha=args.model_sha)
    else:
        score(args.source, args.predictions, args.policy, args.output,
              predictions_sha=args.predictions_sha, policy_sha=args.policy_sha)


if __name__ == "__main__":
    main()
