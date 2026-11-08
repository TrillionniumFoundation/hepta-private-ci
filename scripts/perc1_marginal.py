"""Audit one extra observation against an identical static replay prefix.

The caller executes the same frozen answer continuation twice: once without the
new observation and once with it. This tool verifies the submitted pair and
scores final answers; it does not authenticate the model execution or a live
environment's counterfactual state. Scientific qualification remains HOLD.
"""
import argparse
import base64
import json
from pathlib import Path
from statistics import mean
import sys

from perc1.experiment import actor_context, validate_trace
from perc1.report import evaluation
from perc1.schema import Dataset, Invalid, canonical, digest, exact, integer, load
from perc1.schema import manifest, require, sha


def compare_pair(pair, frozen, dataset, evaluator):
    """Score a one-observation intervention followed by the same answer policy.

    `without.steps` must be an exact prefix of `with.steps`. The latter has
    exactly one extra successful, previously unseen observation and no further
    acquisition. Both final answers are scored independently of the actor.
    """
    manifest(frozen, dataset)
    exact(pair, "schema world_snapshot_sha256 continuation_sha256 inference_seed without with")
    require(pair["schema"] == "perc1.marginal-pair.v1", "wrong marginal pair schema")
    require(digest(pair["world_snapshot_sha256"]) == sha(dataset.value), "replay world changed")
    require(digest(pair["continuation_sha256"]) == frozen["controller"]["sha256"], "answer continuation changed")
    integer(pair["inference_seed"])
    without, acquired = pair["without"], pair["with"]
    audits = [validate_trace(t, frozen, dataset) for t in (without, acquired)]
    require(all(without[k] == acquired[k] for k in ("episode_id", "seed", "arm", "manifest_sha256")), "marginal pair scope changed")
    require(without["arm"].endswith("active"), "marginal intervention requires the active policy arm")
    require(len(acquired["steps"]) == len(without["steps"]) + 1, "requires exactly one extra observation")
    require(canonical(without["steps"]) == canonical(acquired["steps"][:-1]), "actor prefixes differ")
    extra = acquired["steps"][-1]
    require(extra["status"] == "observed" and extra["observation"] is not None, "intervention supplied no new observation")
    require(not any(a["pending_reservation"] for a in audits), "pending effects cannot be a settled marginal comparison")
    source_id = extra["proposal"]["source_id"]
    require(source_id not in audits[0]["observed"], "intervention repeats existing evidence")
    capture = lambda observation: (observation["raw_sha256"], canonical(observation["locator"]))
    seen_captures = {capture(step["observation"]) for step in without["steps"] if step["observation"] is not None}
    require(capture(extra["observation"]) not in seen_captures, "intervention is an alias of existing evidence")
    for source in dataset.sources.values():
        dataset.read(source["id"])
    targets = evaluation(evaluator, frozen, dataset)
    require(without["episode_id"] in targets, "missing marginal evaluator target")
    target = targets[without["episode_id"]]
    episode = dataset.episodes[without["episode_id"]]
    scores = []
    for trace in (without, acquired):
        visible = canonical(actor_context(dataset, episode, trace["steps"])) + canonical(trace["answer"])
        visible += b"".join(base64.b64decode(s["observation"]["raw_base64"]) for s in trace["steps"] if s["observation"] is not None)
        require(not any(c.encode() in visible for c in evaluator["canaries"]), "sealed evaluator canary reached replay actor")
        fields = trace["answer"]["fields"]
        fidelity = mean(fields.get(k) == v for k, v in target["fields"].items())
        scores.append({"task_success": int(trace["answer"]["text"] == target["answer"] and fidelity == 1),
                       "critical_fidelity": fidelity})
    extra_cost = audits[1]["spent"] - audits[0]["spent"]
    require(extra_cost > 0, "new observation is missing its incremental charge")
    return {
        "schema": "perc1.marginal-report.v1", "status": "HOLD",
        "structural_validation": "PASS", "scientific_qualified": False,
        "pair_sha256": sha(pair), "manifest_sha256": sha(frozen),
        "prefix_sha256": sha(actor_context(dataset, episode, without["steps"])),
        "world_snapshot_sha256": pair["world_snapshot_sha256"],
        "episode_id": without["episode_id"], "arm": without["arm"],
        "training_seed": without["seed"], "inference_seed": pair["inference_seed"],
        "new_source_id": source_id, "without": scores[0], "with": scores[1],
        "task_success_change": scores[1]["task_success"] - scores[0]["task_success"],
        "critical_fidelity_change": scores[1]["critical_fidelity"] - scores[0]["critical_fidelity"],
        "incremental_cost": extra_cost, "cost_unit": frozen["budget"]["unit"],
        "net_utility": None,
        "scope": "one additional captured observation and terminal answer on immutable source replay",
        "limits": [
            "Continuation identity and inference seed are caller receipts; execution is not independently attested.",
            "This comparison does not estimate counterfactual effects in a changing live environment.",
            "No equal-cost sham or randomized online intervention is supplied.",
            "A declared value-of-cost rule is required before converting correctness and cost into net utility.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "dataset", "evaluator", "pair"):
        parser.add_argument(name)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        dataset = Dataset(load(args.dataset), Path(args.dataset).parent)
        result = compare_pair(load(args.pair), load(args.manifest), dataset, load(args.evaluator))
        if args.output:
            Path(args.output).write_bytes(canonical(result) + b"\n")
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (Invalid, OSError, ValueError, TypeError, KeyError, UnicodeError) as error:
        reason = str(error) if isinstance(error, Invalid) else "Malformed or unavailable input: " + type(error).__name__
        print(json.dumps({"status": "HOLD", "structural_validation": "FAIL", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
