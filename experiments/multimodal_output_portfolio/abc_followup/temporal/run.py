"""Bounded role-specific real-generation runs, with complete request census."""

import argparse
import json
import os
from pathlib import Path
import resource
import time

import numpy as np

from experiments.multimodal_output_portfolio.abc_next.temporal.audit import sha256, write_json
from experiments.multimodal_output_portfolio.abc_next.temporal.speech import SpeechBackend
from .episodes import execute
from .state import ROUTES
from .tasks import manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--external-assets", type=Path)
    parser.add_argument("--role", choices=("development", "fit", "selection", "evaluation"), required=True)
    parser.add_argument("--policies", type=Path)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--development-limit", type=int, default=8)
    parser.add_argument("--shards", type=int, choices=(1, 2), default=1)
    parser.add_argument("--shard-index", type=int, choices=(0, 1), default=0)
    parser.add_argument("--defer-external", action="store_true")
    args = parser.parse_args()
    if args.role != "development" and args.development_limit != 8:
        raise ValueError("Only development can use a bounded pilot subset")
    if args.shard_index >= args.shards or (args.role == "evaluation" and args.shards != 1):
        raise ValueError("Final selected-policy timing must run serially")
    if args.defer_external and args.role != "evaluation":
        raise ValueError("Only frozen final generation uses deferred scoring")
    final_protocol = None
    if args.role == "evaluation":
        from .registration import verify
        final_protocol = verify(args.protocol, args.policies)
        if not args.defer_external or args.external_assets is None:
            raise ValueError("Frozen final must defer independent observation until all serial generation closes")
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    backend = SpeechBackend(args.assets)
    if final_protocol and (backend.load_receipt["manifest_sha256"] != final_protocol["tts_online_assets_sha256"] or
                           sha256(args.external_assets / "manifest.json") != final_protocol["external_assets_sha256"]):
        raise ValueError("Final generation/observation assets differ from qualification")
    external = None
    if args.external_assets and not args.defer_external:
        if args.role not in ("development", "evaluation"):
            raise ValueError("Offline observer is forbidden in fit/selection")
        from experiments.multimodal_output_portfolio.abc_next.temporal.external import ExternalObserver
        external = ExternalObserver(args.external_assets)
    policy = None
    if args.policies:
        from .value import Policy
        policy = Policy.load(args.policies)
    sources = manifest()["roles"][args.role]
    if args.role == "development":
        sources = sources[:args.development_limit]
    sources = sources[args.shard_index::args.shards]
    if args.role == "evaluation":
        if policy is None or (external is None and not args.defer_external):
            raise ValueError("Final run requires frozen policy and independent observer")
        specifications = [("fixed", tuple(policy.payload["selected_fixed_route"]), "fixed"),
                          ("initial", None, "initial"), ("feedback", None, "feedback")]
    elif args.role == "selection":
        if policy is None or args.shards != 1:
            raise ValueError("Reference selection needs serial actual policy execution")
        specifications = [("fixed", route, "fixed-" + "".join(map(str, route))) for route in ROUTES]
        specifications.extend((("initial", None, "initial"),
                               ("feedback", None, "feedback-full"),
                               ("feedback", None, "feedback-cue_only")))
    else:
        specifications = [("matrix", route, "route-" + "".join(map(str, route))) for route in ROUTES]
    write_json(args.output / "start.json", {"role": args.role, "source_groups": len(sources),
               "templates": 2, "scenarios": 2, "specifications": specifications,
               "assets": backend.load_receipt, "external": external.load_receipt if external else None,
               "external_assets_manifest_sha256": sha256(args.external_assets / "manifest.json") if args.external_assets else None,
               "external_scoring_deferred_until_all_generation_closes": args.defer_external,
               "source_manifest": manifest(), "policy_sha256": sha256(args.policies) if args.policies else None,
               "protocol_sha256": sha256(args.protocol) if args.protocol else None,
               "shards": args.shards, "shard_index": args.shard_index,
               "source_hashes": {name: sha256(Path(__file__).parent / name) for name in
                                  ("tasks.py", "state.py", "episodes.py", "run.py", "value.py")},
               "wall_start_unix_ns": time.time_ns(), "pid": os.getpid()})
    rows = []
    rng = np.random.default_rng(20261025043)
    with (args.output / "index.jsonl").open("x") as index:
        for source_index, source in enumerate(sources):
            for template in range(2):
                for scenario in range(2):
                    # Counterbalance actual policy order; never inspect outcomes.
                    order = rng.permutation(len(specifications))
                    for position in order:
                        mode, route, label = specifications[int(position)]
                        active_policy = policy.for_variant(label.removeprefix("feedback-")) if label.startswith("feedback-") else policy
                        folder = args.output / f"source-{source_index:03d}" / f"t{template}-s{scenario}" / label
                        case = execute(backend, source, scenario, template, folder,
                                       mode, route, active_policy, external)
                        entry = {"source_id": source["source_id"], "template": template,
                                 "scenario": scenario, "policy": label, "case": str(folder / "case.json"),
                                 "sha256": sha256(folder / "case.json")}
                        rows.append(entry)
                        index.write(json.dumps(entry) + "\n")
                        index.flush()
            print(json.dumps({"role": args.role, "completed_sources": source_index + 1,
                              "total_sources": len(sources), "requests": len(rows)}), flush=True)
    result = {"role": args.role, "complete": True, "source_groups": len(sources),
              "external_scoring_complete": external is not None,
              "requests": len(rows), "failures": 0, "index_sha256": sha256(args.output / "index.jsonl"),
              "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu,
              "self_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              "wall_end_unix_ns": time.time_ns(),
              "clock_scope": "after argument parsing/output mkdir; includes model loads, requests, offline scoring and index writes; excludes imports/final receipt"}
    write_json(args.output / "complete.json", result)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
