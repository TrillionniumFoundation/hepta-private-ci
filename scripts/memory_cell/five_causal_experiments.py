"""Five causal experiments: sealed cohorts, blind execution and paired readout.

No task generator, implicit model download, synthetic default or promotion path.
Existing model/Cell/System2 implementations are invoked through reviewed local
executors. This module does not implement or certify those algorithms. A fixture
executor can test the transport, never supply natural-task evidence.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import subprocess
import sys
import time
from typing import Any

ARMS = {
    "reader": ("no_evidence", "ordinary_retrieval", "human_sufficient", "critical_premise_removed"),
    "sharing": ("replicated_full", "shared_frozen_head", "shared_trained_head"),
    "system2": ("stateless", "independent_attempts", "fixed_search", "learned_recurrent"),
    "ndu": ("fixed_budget", "threshold_rule", "shuffled_utility", "ndu_allocation"),
    "multimodal": ("text_only", "joint_unsplit", "wrong_pair", "time_shuffle", "missing_modality", "offline_split", "fixed_split"),
}
CONTRASTS = {
    "reader": (("human_sufficient", "ordinary_retrieval"),),
    "sharing": (("shared_trained_head", "shared_frozen_head"), ("shared_trained_head", "replicated_full")),
    "system2": tuple(("learned_recurrent", a) for a in ARMS["system2"][:-1]),
    "ndu": tuple(("ndu_allocation", a) for a in ARMS["ndu"][:-1]),
    "multimodal": (("joint_unsplit", "text_only"), ("joint_unsplit", "wrong_pair"),
                   ("joint_unsplit", "time_shuffle"), ("joint_unsplit", "missing_modality"),
                   ("offline_split", "joint_unsplit"), ("offline_split", "fixed_split")),
}
PROTOCOL = {
    "schema": "hepta.five-causal.protocol.v1",
    "arms": ARMS, "contrasts": CONTRASTS,
    "family_weighting": "equal_family_then_equal_task",
    "alpha": 0.05, "bootstrap_replicates": 10000, "bootstrap_seed": 20261013,
    "minimum_confirmation_families": 8,
    "multiple_testing": "bonferroni_over_all_15_preregistered_contrasts",
    "failed_or_unexecuted_score": 0.0,
    "ordinary_equal_sufficient": "reader_can_qualify_retrieval_headroom_not_established",
    "cost_policy": "observed_cost_frontier_no_imputed_zero_no_nominal_flops",
    "confirmation_policy": "all_arms_checkpoint_frozen_before_external_cohort_release",
    "runtime_parameter_updates": False, "production_authority": False,
}
BINDINGS = ("reader", "tokenizer", "prompt", "decoder", "encoder", "preprocessor", "action_menu", "verifier")
SPLITS = ("train", "validation", "confirmation", "retention")
SHA = re.compile(r"[0-9a-f]{64}\Z")
ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")
MAX_TRIALS = 100000
MAX_FILE_BYTES = 64 * 1024 * 1024
RESOURCE_KEYS = ("active_flops", "energy_joules", "peak_memory_bytes", "model_calls")


class Invalid(ValueError):
    """Invalid or unsupported evidence; never interpreted as a zero score."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise Invalid(reason)


