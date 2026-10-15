"""Independent stdlib audit of V5 controlled learning and physical receipts.

No torch is imported, no official validation file is read, and reported pass flags
never establish qualification. Checkpoint file bytes are authenticated; in-memory
tensor digests are cross-bound to receipts, not independently reconstructed.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import re


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _check(condition, message):
    if not condition:
        raise ValueError(message)


def _rows(cases):
    return [asdict(c) if is_dataclass(c) else dict(c) for c in cases]


def _id(row):
    return json.dumps([row[k] for k in ("source_split", "paragraph_id", "question_id", "answer_id")], separators=(",", ":"))


def _semantic(row, source_only=False):
    facts = sorted(" ".join(f.split()) for f in row["facts"])
    return _digest(facts if source_only else dict(facts=facts, question=" ".join(row["question"].split()),
                                                candidate=" ".join(row["candidate"].split())))


def _groups(cases):
    rows, groups, identifiers, semantics = _rows(cases), defaultdict(list), set(), set()
    for index, row in enumerate(rows):
        _check(len(row["facts"]) == 4 and list(row["sentence_ids"]) == [1, 2, 3, 4], "four source sentences required")
        owners, stores, support_indices = {}, {}, {}
        for sentence_index, sentence in enumerate(row["facts"], 1):
            own = re.fullmatch(r"The (\w+) belongs to ([A-Z]\w*)\.", sentence)
            store = re.fullmatch(r"([A-Z]\w*) stores all their possessions in the (\w+) box\.", sentence)
            _check(bool(own or store), "unrecognized independent binding grammar")
            key, value = (own or store).groups()
            relation = owners if own else stores
            _check(key not in relation, "duplicate independent relation")
            relation[key] = value
            support_indices[("own" if own else "store", key)] = sentence_index
        question = re.fullmatch(r"Where is the (\w+) stored\?", row["question"])
        answer = re.fullmatch(r"The (\w+) box\.", row["candidate"])
        _check(len(owners) == len(stores) == 2 and set(owners.values()) == set(stores)
               and len(set(owners.values())) == len(set(stores.values())) == 2
               and question is not None and question[1] in owners and answer is not None
               and answer[1] in stores.values(), "non-bijective independent binding grammar")
        person = owners[question[1]]
        _check(type(row["label"]) is int and row["label"] == int(stores[person] == answer[1]), "independent truth mismatch")
        _check(sorted(row["evidence_sentence_indices"]) == sorted((support_indices[("own", question[1])],
            support_indices[("store", person)])), "independent support mismatch")
        _check(row["source_hash"] == sha256("\n".join(row["facts"]).encode()).hexdigest(), "source byte hash mismatch")
        _check(row["segmentation"] == "synthetic-ownership-storage-v1", "unknown binding grammar identity")
        _check(_id(row) not in identifiers and _semantic(row) not in semantics, "duplicate binding task")
        identifiers.add(_id(row))
        semantics.add(_semantic(row))
        prefix, separator, world = row["paragraph_id"].rpartition("/world-")
        _check(separator and world in ("0", "1") and row["answer_id"] in ("0", "1"), "invalid world/candidate identity")
        groups[prefix].append((world, row, index, owners, stores))
    _check(bool(rows), "nonempty binding domain required")
    for values in groups.values():
        _check(len(values) == 4 and {(w, r["answer_id"]) for w, r, *_ in values}
               == {(w, a) for w in ("0", "1") for a in ("0", "1")}, "incomplete paired-world group")
        worlds = [[value for value in values if value[0] == world] for world in ("0", "1")]
        _check(len({r["question"] for _, r, *_ in values}) == 1, "paired question mismatch")
        for world in worlds:
            _check(world[0][1]["facts"] == world[1][1]["facts"]
                   and {r["label"] for _, r, *_ in world} == {0, 1}, "within-world candidate mismatch")
        a, b = worlds[0][0], worlds[1][0]
        _check(a[4] == b[4] and a[3].keys() == b[3].keys()
               and all(person != b[3][obj] for obj, person in a[3].items()), "ownership-only intervention violated")
        _check(Counter(" ".join(a[1]["facts"]).split()) == Counter(" ".join(b[1]["facts"]).split()), "word bag mismatch")
        for answer_id in ("0", "1"):
            pair = [value for value in values if value[1]["answer_id"] == answer_id]
            _check(pair[0][1]["candidate"] == pair[1][1]["candidate"]
                   and pair[0][1]["label"] != pair[1][1]["label"], "paired candidate mismatch")
    return rows, groups


def audit_protocol(parts, manifest):
    """Verify independently parsed truth, exact V4 reuse and every manifest row."""
    from token_protocol import build_binding_cases

    roles = ("reader_train", "internal_tune", "verifier_fit", "fresh_combinations", "fresh_vocabulary")
    _check(set(parts) == set(roles) == set(manifest["roles"]), "protocol roles mismatch")
    old = [asdict(c) for split, size in (("train", 32), ("tune", 16), ("final", 32))
           for c in build_binding_cases(split, groups=size, seed=41)]
    seen, sources = {_semantic(r) for r in old}, {_semantic(r, True) for r in old}
    _check(manifest["old_v4_exclusions_sha256"] == _digest(sorted(_semantic(r) for r in old)), "old exclusions changed")
    counts = {}
    for role in roles:
        rows, groups = _groups(parts[role])
        size = 64 if role == "internal_tune" else 128
        _check(len(rows) == size, "protocol candidate count mismatch")
        if role in ("reader_train", "internal_tune"):
            split = "train" if role == "reader_train" else "tune"
            expected = [asdict(c) for c in build_binding_cases(split, groups=size // 4, seed=41)]
            _check(_digest(rows) == _digest(expected), "old V4 train/tune changed")
        else:
            keys, current_sources = {_semantic(r) for r in rows}, {_semantic(r, True) for r in rows}
            _check(not keys & seen and not current_sources & sources, "semantic/source overlap")
            seen.update(keys)
            sources.update(current_sources)
            names = set("Alden Briar Cassia Dorian Elian Freya Galen Hazel".split()) if role == "fresh_vocabulary" else set("Ada Ben Cleo Drew Esme Finn Gina Hugo".split())
            objects = set("anchor lantern ribbon pebble locket whistle prism thimble".split()) if role == "fresh_vocabulary" else set("coin bead token key button marble shell stamp".split())
            for values in groups.values():
                for _, row, _, owners, stores in values:
                    _check(set(owners) <= objects and set(stores) <= names, "lexical domain mismatch")
                    _check(row["paragraph_id"].startswith(f"binding-v5/{role}/{manifest['protocol_seed']}/"), "role/seed mismatch")
                    _check(row["source_split"] == ("validation" if role.startswith("fresh_") else "train"), "source role mismatch")
        bound = manifest["roles"][role]
        _check(bound["cases"] == len(rows) and bound["groups"] == len(groups)
               and bound["paired_candidates"] == 2 * len(groups)
               and bound["semantic_tasks_sha256"] == _digest(sorted(_semantic(r) for r in rows)), "manifest counts/semantics mismatch")
        _check(bound["case_ids"] == [_id(r) for r in rows], "manifest candidate membership mismatch")
        _check(bound["source_hashes"] == sorted({r["source_hash"] for r in rows}), "manifest source membership mismatch")
        _check(bound["complete_labeled_cases_sha256"] == _digest(rows), "manifest labeled source digest mismatch")
        counts[role] = dict(cases=len(rows), groups=len(groups))
    reserved = manifest["roles"]["verifier_fit"]
    _check(reserved["usage"] == "reserved_unused" and not any(reserved[k] for k in
           ("encoding_authorized", "scoring_authorized", "training_authorized")), "unused verifier role misrepresented")
    return dict(passed=True, domains=counts, official_validation_read=False, independent_grammar=True)


def audit_scores(cases, probabilities, reported=None):
    rows, groups = _groups(cases)
    probabilities = list(probabilities)
    _check(len(probabilities) == len(rows) and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
                                                for p in probabilities), "finite complete probabilities required")
    predictions, paired, switches, signed, absolute, complete = [int(p > .5) for p in probabilities], 0, 0, [], [], 0
    for values in groups.values():
        complete += all(predictions[index] == row["label"] for _, row, index, *_ in values)
        for answer_id in ("0", "1"):
            pair = [(row, index) for _, row, index, *_ in values if row["answer_id"] == answer_id]
            positive = next(index for row, index in pair if row["label"])
            negative = next(index for row, index in pair if not row["label"])
            paired += predictions[positive] == 1 and predictions[negative] == 0
            switches += predictions[positive] != predictions[negative]
            signed.append(probabilities[positive] - probabilities[negative])
            absolute.append(abs(signed[-1]))
    metrics = dict(cases=len(rows), groups=len(groups), paired_candidates=2 * len(groups),
        accuracy=sum(predictions[i] == row["label"] for i, row in enumerate(rows)) / len(rows),
        probability_CE=-sum(math.log(max(1e-12, p if row["label"] else 1-p)) for row, p in zip(rows, probabilities)) / len(rows),
        both_worlds_correct=paired / len(signed), evidence_switch_rate=switches / len(signed),
        all_four_correct=complete / len(groups), mean_truth_signed_world_probability_gap=sum(signed) / len(signed),
        mean_absolute_world_probability_gap=sum(absolute) / len(absolute),
        positive_truth_gap_rate=sum(value > 0 for value in signed) / len(signed))
    if reported is not None:
        # Training CE was computed directly from logits. Saved FP32 softmax
        # probabilities can round near 0/1 and cannot reconstruct that value.
        # Canonical panel probability_CE is instead recomputed from saved p.
        aliases = dict(n="cases")
        for key, expected in metrics.items():
            name = key if key in reported else next((alias for alias, target in aliases.items() if target == key and alias in reported), None)
            if name is not None:
                value = reported[name]
                _check(type(value) in (int, float) and math.isfinite(value)
                       and math.isclose(value, expected, abs_tol=2e-6, rel_tol=1e-6), "reported metric mismatch: " + key)
        if "predictions" in reported:
            _check(reported["predictions"] == predictions, "reported predictions differ from raw p>0.5")
        if "binary_cross_entropy" in reported:
            value = reported["binary_cross_entropy"]
            _check(type(value) in (int, float) and math.isfinite(value) and value >= 0,
                   "training logit-space CE must be finite and nonnegative")
    return metrics


def _gate(metrics):
    return (metrics["cases"] == 128 and metrics["groups"] == 32 and metrics["paired_candidates"] == 64
            and metrics["accuracy"] == metrics["both_worlds_correct"] == metrics["all_four_correct"] == 1
            and metrics["probability_CE"] <= .10)


def _cost(record):
    for key in ("cpu_ns", "wall_ns"):
        _check(type(record.get(key)) is int and record[key] >= 0, "nonnegative measured physical cost required")
    return {key: record[key] for key in ("cpu_ns", "wall_ns")}


def _group_batches(cases, updates, batch_size, seed):
    _, groups = _groups(cases)
    ordered = [tuple(next(index for world, row, index, *_ in values if world == w and row["answer_id"] == a)
                     for w in ("0", "1") for a in ("0", "1")) for values in groups.values()]
    width = batch_size // 4
    _check(batch_size >= 4 and batch_size % 4 == 0 and len(ordered) % width == 0, "complete group batch geometry required")
    rng, result, offset, order = random.Random(seed), [], len(ordered), []
    for _ in range(updates):
        if offset == len(ordered):
            order = list(range(len(ordered)))
            rng.shuffle(order)
            offset = 0
        result.append([index for group in order[offset:offset + width] for index in ordered[group]])
        offset += width
    return result


def _audit_updates(receipt, streams, cases_by_stream, batches_by_stream):
    positions, nested = Counter(), dict(cpu_ns=0, wall_ns=0)
    for step, (record, stream) in enumerate(zip(receipt["updates"], streams), 1):
        rows = _rows(cases_by_stream[stream])
        position = positions[stream]
        expected_indices = batches_by_stream[stream][position]
        expected_ids = [_id(rows[i]) for i in expected_indices]
        _check(record["step"] == step and record["indices"] == expected_indices and record["case_ids"] == expected_ids
               and record["sample_sha256"] == _digest(expected_ids) and record["exposures"] == len(expected_ids), "executed sampling differs from plan")
        _check(record["inference_feature_arguments"] == 6, "labels/annotations claimed in model arguments")
        for key in ("binary_cross_entropy", "pair_loss", "pair_weight", "total_loss", "parameter_gradient_l2"):
            _check(type(record[key]) in (int, float) and math.isfinite(record[key]) and record[key] >= 0, "nonfinite update evidence")
        _check(math.isclose(record["total_loss"], record["binary_cross_entropy"] + record["pair_weight"] * record["pair_loss"],
                            rel_tol=1e-5, abs_tol=1e-6), "training objective receipt mismatch")
        costs = _cost(record)
        for key in nested:
            nested[key] += costs[key]
        positions[stream] += 1
    _check(len(receipt["updates"]) == len(streams), "missing or extra physical optimizer updates")
    return positions, nested


def _nested_costs(receipt, update_costs):
    nested = dict(update_costs)
    for diagnostic in receipt.get("diagnostics", []):
        for key in ("binding", "natural"):
            if key in diagnostic:
                cost = _cost(diagnostic[key])
                for axis in nested:
                    nested[axis] += cost[axis]
    outer = _cost(receipt)
    _check(all(outer[key] >= nested[key] for key in outer), "fit outer cost below its disjoint measured children")
    return dict(outer=outer, nested_decomposition=nested, total_uses_outer_once=True)


def audit_warmup(receipt, cases, scored_metrics=None):
    rows = _rows(cases)
    planned = _group_batches(rows, receipt["requested_steps"], receipt["batch_size"], receipt["seed"])
    _check(receipt["case_ids"] == [_id(r) for r in rows] and receipt["case_ids_sha256"] == _digest([_id(r) for r in rows])
           and receipt["schedule_sha256"] == _digest(planned), "warmup membership/schedule hash mismatch")
    count = len(receipt["updates"])
    positions, nested = _audit_updates(receipt, ["binding"] * count, {"binding": rows}, {"binding": planned})
    _check(receipt["completed_steps"] == count and receipt["actual_training_exposures"] == count * receipt["batch_size"], "warmup exposure count mismatch")
    diagnostics = receipt["diagnostics"]
    _check(bool(diagnostics), "complete diagnostics required")
    diagnostic_ce = []
    for diagnostic in diagnostics:
        measured = diagnostic["binding"]
        rescored = audit_scores(rows, measured["probabilities"], measured)
        diagnostic_ce.append(dict(optimizer_step=diagnostic["optimizer_step"],
            probability_CE=rescored["probability_CE"], reported_logit_space_CE=measured["binary_cross_entropy"]))
    last = audit_scores(rows, diagnostics[-1]["binding"]["probabilities"], diagnostics[-1]["binding"])
    qualified = _gate(last)
    _check(bool(receipt["train_gate_passed"]) == qualified, "warmup pass flag conflicts with independent scores")
    if qualified:
        _check(diagnostics[-1]["optimizer_step"] == count and receipt["status"] == "train_gate_passed", "qualified checkpoint is not final diagnostic")
    if scored_metrics is not None:
        _check(all(math.isclose(scored_metrics[key], last[key], abs_tol=2e-6, rel_tol=1e-6)
                   for key in ("accuracy", "both_worlds_correct", "probability_CE")), "saved checkpoint panel differs from final training diagnostic")
    _check(set(receipt["training_source_groups"]) == {r["source_hash"] for r in rows}, "warmup training sources mismatch")
    return dict(passed=True, qualified=qualified, independently_recomputed_metrics=last,
                costs=_nested_costs(receipt, nested), model_sha256=receipt["model_sha256"], diagnostic_CE=diagnostic_ce,
                CE_definitions=dict(probability_CE="negative_log_of_saved_FP32_probability_with_1e-12_floor",
                    reported_logit_space_CE="recorded_torch_cross_entropy_from_logits_not_independently_reconstructed",
                    interchangeable=False), qualification_uses_saved_probability_CE=True)


def audit_continuation(receipt, plan, natural_cases, binding_cases, warmup_receipt):
    natural, binding = _rows(natural_cases), _rows(binding_cases)
    _check(plan["plan_sha256"] == _digest({k: v for k, v in plan.items() if k != "plan_sha256"}), "plan digest mismatch")
    _check(receipt["plan_sha256"] == plan["plan_sha256"] and receipt["initial_model_sha256"] == warmup_receipt["model_sha256"], "checkpoint/plan provenance mismatch")
    _check(all(r["source_split"] == "train" for r in natural + binding)
           and not {r["source_hash"] for r in natural} & {r["source_hash"] for r in binding}, "train source role/overlap violation")
    for prefix, rows in (("natural", natural), ("binding", binding)):
        _check(plan[prefix + "_case_ids"] == [_id(r) for r in rows] and plan[prefix + "_targets"] == [r["label"] for r in rows]
               and plan[prefix + "_source_groups"] == [r["source_hash"] for r in rows], "plan row binding mismatch")
    rng = random.Random(f"hepta-binding-natural-v5/{plan['seed']}")
    natural_batches = [rng.sample(range(len(natural)), plan["batch_size"]) for _ in range(plan["updates"])]
    binding_batches = _group_batches(binding, plan["updates"], plan["batch_size"], plan["seed"])
    _check(plan["natural_batches"] == natural_batches and plan["binding_batches"] == binding_batches, "deterministic natural/binding plan mismatch")
    arm = receipt["arm"]
    _check(arm in ("natural_only", "replay", "contrastive"), "unknown continuation arm")
    streams = [stream for _ in range(plan["updates"]) for stream in (("natural",) if arm == "natural_only" else ("natural", "binding"))]
    _check(receipt["status"] == "completed", "continuation did not complete fixed budget")
    positions, nested = _audit_updates(receipt, streams, {"natural": natural, "binding": binding},
                                      {"natural": natural_batches, "binding": binding_batches})
    for record, stream in zip(receipt["updates"], streams):
        _check(record["stream"] == stream and record["logical_step"] == (record["step"] if arm == "natural_only" else (record["step"] + 1) // 2), "logical stream order mismatch")
        _check(record["pair_weight"] == (.5 if arm == "contrastive" and stream == "binding" else 0.), "arm training loss mismatch")
    for stream in ("natural", "binding"):
        _check(receipt["completed_" + stream + "_updates"] == positions[stream]
               and receipt["actual_" + stream + "_exposures"] == positions[stream] * plan["batch_size"], "continuation exposure count mismatch")
    _check(receipt["completed_steps"] == plan["updates"] and receipt["natural_sequence_sha256"] == _digest(natural_batches), "natural budget/sequence mismatch")
    expected_sources = set(warmup_receipt["training_source_groups"]) | {r["source_hash"] for r in natural}
    _check(set(receipt["training_source_groups"]) == expected_sources, "continued model source provenance mismatch")
    for diagnostic in receipt["diagnostics"]:
        audit_scores(binding, diagnostic["binding"]["probabilities"], diagnostic["binding"])
    return dict(passed=True, arm=arm, initial_model_sha256=receipt["initial_model_sha256"],
                natural_sequence_sha256=_digest([[_id(natural[i]) for i in batch] for batch in natural_batches]),
                natural_updates=positions["natural"], binding_updates=positions["binding"], costs=_nested_costs(receipt, nested))


def audit_checkpoint(path, manifest, training_receipt=None, initial_checkpoint=None):
    path = Path(path)
    _check(path.name == manifest["file"] and path.is_file(), "checkpoint file identity mismatch")
    digest = sha256(path.read_bytes()).hexdigest()
    _check(digest == manifest["file_sha256"], "checkpoint byte hash mismatch")
    for key in ("training_parameter_sha256", "execution_parameter_sha256"):
        _check(isinstance(manifest[key], str) and re.fullmatch(r"[0-9a-f]{64}", manifest[key]), "malformed parameter digest")
    _check(type(manifest["frozen_ns"]) is int and manifest["frozen_ns"] > 0, "checkpoint freeze time missing")
    if "training_receipt_file" in manifest or "training_receipt_sha256" in manifest:
        receipt_path = path.parent / manifest["training_receipt_file"]
        _check(receipt_path.name == manifest["training_receipt_file"]
               and sha256(receipt_path.read_bytes()).hexdigest() == manifest["training_receipt_sha256"], "checkpoint training receipt byte hash mismatch")
        bound_receipt = json.loads(receipt_path.read_text())
        if training_receipt is not None:
            _check(_digest(bound_receipt) == _digest(training_receipt), "checkpoint bound receipt differs from audited fit")
        if "model_receipt" in bound_receipt:
            shared_path = path.parent / bound_receipt["shared_training_receipt"]
            _check(sha256(shared_path.read_bytes()).hexdigest() == bound_receipt["shared_receipt_sha256"], "shared revision fit receipt byte hash mismatch")
            shared = json.loads(shared_path.read_text())
            model = bound_receipt["model_receipt"]
            _check(any(_digest(model) == _digest(value) for value in shared["models"].values())
                   and model["training_parameter_sha256"] == manifest["training_parameter_sha256"]
                   and model["execution_parameter_sha256"] == manifest["execution_parameter_sha256"]
                   and model["parameter_count"] == manifest["parameter_count"]
                   and shared["reader_training_source_groups"] == manifest["training_source_groups"], "revision checkpoint/shared fit provenance mismatch")
    if training_receipt is not None:
        _check(manifest["training_parameter_sha256"] == training_receipt["model_sha256"]
               and manifest["training_source_groups"] == training_receipt["training_source_groups"]
               and manifest["parameter_count"] == training_receipt["parameter_count"], "checkpoint/fit provenance mismatch")
    if initial_checkpoint is not None:
        _check(manifest["initial_execution_parameter_sha256"] == initial_checkpoint["execution_parameter_sha256"], "initial execution digest mismatch")
    return dict(passed=True, file_sha256=digest, tensor_digest_independently_reconstructed=False,
                scope="file_bytes_and_record_cross_bindings_only")


def audit_failure_receipt(receipt):
    """Retain measured failed work without manufacturing a qualified checkpoint."""
    _check(receipt.get("status") == "failed" and receipt.get("failed_attempt_time_included") is True
           and bool(receipt.get("error_type")) and isinstance(receipt.get("error"), str), "failed attempt lacks measured failure provenance")
    _check(receipt.get("final_evaluation_authorized", False) is False, "failed fit authorized final evaluation")
    cost, completed_cpu = _cost(receipt), 0
    for update in receipt.get("updates", []):
        if "cpu_ns" in update:
            completed_cpu += _cost(update)["cpu_ns"]
    _check(cost["cpu_ns"] >= completed_cpu, "failed attempt omits completed measured work")
    return dict(passed=True, qualified=False, cost=cost, failed_partial_update_may_be_uncheckpointed=True)


def audit_fresh_gate(warmups, retentions, model_manifests, *, all_models_frozen_ns, fresh_started_ns):
    """Require independently recomputed scores for all three seeds before fresh."""
    _check({item["seed"] for item in warmups} == {41, 47, 53} and len(warmups) == 3
           and {item["seed"] for item in retentions} == {41, 47, 53} and len(retentions) == 3,
           "all three warmup and contrastive retention seeds required")
    for item in warmups:
        _check(_gate(item["metrics"]), "fresh opened before full warmup fitting")
    for item in retentions:
        metrics = item["metrics"]
        baseline = next(value["metrics"] for value in warmups if value["seed"] == item["seed"])
        _check(metrics["cases"] == 128 and metrics["groups"] == 32 and metrics["paired_candidates"] == 64,
               "complete retained training domain required")
        _check(all(metrics[key] + 1e-12 >= .95 and baseline[key] - metrics[key] <= .05 + 1e-12
                   for key in ("accuracy", "both_worlds_correct")), "fresh opened before contrastive retention")
    _check(model_manifests and type(all_models_frozen_ns) is int and type(fresh_started_ns) is int
           and all_models_frozen_ns < fresh_started_ns
           and all(type(model.get("frozen_ns")) is int and 0 < model["frozen_ns"] <= all_models_frozen_ns
                   for model in model_manifests), "fresh evaluation predates model freezing")
    return dict(passed=True, warmup_seeds=3, contrastive_retention_seeds=3, model_freezes=len(model_manifests),
                all_models_frozen_ns=all_models_frozen_ns, fresh_started_ns=fresh_started_ns)


def audit_panel(cases, panel, model_manifest=None):
    rows = _rows(cases)
    _check(panel["case_ids"] == [_id(r) for r in rows], "panel case order mismatch")
    _check(panel.get("labels_entered_model") is False, "panel public model boundary not recorded")
    metrics = audit_scores(rows, panel["probabilities"], panel["metrics"])
    batches = panel["batches"]
    _check(len({batch["batch_id"] for batch in batches}) == len(batches)
           and [case_id for batch in batches for case_id in batch["case_ids"]] == panel["case_ids"], "duplicate/missing physical batch receipt")
    total = dict(cpu_ns=0, wall_ns=0)
    for batch in batches:
        _check(batch["steps"] == panel["depth"] and batch["proposal_steps"] == len(batch["case_ids"]) * panel["depth"], "physical proposal count mismatch")
        cost = _cost(batch)
        for key in total:
            total[key] += cost[key]
    if model_manifest is not None:
        _check(panel["model_execution_parameter_sha256"] == model_manifest["execution_parameter_sha256"], "panel model digest mismatch")
    return dict(passed=True, metrics=metrics, physical_batches=len(batches), costs=total,
                nested_work_observation_not_added=True, tensor_inputs_independently_executed=False)


def audit_natural_panel(cases, panel, model_manifest=None):
    """Rescore the old official-training internal cohort, never official val."""
    rows, probabilities = _rows(cases), panel["probabilities"]
    ids = [_id(row) for row in rows]
    _check(rows and len(set(ids)) == len(ids) and panel["case_ids"] == ids
           and all(row["source_split"] == "train" for row in rows), "natural internal train-source membership mismatch")
    _check(len(probabilities) == len(rows) and all(type(p) in (int, float) and math.isfinite(p) and 0 <= p <= 1
                                                 for p in probabilities), "natural probabilities incomplete/nonfinite")
    _check(panel.get("threshold_selected") is False and panel.get("scope") == "old_training_source_internal_tune_not_fresh",
           "natural internal scope or decision rule changed")
    predictions = [int(p > .5) for p in probabilities]
    groups = defaultdict(list)
    for row, prediction in zip(rows, predictions):
        _check(type(row["label"]) is int and row["label"] in (0, 1), "natural binary reference required")
        groups[tuple(row[k] for k in ("source_split", "paragraph_id", "question_id"))].append((row["label"], prediction))

    def f1(values, positive):
        denominator = sum(gold == positive for gold, _ in values) + sum(pred == positive for _, pred in values)
        return 2 * sum(gold == pred == positive for gold, pred in values) / denominator if denominator else 0.

    values = [(row["label"], pred) for row, pred in zip(rows, predictions)]
    macro = [sum(f1(value, label) for label in {v for pair in value for v in pair}) /
             len({v for pair in value for v in pair}) for value in groups.values()]
    metrics = dict(candidates=len(rows), questions=len(groups),
        paragraphs=len({(row["source_split"], row["paragraph_id"]) for row in rows}), f1_a=f1(values, 1),
        exact_match=sum(all(gold == pred for gold, pred in value) for value in groups.values()) / len(groups),
        f1_m=sum(macro) / len(macro), accuracy=sum(gold == pred for gold, pred in values) / len(values))
    for key, expected in metrics.items():
        _check(type(panel["metrics"][key]) in (int, float)
               and math.isclose(panel["metrics"][key], expected, abs_tol=1e-9, rel_tol=1e-9), "natural metric mismatch: " + key)
    batches = panel["batches"]
    _check(len({batch["batch_id"] for batch in batches}) == len(batches)
           and [case_id for batch in batches for case_id in batch["case_ids"]] == ids, "natural physical batches duplicated/incomplete")
    costs = dict(cpu_ns=0, wall_ns=0)
    for batch in batches:
        _check(batch["steps"] == 3 and batch["proposal_steps"] == 3 * len(batch["case_ids"]), "natural physical proposal count mismatch")
        cost = _cost(batch)
        for key in costs:
            costs[key] += cost[key]
    if model_manifest is not None:
        _check(panel["model_execution_parameter_sha256"] == model_manifest["execution_parameter_sha256"], "natural panel model digest mismatch")
    return dict(passed=True, metrics=metrics, physical_batches=len(batches), costs=costs,
                scope="old_official_training_source_internal_cohort_not_fresh", nested_meter_costs_not_added=True)


def audit_source_inventory(code_dir, declared):
    _check(bool(declared), "nonempty runtime source inventory required")
    for name, expected in declared.items():
        path = Path(code_dir) / name
        _check(Path(name).name == name and sha256(path.read_bytes()).hexdigest() == expected, "runtime source bytes mismatch: " + name)
    return dict(passed=True, files=len(declared), inventory_sha256=_digest(declared))


def review_bundle(bundle, base_dir):
    """Review an explicit index of references; paths are relative to base_dir.

    Required: cases, design, code_dir. Optional arrays: warmups (receipt/model/
    panel), continuations (receipt/plan/natural_cases/warmup_receipt/model/
    initial_model), panels (role/panel/model). A model reference points to its
    *-model.json; its sibling .pt is hash checked. No implicit glob is scored.
    """
    base = Path(base_dir)

    def read(reference):
        return json.loads((base / reference).read_text())

    def checkpoint(reference, receipt=None, initial=None):
        record = read(reference)
        return audit_checkpoint((base / reference).parent / record["file"], record, receipt, initial)

    parts, design = read(bundle["cases"]), read(bundle["design"])
    result = dict(protocol=audit_protocol(parts, design["membership"]),
                  sources=audit_source_inventory(bundle["code_dir"], design["runtime_source_sha256"]),
                  warmups=[], continuations=[], panels=[], natural_panels=[], models=[])
    outer_total, inference_total, panel_paths, receipt_paths = 0, 0, set(), set()
    for entry in bundle.get("warmups", []):
        receipt_path = str((base / entry["receipt"]).resolve())
        _check(receipt_path not in receipt_paths, "repeated fit outer cost")
        receipt_paths.add(receipt_path)
        receipt, panel = read(entry["receipt"]), read(entry["panel"])
        metrics = audit_scores(parts["reader_train"], panel["probabilities"], panel["metrics"])
        result["warmups"].append(audit_warmup(receipt, parts["reader_train"], metrics))
        checkpoint(entry["model"], receipt)
        outer_total += receipt["cpu_ns"]
    natural_sequences = defaultdict(set)
    for entry in bundle.get("continuations", []):
        receipt_path = str((base / entry["receipt"]).resolve())
        _check(receipt_path not in receipt_paths, "repeated fit outer cost")
        receipt_paths.add(receipt_path)
        receipt, plan = read(entry["receipt"]), read(entry["plan"])
        check = audit_continuation(receipt, plan, read(entry["natural_cases"]), parts["reader_train"], read(entry["warmup_receipt"]))
        result["continuations"].append(check)
        checkpoint(entry["model"], receipt, read(entry["initial_model"]))
        natural_sequences[plan["seed"]].add(check["natural_sequence_sha256"])
        outer_total += receipt["cpu_ns"]
    _check(all(len(values) == 1 for values in natural_sequences.values()), "cross-arm natural sample sequence differs")
    for entry in bundle.get("panels", []):
        panel_path = str((base / entry["panel"]).resolve())
        _check(panel_path not in panel_paths and entry["role"] != "verifier_fit", "repeated physical panel or unused verifier evaluation")
        panel_paths.add(panel_path)
        report = audit_panel(parts[entry["role"]], read(entry["panel"]), read(entry["model"]))
        result["panels"].append(report)
        inference_total += report["costs"]["cpu_ns"]
    for entry in bundle.get("natural_panels", []):
        panel_path = str((base / entry["panel"]).resolve())
        _check(panel_path not in panel_paths, "repeated natural physical panel")
        panel_paths.add(panel_path)
        cases = read(entry["cases"])
        if isinstance(cases, dict):
            cases = cases[entry.get("case_role", "tune")]
        _check([_id(row) for row in _rows(cases)] == design["natural_case_ids"][entry.get("case_role", "tune")],
               "natural panel differs from frozen design row identities")
        report = audit_natural_panel(cases, read(entry["panel"]), read(entry["model"]))
        result["natural_panels"].append(report)
        inference_total += report["costs"]["cpu_ns"]
    for reference in bundle.get("models", []):
        result["models"].append(checkpoint(reference))
    fresh_panels = any(entry["role"].startswith("fresh_") for entry in bundle.get("panels", []))
    if fresh_panels:
        _check("fresh_boundary" in bundle, "fresh panel audit requires explicit freeze/qualification boundary")
        boundary = bundle["fresh_boundary"]
        scored = {}
        for role in ("warmups", "retentions"):
            scored[role] = [dict(seed=item["seed"], metrics=audit_scores(parts["reader_train"],
                read(item["panel"])["probabilities"], read(item["panel"])["metrics"])) for item in boundary[role]]
        result["fresh_boundary"] = audit_fresh_gate(scored["warmups"], scored["retentions"],
            [read(reference) for reference in boundary["models"]],
            all_models_frozen_ns=boundary["all_models_frozen_ns"], fresh_started_ns=boundary["fresh_started_ns"])
    result.update(passed=True, fit_outer_cpu_ns_once=outer_total, panel_physical_cpu_ns_once=inference_total,
                  costs_are_scoped_not_complete_lifecycle=True, independent_neural_execution=False,
                  coverage="explicit_index_entries_only")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = review_bundle(json.loads(args.index.read_text()), args.index.parent)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