def sha(value: Any) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def finite(value: Any, lower: float = 0, upper: float = math.inf) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def text_id(value: Any) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def load(path: Path) -> Any:
    require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, "missing/oversized JSON")
    def pairs(rows):
        out = {}
        for k, v in rows:
            require(k not in out, "duplicate JSON key")
            out[k] = v
        return out
    try:
        return json.loads(path.read_text(), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite JSON")))
    except (ValueError, UnicodeError) as e:
        raise Invalid("invalid JSON: " + str(e)) from e


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as f:
        f.write(canonical(value) + b"\n")
        f.flush()
        os.fsync(f.fileno())


def instant(value: str) -> datetime:
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(t.tzinfo is not None, "timezone required")
        return t
    except (AttributeError, ValueError) as e:
        raise Invalid("invalid timestamp") from e


def pinned(review: dict, expected: str | None, scope: str, now: datetime | None = None) -> None:
    """A pin MUST come from an independently authorized owner, not this bundle.

    This validates byte binding and declared identity/time scope, not the human
    truth of the review, independence or calibration of device counters.
    """
    require(isinstance(review, dict) and sha(expected) and digest(review) == expected, "external trust pin missing/mismatched")
    require(review.get("schema") == "hepta.five-causal.review.v1" and review.get("scope") == scope, "wrong review scope")
    require(text_id(review.get("owner")) and text_id(review.get("experimenter"))
            and review["owner"] != review["experimenter"] and review.get("revoked") is False, "review identity/revocation invalid")
    now = now or datetime.now(timezone.utc)
    require(instant(review["valid_from"]) <= now < instant(review["valid_until"]), "review expired/not yet valid")


def validate_public(request: dict) -> None:
    # Explicit allowlist, including evidence: no arm names, kind=reviewed,
    # source-sufficiency annotations, gold answers or evaluator inputs.
    require(isinstance(request, dict) and set(request) == {"question", "options", "evidence"}, "public input keys invalid")
    require(isinstance(request["question"], str) and 0 < len(request["question"]) <= 65536, "question invalid")
    require(isinstance(request["options"], list) and len(request["options"]) <= 128
            and all(isinstance(x, str) for x in request["options"]), "options invalid")
    require(isinstance(request["evidence"], list) and len(request["evidence"]) <= 256, "evidence invalid")
    seen = set()
    for e in request["evidence"]:
        require(isinstance(e, dict) and set(e) == {"id", "modality", "text", "asset_sha256", "position"}, "evidence keys invalid")
        require(text_id(e["id"]) and e["id"] not in seen, "evidence identity invalid")
        seen.add(e["id"])
        require(e["modality"] in ("text", "image", "audio", "video"), "modality invalid")
        require(isinstance(e["text"], str) and len(e["text"]) <= 131072, "evidence text invalid")
        require(type(e["position"]) is int and e["position"] >= 0, "position invalid")
        require((e["modality"] == "text" and e["asset_sha256"] is None)
                or (e["modality"] != "text" and sha(e["asset_sha256"])), "media content binding missing")


def validate_bundle(b: dict) -> dict[str, dict]:
    require(isinstance(b, dict) and b.get("schema") == "hepta.five-causal.bundle.v1", "unknown bundle")
    require(b.get("protocol_sha256") == digest(PROTOCOL), "protocol changed/unregistered")
    require(b.get("data_kind") == "natural_unseen", "not a natural unseen cohort")
    require(isinstance(b.get("cohort"), list) and b["cohort"], "cohort missing")
    tasks = {}
    ownership = {name: {} for name in ("source_roots", "exposure_groups", "content_sha256")}
    family_splits = defaultdict(set)
    independent_roots = {}
    for t in b["cohort"]:
        require(isinstance(t, dict) and text_id(t.get("id")) and t["id"] not in tasks, "duplicate/invalid task")
        require(t.get("split") in SPLITS and text_id(t.get("family")), "task split/family missing")
        require(sha(t.get("content_sha256")), "content hash missing")
        for field in ("source_roots", "exposure_groups"):
            require(isinstance(t.get(field), list) and t[field]
                    and all(text_id(x) for x in t[field]), "source/exposure roots missing")
        for field, index in ownership.items():
            values = [t[field]] if field == "content_sha256" else t[field]
            for value in values:
                require(value not in index or index[value] == t["split"], "cross-split leakage: " + field)
                index[value] = t["split"]
                if t["split"] == "confirmation":
                    root_key = (field, value)
                    require(root_key not in independent_roots or independent_roots[root_key] == t["family"], "one source/template cannot become multiple independent families")
                    independent_roots[root_key] = t["family"]
        family_splits[t["family"]].add(t["split"])
        tasks[t["id"]] = t
    # Retention deliberately reuses old task families, never the same source
    # roots/content. Confirmation families must be genuinely held out.
    require(all("confirmation" not in s or len(s) == 1 for s in family_splits.values()), "confirmation task-family leakage")
    require(isinstance(b.get("trials"), list) and 0 < len(b["trials"]) <= MAX_TRIALS, "trial census invalid")
    keys, trial_ids, groups = set(), set(), defaultdict(set)
    bindings, implementations = {}, {}
    for r in b["trials"]:
        require(isinstance(r, dict), "trial must be an object")
        e, a, tid = r.get("experiment"), r.get("arm"), r.get("task_id")
        require(e in ARMS and a in ARMS[e] and tid in tasks, "unknown experiment/arm/task")
        require(tasks[tid]["split"] in ("confirmation", "retention"), "only frozen evaluation tasks are executable")
        require(text_id(r.get("trial_id")) and r["trial_id"] not in trial_ids, "duplicate trial id")
        key = (e, a, tid)
        require(key not in keys, "duplicate arm-task row")
        keys.add(key); trial_ids.add(r["trial_id"]); groups[(e, tid)].add(a)
        validate_public(r["request"])
        binding = r.get("bindings")
        require(isinstance(binding, dict) and set(binding) == set(BINDINGS)
                and all(sha(v) for v in binding.values()), "incomplete model/menu/verifier binding")
        require(e not in bindings or binding == bindings[e], "within-experiment model/menu/verifier drift")
        bindings[e] = binding
        require(sha(r.get("implementation_sha256")) and sha(r.get("checkpoint_sha256")), "implementation/checkpoint identity missing")
        pair = (r["implementation_sha256"], r["checkpoint_sha256"])
        require((e, a) not in implementations or implementations[(e, a)] == pair, "evaluation-time model update")
        implementations[(e, a)] = pair
        require(finite(r.get("timeout_seconds"), 0.01, 3600), "invalid deadline")
    require(all(arms == set(ARMS[e]) for (e, _), arms in groups.items()), "unpaired/missing arms")
    for e in {e for e, _ in groups}:
        for split in ("confirmation", "retention"):
            require(any(exp == e and tasks[tid]["split"] == split for exp, tid in groups), "confirmation/retention census missing")
    validate_controls(b)
    return tasks



def validate_controls(b: dict) -> None:
    """Verify actual controlled input edits, not treatment names alone."""
    rows = {(r["experiment"], r["task_id"], r["arm"]): r for r in b["trials"]}
    groups = {(e, tid) for e, tid, _ in rows}
    annotations = b.get("control_annotations")
    require(isinstance(annotations, dict), "independently sealed control annotations missing")
    for e, tid in groups:
        requests = {a: rows[(e, tid, a)]["request"] for a in ARMS[e]}
        # Prompts/options are invariant; only the registered evidence/control
        # or frozen implementation may differ.
        first = next(iter(requests.values()))
        require(all(r["question"] == first["question"] and r["options"] == first["options"]
                    for r in requests.values()), "question/options changed between arms")
        if e in ("sharing", "system2", "ndu"):
            require(all(r == first for r in requests.values()), "non-model input confounding")
        if e == "reader":
            require(len({(rows[(e, tid, a)]["implementation_sha256"], rows[(e, tid, a)]["checkpoint_sha256"]) for a in ARMS[e]}) == 1, "Reader implementation changed between evidence arms")
            require(not requests["no_evidence"]["evidence"], "no-evidence arm contains evidence")
            sufficient = requests["human_sufficient"]["evidence"]
            ann = annotations.get(tid, {})
            critical = ann.get("critical_evidence_ids")
            require(isinstance(critical, list) and critical and all(text_id(x) for x in critical)
                    and len(set(critical)) == len(critical), "critical premise group missing")
            require(set(critical) <= {x["id"] for x in sufficient}, "critical premise not in sufficient evidence")
            remaining = [x for x in sufficient if x["id"] not in critical]
            require(requests["critical_premise_removed"]["evidence"] == remaining, "critical premise not exactly removed")
        if e == "multimodal":
            base = requests["joint_unsplit"]["evidence"]
            media = [x for x in base if x["modality"] != "text"]
            texts = [x for x in base if x["modality"] == "text"]
            require(media and texts, "actual text and media inputs required")
            require(requests["text_only"]["evidence"] == texts, "text-only control invalid")
            require(requests["offline_split"] == requests["joint_unsplit"]
                    and requests["fixed_split"] == requests["joint_unsplit"], "split changes evidence instead of model")
            ann = annotations.get(tid, {})
            missing = ann.get("missing_modality")
            require(missing in {x["modality"] for x in media}, "missing-modality intervention undefined")
            require(requests["missing_modality"]["evidence"] == [x for x in base if x["modality"] != missing], "modality not exactly removed")
            shuffled = requests["time_shuffle"]["evidence"]
            require(any(x["modality"] in ("audio", "video") for x in media), "time-control requires temporal media")
            def strip(x):
                return {k: v for k, v in x.items() if k != "position"}
            require([x for x in shuffled if x["modality"] in ("text", "image")] == [x for x in base if x["modality"] in ("text", "image")], "time shuffle changed static evidence")
            require(sorted(digest(strip(x)) for x in shuffled) == sorted(digest(strip(x)) for x in base)
                    and sorted(x["position"] for x in shuffled) == sorted(x["position"] for x in base)
                    and {x["id"]: x["position"] for x in shuffled} != {x["id"]: x["position"] for x in base}, "time shuffle is not a genuine position permutation")
            donor = ann.get("wrong_pair_donor")
            donor_row = rows.get((e, donor, "joint_unsplit")) if text_id(donor) and donor != tid else None
            require(donor_row is not None, "wrong-pair donor missing/unregistered")
            splits = {t["id"]: t["split"] for t in b["cohort"]}
            require(splits[donor] == splits[tid], "wrong-pair donor crosses evaluation partitions")
            donor_media = [x for x in donor_row["request"]["evidence"] if x["modality"] != "text"]
            wrong = requests["wrong_pair"]["evidence"]
            require([x for x in wrong if x["modality"] == "text"] == texts
                    and [x for x in wrong if x["modality"] != "text"] == donor_media
                    and {x["asset_sha256"] for x in donor_media} != {x["asset_sha256"] for x in media}, "wrong-pair control not an actual donor-media substitution")
    if any(e == "multimodal" for e, _ in groups):
        capacity = b.get("split_parameter_counts")
        require(isinstance(capacity, dict) and set(capacity) == {"joint_unsplit", "offline_split", "fixed_split"}
                and all(type(n) is int and n > 0 for n in capacity.values())
                and len(set(capacity.values())) == 1, "split controls lack same total parameter capacity")
    # Counts are an independently reviewed manifest, not introspection of a
    # native checkpoint. Actual parameter/storage measurements still required.
    budgets = b.get("budget_caps")
    require(isinstance(budgets, dict) and set(budgets) == set(ARMS), "budget profiles missing")
    for e, budget in budgets.items():
        require(isinstance(budget, dict) and set(budget) == {"wall_seconds", "active_flops", "energy_joules", "model_calls"}
                and all(finite(v, .000001) for v in budget.values()), "invalid resource budget")
        require(all(r["timeout_seconds"] == budget["wall_seconds"] for r in b["trials"] if r["experiment"] == e), "unequal arm deadline budget")


def validate_freeze(b: dict, review: dict, pin: str | None) -> None:
    pinned(review, pin, "preregistration")
    require(review.get("bundle_sha256") == digest(b), "review does not bind complete bundle")
    require(review.get("grouping_review") == "independent_source_and_task_family_reviewed"
            and review.get("prior_exposure_review") == "not_used_in_development", "unseen/grouping review unavailable")
    require(sha(review.get("exposure_audit_sha256")), "exposure audit identity missing")
    require(instant(review["checkpoints_frozen_at"]) < instant(review["cohort_released_at"])
            <= instant(review["valid_from"]), "checkpoint/cohort freeze chronology invalid")


def source_file(root: Path, relative: str, expected: str) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), "relative asset path required")
    p = root / relative
    require(".." not in Path(relative).parts and not any(x.is_symlink() for x in [p, *p.parents]), "symlink/traversal denied")
    require(p.is_file() and sha(expected) and file_sha(p) == expected, "asset missing/hash mismatch: " + relative)
    return p.resolve()


def check_materials(b: dict, root: Path, experiment: str | None = None) -> None:
    files = b.get("files")
    executors = b.get("executors")
    require(isinstance(files, dict) and files, "actual model/media/checkpoint files not supplied")
    require(isinstance(executors, dict), "native executor inventory not supplied")
    needed = set()
    for r in b["trials"]:
        if experiment is not None and r["experiment"] != experiment:
            continue
        needed.add(r["checkpoint_sha256"])
        needed.update(e["asset_sha256"] for e in r["request"]["evidence"] if e["asset_sha256"] is not None)
        x = executors.get(r["implementation_sha256"])
        require(isinstance(x, dict) and x.get("kind") == "real_model", "real native executor unavailable")
        require(x.get("sha256") == r["implementation_sha256"], "executor identity mismatch")
        source_file(root, x["path"], x["sha256"])
        require(r["checkpoint_sha256"] in files.values(), "selected checkpoint bytes unavailable")
        require(all(e["asset_sha256"] is None or e["asset_sha256"] in files.values()
                    for e in r["request"]["evidence"]), "modality bytes unavailable")
    for value in needed:
        matches = [name for name, expected in files.items() if expected == value]
        require(len(matches) == 1, "missing/ambiguous material content mapping")
        source_file(root, matches[0], value)


def plan() -> dict:
    return {"protocol": PROTOCOL, "protocol_sha256": digest(PROTOCOL),
            "total_arms": sum(map(len, ARMS.values())),
            "experiments": [{"experiment": e, "arms": a, "status": "not_executed",
                             "missing": ["externally_released_natural_cohort", "frozen_native_checkpoints",
                                         "independent_preregistration_pin", "actual_execution_and_adjudication"]}
                            for e, a in ARMS.items()],
            "production_authority": False, "model_efficacy_established": False}


def journal_append(stream, row: dict, previous: str) -> str:
    entry = {"previous_sha256": previous, "record": row}
    stream.write(canonical(entry) + b"\n")
    stream.flush(); os.fsync(stream.fileno())
    return digest(entry)


def validate_result(result: dict, expected_request: str) -> None:
    require(isinstance(result, dict) and set(result) == {"request_sha256", "answer", "resources"}, "invalid executor response")
    require(result["request_sha256"] == expected_request and isinstance(result["answer"], str), "response/input identity mismatch")
    costs = result["resources"]
    require(isinstance(costs, dict) and set(costs) == set(RESOURCE_KEYS), "resource fields missing")
    require(all(v is None or finite(v) for v in costs.values()), "invalid resource measurement")


def execute(b: dict, review: dict, pin: str, root: Path, output: Path,
            experiment: str, reader_review: dict | None = None, reader_pin: str | None = None) -> dict:
    validate_bundle(b); validate_freeze(b, review, pin); check_materials(b, root, experiment)
    require(experiment in ARMS, "unknown experiment")
    if experiment != "reader":
        pinned(reader_review, reader_pin, "reader_admission")
        require(reader_review.get("bundle_sha256") == digest(b)
                and reader_review.get("disposition") == "qualified_for_registered_capabilities"
                and experiment in reader_review.get("experiments", []), "independent Reader admission missing")
        require(all(sha(reader_review.get(k)) for k in ("reader_raw_sha256", "judgments_sha256", "gate_receipt_sha256")), "Reader review lineage missing")
        from full_cell_matrix import evaluate_reader_gate
        receipt = reader_review.get("gate_receipt")
        trust = reader_review.get("gate_trust_manifest")
        require(isinstance(receipt, dict) and digest(receipt) == reader_review["gate_receipt_sha256"], "Reader gate bytes missing/mismatched")
        decision = evaluate_reader_gate(
            receipt, trust, trusted_review_sha256=reader_review.get("gate_trust_sha256"),
            reviewer_roster=reader_review.get("reviewer_roster"),
            trusted_roster_sha256=os.environ.get("HEPTA_REVIEWER_ROSTER_SHA256"),
        )
        require(decision.passed, "Reader adequacy gate denied: " + decision.reason)
        stage = [r for r in b["trials"] if r["experiment"] == experiment]
        require(stage and set(receipt["cohort"]) == {r["task_id"] for r in stage}, "Reader qualification cohort does not cover this stage")
        require(receipt["model_binding"].get("five_causal_bindings_sha256") == digest(stage[0]["bindings"]), "Reader/model/menu binding differs from qualified stage")
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "frozen-bundle.json", b)
    rows = [r for r in b["trials"] if r["experiment"] == experiment]
    # Counterbalance by a predeclared digest; do not let evaluation labels
    # choose arm order. The permutation is part of the original bundle seal.
    rows.sort(key=lambda r: digest({"seed": PROTOCOL["bootstrap_seed"], "trial": r["trial_id"]}))
    previous = "0" * 64
    with (output / "raw-journal.jsonl").open("xb") as f:
        for i, r in enumerate(rows):
            packet = {"request": r["request"], "checkpoint_sha256": r["checkpoint_sha256"],
                      "bindings": r["bindings"], "timeout_seconds": r["timeout_seconds"]}
            req = digest(packet)
            previous = journal_append(f, {"event": "started", "trial_id": r["trial_id"], "request_sha256": req}, previous)
            executor = b["executors"][r["implementation_sha256"]]
            script = source_file(root, executor["path"], executor["sha256"])
            started = time.perf_counter()
            record = {"event": "finished", "trial_id": r["trial_id"], "request_sha256": req,
                      "status": "failed", "result": None}
            # Raw outputs remain in private files. subprocess transport is not
            # a security sandbox; production hosts must mount only public data.
            with (output / f"stdout-{i}.json").open("xb") as out, (output / f"stderr-{i}.txt").open("xb") as err:
                child = subprocess.Popen([sys.executable, str(script)], cwd=root,
                                         stdin=subprocess.PIPE, stdout=out, stderr=err,
                                         start_new_session=True, env={**os.environ, "HEPTA_MODEL_NETWORK": "disabled"})
                try:
                    child.communicate(canonical(packet) + b"\n", timeout=r["timeout_seconds"])
                    require(child.returncode == 0, "executor failed; inspect private stderr")
                    result = load(output / f"stdout-{i}.json")
                    validate_result(result, req)
                    record.update(status="succeeded", result=result)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL); child.communicate()
                    record["status"] = "timeout"
                except (Invalid, OSError) as error:
                    record["error"] = str(error)[:1024]
            record["wall_seconds_including_process_start"] = time.perf_counter() - started
            previous = journal_append(f, record, previous)
    check_materials(b, root, experiment)
    receipt = {"schema": "hepta.five-causal.execution.v1", "bundle_sha256": digest(b),
               "experiment": experiment, "planned": len(rows), "journal_tail_sha256": previous,
               "raw_sha256": file_sha(output / "raw-journal.jsonl"),
               "model_efficacy_established": False, "production_authority": False}
    write_new(output / "execution-receipt.json", receipt)
    return receipt


def read_journal(path: Path) -> dict[str, dict]:
    previous = "0" * 64
    started, finished = {}, {}
    require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, "raw journal missing/oversized")
    for line in path.read_bytes().splitlines():
        entry = json.loads(line)
        require(entry.get("previous_sha256") == previous, "journal chain mismatch")
        previous = digest(entry)
        r = entry["record"]; tid = r.get("trial_id")
        require(text_id(tid) and sha(r.get("request_sha256")), "journal record invalid")
        if r.get("event") == "started":
            require(tid not in started, "duplicate execution attempt")
            started[tid] = r["request_sha256"]
        elif r.get("event") == "finished":
            require(tid in started and tid not in finished and started[tid] == r["request_sha256"], "unmatched execution result")
            require(r.get("status") in ("succeeded", "failed", "timeout") and finite(r.get("wall_seconds_including_process_start")), "invalid execution status/cost")
            if r["status"] == "succeeded":
                validate_result(r["result"], r["request_sha256"])
            finished[tid] = r
        else:
            raise Invalid("unknown journal event")
    # No new run is silently issued for an interrupted attempt.
    for tid in started.keys() - finished.keys():
        finished[tid] = {"trial_id": tid, "request_sha256": started[tid], "status": "unknown_interrupted", "result": None}
    return finished


def mean(xs: list[float]) -> float:
    return math.fsum(xs) / len(xs)


def cluster_interval(family_deltas: list[float]) -> tuple[float, float] | None:
    if len(family_deltas) < PROTOCOL["minimum_confirmation_families"]:
        return None
    rng = random.Random(PROTOCOL["bootstrap_seed"])
    n = len(family_deltas)
    samples = sorted(mean([family_deltas[rng.randrange(n)] for _ in range(n)])
                     for _ in range(PROTOCOL["bootstrap_replicates"]))
    comparisons = sum(map(len, CONTRASTS.values()))
    tail = PROTOCOL["alpha"] / (2 * comparisons)
    return samples[int(tail * len(samples))], samples[min(len(samples)-1, math.ceil((1-tail)*len(samples))-1)]


def analyze(b: dict, journal: Path, judgments: dict, review: dict, pin: str) -> dict:
    tasks = validate_bundle(b)
    pinned(review, pin, "outcome_adjudication")
    require(review.get("bundle_sha256") == digest(b) and review.get("raw_sha256") == file_sha(journal)
            and review.get("judgments_sha256") == digest(judgments), "adjudication not bound to actual raw outputs")
    experiment = review.get("experiment")
    require(experiment in ARMS and review.get("execution_kind") == "real_model", "not a reviewed real-model experiment")
    raw = read_journal(journal)
    planned = {r["trial_id"]: r for r in b["trials"] if r["experiment"] == experiment}
    require(set(raw) <= set(planned), "unregistered raw trial")
    require(isinstance(judgments, dict) and set(judgments) <= set(planned), "unregistered judgments")
    scored = {}
    for tid, r in planned.items():
        rr = raw.get(tid, {"status": "not_executed", "result": None})
        packet = {"request": r["request"], "checkpoint_sha256": r["checkpoint_sha256"],
                  "bindings": r["bindings"], "timeout_seconds": r["timeout_seconds"]}
        if tid in raw:
            require(raw[tid]["request_sha256"] == digest(packet), "raw output belongs to different public inputs")
        j = judgments.get(tid)
        if j is not None:
            require(rr["status"] == "succeeded", "judgment for non-successful model call")
            require(set(j) == {"score", "grounded_and_cited", "exact_refusal", "unsupported_claim"}
                    and finite(j["score"], 0, 1)
                    and all(type(j[k]) is bool for k in j if k != "score"), "invalid independent judgment")
        scored[tid] = {"task_id": r["task_id"], "arm": r["arm"],
                       "split": tasks[r["task_id"]]["split"], "family": tasks[r["task_id"]]["family"],
                       "score": j["score"] if j is not None else 0.0,
                       "judgment_available": j is not None, "status": rr["status"],
                       "resources": rr["result"]["resources"] if rr.get("result") is not None else None}
    look = {(r["task_id"], r["arm"]): r for r in scored.values()}
    complete = all(r["status"] == "succeeded" and r["judgment_available"] for r in scored.values())
    costs_complete = complete and all(r["resources"] is not None and all(v is not None for v in r["resources"].values()) for r in scored.values())
    contrasts = []
    for candidate, baseline in CONTRASTS[experiment]:
        split_results = {}
        for split in ("confirmation", "retention"):
            fam = defaultdict(list)
            for r in scored.values():
                if r["arm"] == candidate and r["split"] == split:
                    fam[r["family"]].append(r["score"] - look[(r["task_id"], baseline)]["score"])
            deltas = [mean(fam[k]) for k in sorted(fam)]
            interval = cluster_interval(deltas)
            split_results[split] = {"families": len(fam), "paired_tasks": sum(map(len, fam.values())),
                                    "family_macro_delta": mean(deltas), "simultaneous_bootstrap_interval": interval,
                                    "worst_family_delta": min(deltas),
                                    "positive_interval": bool(complete and interval is not None and interval[0] > 0)}
        contrasts.append({"candidate": candidate, "baseline": baseline, **split_results})
    arms = {}
    for arm in ARMS[experiment]:
        vals = [r for r in scored.values() if r["arm"] == arm]
        arms[arm] = {"planned": len(vals), "successful_calls": sum(r["status"] == "succeeded" for r in vals),
                     "independent_judgments": sum(r["judgment_available"] for r in vals),
                     "failure_inclusive_task_mean": mean([r["score"] for r in vals]),
                     "resources": {key: (sum(r["resources"][key] for r in vals)
                                           if key != "peak_memory_bytes" else max(r["resources"][key] for r in vals))
                                   if all(r["resources"] is not None and r["resources"][key] is not None for r in vals) else None
                                   for key in RESOURCE_KEYS}}
    return {"schema": "hepta.five-causal.analysis.v1", "experiment": experiment,
            "bundle_sha256": digest(b), "raw_sha256": file_sha(journal),
            "review_sha256": digest(review), "all_trials_adjudicated": complete,
            "resource_measurements_complete": costs_complete, "arms": arms, "contrasts": contrasts,
            "uncertainty_assumption": "independent_exchangeable_curator_reviewed_families; bootstrap intervals are approximate",
            "compute_matched": False, "lifecycle_costs_evaluated": False,
            "budget_compliance": {
                key: (all(r["resources"] is not None and r["resources"][key] is not None
                           and r["resources"][key] <= b["budget_caps"][experiment][key] for r in scored.values())
                      if all(r["resources"] is not None and r["resources"][key] is not None for r in scored.values()) else None)
                for key in ("active_flops", "energy_joules", "model_calls")},
            "reader_admission_issued": False, "production_authority": False}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("plan", "preflight", "run", "analyze"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--bundle", type=Path); p.add_argument("--review", type=Path)
    p.add_argument("--root", type=Path); p.add_argument("--experiment", choices=ARMS)
    p.add_argument("--reader-review", type=Path); p.add_argument("--journal", type=Path)
    p.add_argument("--judgments", type=Path)
    args = p.parse_args(argv)
    try:
        if args.mode == "plan":
            write_new(args.output, plan()); return 0
        require(args.bundle is not None and args.review is not None, "bundle/review required")
        b, review = load(args.bundle), load(args.review)
        pin = os.environ.get("HEPTA_FIVE_EXPERIMENT_REVIEW_SHA256")
        if args.mode == "analyze":
            require(args.journal is not None and args.judgments is not None, "journal/judgments required")
            write_new(args.output, analyze(b, args.journal, load(args.judgments), review, pin)); return 0
        validate_bundle(b); validate_freeze(b, review, pin)
        require(args.root is not None, "material root required"); check_materials(b, args.root, args.experiment)
        if args.mode == "preflight":
            write_new(args.output, {"status": "inputs_admitted_not_executed", "bundle_sha256": digest(b), "efficacy_claim": False}); return 0
        execute(b, review, pin, args.root, args.output, args.experiment,
                load(args.reader_review) if args.reader_review else None,
                os.environ.get("HEPTA_FIVE_READER_REVIEW_SHA256"))
        return 0
    except (Invalid, OSError, KeyError, TypeError) as error:
        # A failing invocation remains nonzero; writing a blocker receipt does
        # not turn it into successful execution. Existing outputs are not erased.
        path = args.output if args.output.suffix == ".json" else args.output / "blocked.json"
        if not path.exists():
            write_new(path, {"status": "blocked", "reason": str(error), "model_efficacy_established": False,
                             "production_authority": False})
        print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
