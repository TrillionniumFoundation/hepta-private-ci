"""Independently audit saved routing outputs; never train or execute a model.

Normal mode reads a sealed unified run and only the executed domains in its
source snapshot. Legacy mode requires explicitly supplied, unsealed sources.
An audit is written outside the input run and never repairs historical evidence.
"""

import argparse
import json
from pathlib import Path
import statistics

from v3.routing_audit_core import (
    INTENTS,
    PACKAGE,
    REJECT,
    StoredRun,
    arm_metrics,
    compare,
    encoded,
    expected_queries,
    literal,
    parsed,
    require,
    route_metrics,
    sha,
)


ARMS = {
    "parameter_learned_semantic": "semantic",
    "parameter_raw_semantic": "raw_semantic",
    "parameter_slot_semantic": "slot_semantic",
    "parameter_learned_oracle_route": "oracle",
    "parameter_exact_planner_semantic": "semantic",
    "parameter_exact_planner_oracle": "oracle",
    "parameter_single_hop": "semantic",
    "parameter_removed_cross_edges": "semantic",
    "parameter_permuted_ports": "semantic",
    "parameter_zero_shot_route": "zero_shot_description",
    "parameter_literal_route": "literal",
    "exact_values_learned_semantic": "semantic",
    "exact_values_learned_oracle_route": "oracle",
    "exact_values_exact_planner_semantic": "semantic",
    "exact_values_exact_planner_oracle": "oracle",
    "exact_values_exact_trained_layout": "semantic",
    "lossless_codec_learned_semantic": "semantic",
    "lossless_codec_raw_semantic": "raw_semantic",
    "lossless_codec_slot_semantic": "slot_semantic",
    "lossless_codec_raw_without_risk_abstention": "raw_without_risk_abstention",
    "lossless_codec_oracle_route": "oracle",
    "lossless_codec_removed_cross_edges": "semantic",
    "lossless_codec_permuted_ports": "semantic",
    "strong_exact_codec_planner_semantic": "semantic",
    "strong_exact_codec_planner_oracle": "oracle",
}


def artifact(store, prefix):
    manifest_raw, weights = (
        store.read(prefix + "/manifest.json"),
        store.read(prefix + "/weights.bin"),
    )
    manifest = parsed(manifest_raw)
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    require(
        manifest["manifest_sha256"] == sha(encoded(body)),
        "model manifest checksum differs",
    )
    require(
        len(weights) == manifest["parameter_bytes"]
        and sha(weights) == manifest["parameter_sha256"],
        "model parameters differ",
    )
    files = {
        "manifest.json": {"bytes": len(manifest_raw), "sha256": sha(manifest_raw)},
        "weights.bin": {"bytes": len(weights), "sha256": sha(weights)},
    }
    return manifest, weights, files


def audit_policy(store, prefix, summary):
    policy = summary["router_selection_study"]
    require(len(policy["candidates"]) == 12, "router candidate inventory differs")
    selected, payloads, candidate_bytes, found = {}, [], 0, []
    expected = {
        (mode, aliases, l2)
        for mode in ("raw", "slot")
        for aliases in ((0, 3, 6) if mode == "raw" else (0,))
        for l2 in (0.0001, 0.0003, 0.001)
    }
    require(
        {(row["mode"], row["alias_count"], row["l2"]) for row in policy["candidates"]}
        == expected,
        "wrong candidate grid",
    )
    for row in policy["candidates"]:
        if "artifact" not in row:
            require(
                store.legacy_sources is not None, "candidate weights were not retained"
            )
            continue
        receipt = row["artifact"]
        expected_path = (
            f"candidates/{row['mode']}-aliases{row['alias_count']}-l2{row['l2']:g}"
        )
        require(
            receipt["path"] == expected_path, "candidate artifact identity/path differs"
        )
        manifest, _, files = artifact(
            store, prefix + "/routing-policies/" + receipt["path"]
        )
        require(
            manifest["source_commit"] == summary["source_commit"]
            and manifest["support_digest"] == summary["support_digest"]
            and manifest["encoder_digest"] == sha(encoded(summary["encoder"])),
            "candidate source/encoder binding differs",
        )
        total = sum(info["bytes"] for info in files.values())
        require(
            receipt["files"] == files
            and receipt["bytes"] == total
            and receipt["inventory_sha256"] == sha(encoded(files)),
            "candidate byte accounting differs",
        )
        require(
            receipt["manifest_sha256"] == manifest["manifest_sha256"],
            "candidate identity differs",
        )
        candidate_bytes += total
        found.append(receipt["path"])
    require(len(found) == len(set(found)), "candidate artifact path reused")
    selected_bytes = 0
    for mode in ("raw", "slot"):
        manifest, weights, files = artifact(store, prefix + "/routing-policies/" + mode)
        require(
            manifest["source_commit"] == summary["source_commit"]
            and manifest["support_digest"] == summary["support_digest"],
            "selected policy source binding differs",
        )
        require(
            manifest["encoder_digest"] == sha(encoded(summary["encoder"])),
            "selected policy encoder binding differs",
        )
        selected[mode] = manifest
        payloads.append(
            weights
            + encoded(
                {
                    "threshold": manifest["threshold"],
                    "margin": manifest["margin"],
                    "reject_all": manifest["reject_all"],
                }
            )
        )
        chosen = policy["selected"][mode]
        require(
            manifest == chosen["selected_manifest"], "selected router manifest differs"
        )
        size = sum(info["bytes"] for info in files.values())
        if found:
            require(
                files == chosen["artifact"]["files"]
                and size == chosen["selected_copy_artifact_bytes"],
                "selected duplicate bytes differ",
            )
        selected_bytes += size
    graph, graph_weights, graph_files = artifact(
        store, prefix + "/parameter-layout/model"
    )
    _, exact_weights, _ = artifact(store, prefix + "/exact-layout-diagnostic/model")
    policy_hash = sha(sha(b"".join(payloads)).encode() + graph_weights + exact_weights)
    require(
        policy_hash
        == summary["frozen_policy_digest_before_evaluation"]
        == summary["frozen_policy_digest_after_evaluation"],
        "frozen policy digest differs",
    )
    require(summary["policy_unchanged"] is True, "policy changed during transfer")
    if found:
        require(
            candidate_bytes == policy["all_candidate_artifact_bytes"]
            and candidate_bytes + selected_bytes
            == policy["research_model_artifact_bytes_including_selected_copies"]
            and len(found) == 12,
            "research model bytes differ",
        )
    return (
        selected,
        {row["name"]: row for row in graph["specs"]},
        {
            "recomputed_frozen_policy_digest": policy_hash,
            "selected_router_count": 2,
            "candidate_artifacts_verified": len(found),
            "candidate_artifact_bytes": candidate_bytes,
            "selected_copy_bytes": selected_bytes,
            "research_router_bytes_including_selected_copies": candidate_bytes
            + selected_bytes,
            "primary_layout_bytes": sum(info["bytes"] for info in graph_files.values()),
            "legacy_missing_candidate_artifacts": not bool(found),
        },
    )


def decision(decision, manifest):
    winner = decision["raw_route"]
    require(
        winner in manifest["classes"]
        and 0 <= decision["confidence"] <= 1
        and 0 <= decision["margin"] <= 1,
        "invalid stored routing decision",
    )
    accepted = (
        not manifest["reject_all"]
        and winner != REJECT
        and decision["confidence"] >= manifest["threshold"]
        and decision["margin"] >= manifest["margin"]
    )
    route = winner if accepted else None
    require(route == decision["route"], "decision violates saved rejection policy")
    return route


def audit_seed(store, prefix, language, names, allowed_domains):
    summary = store.json(prefix + "/summary.json")
    require(
        set(summary["domains"]) == set(allowed_domains),
        "executed domain inventory differs before source loading",
    )
    selected, specs, policy = audit_policy(store, prefix, summary)
    domains = {}
    primary = summary["primary_router_mode"]
    require(
        primary == summary["router_selection_study"]["selected_primary_mode"],
        "primary policy differs",
    )
    for domain, reported in summary["domains"].items():
        require(
            reported["new_domain_policy_updates"] == 0
            and reported["policy_training_domain"] == "co2",
            "transfer policy was updated",
        )
        require(
            reported["routing"]["primary_mode_selected_on_noaa_selection"] == primary,
            "domain policy family differs",
        )
        source_group = "held-economy" if domain == "unemployment" else "numeric"
        source = parsed(
            store.source(PACKAGE + f"/sources/{source_group}/{domain}.json")
        )
        require(source["domain"] == domain, "wrong source domain")
        expected = expected_queries(
            source,
            summary["seed"],
            summary["evaluation_partition"],
            language,
            names[domain],
        )
        root = prefix + "/evaluation/" + domain
        routing = store.rows(root + "/routing.jsonl")
        queries = [row["query"] for row in routing]
        require(
            len(queries) == len(expected)
            and {row["id"] for row in queries} == set(expected),
            "missing or duplicate routing queries",
        )
        require(
            all(row == expected[row["id"]] for row in queries),
            "query differs from frozen language/address fixture",
        )
        routes = {name: {} for name in reported["routing"]["routes"]}
        for row in routing:
            query, identifier = row["query"], row["query"]["id"]
            require(row["primary_mode"] == primary, "domain switched routing policy")
            raw, slot = (
                decision(row["raw_semantic"], selected["raw"]),
                decision(row["slot_semantic"], selected["slot"]),
            )
            values = {
                "raw_semantic": raw,
                "slot_semantic": slot,
                "semantic": raw if primary == "raw" else slot,
                "raw_without_risk_abstention": None
                if row["raw_semantic"]["raw_route"] == REJECT
                else row["raw_semantic"]["raw_route"],
                "zero_shot_description": row["zero_shot_description"],
                "literal": row["literal"],
                "oracle": None if query["intent"] == REJECT else query["intent"],
            }
            require(set(values) == set(routes), "route comparator inventory differs")
            for name, route in values.items():
                require(route is None or route in INTENTS, "unsupported routing output")
                routes[name][identifier] = route
        routing_metrics = {
            name: route_metrics(queries, [mapping[row["id"]] for row in queries])
            for name, mapping in routes.items()
        }
        for name, metrics in routing_metrics.items():
            compare(
                reported["routing"]["routes"][name],
                metrics,
                domain + "/routing/" + name,
            )
        require(set(reported["arms"]) == set(ARMS), "missing or extra evaluation arm")
        arms = {}
        for arm, route_name in ARMS.items():
            rows = store.rows(root + "/" + arm + ".jsonl")
            require(
                all(row["arm"] == arm for row in rows), "arm file contains another arm"
            )
            arms[arm] = arm_metrics(
                rows,
                expected,
                routes[route_name],
                source,
                specs,
                reported["arms"][arm]["permutation"],
            )
            compare(reported["arms"][arm], arms[arm], domain + "/" + arm)

        def accuracy(arm):
            return arms[arm]["exact_answer_rate"]

        gaps = {
            "parameter_exact_routing_gap": accuracy("parameter_learned_oracle_route")
            - accuracy("parameter_learned_semantic"),
            "lossless_exact_routing_gap": accuracy("lossless_codec_oracle_route")
            - accuracy("lossless_codec_learned_semantic"),
            "lossless_cross_edge_gain": accuracy("lossless_codec_learned_semantic")
            - accuracy("lossless_codec_removed_cross_edges"),
            "lossless_same_port_permutation_gain": accuracy(
                "lossless_codec_learned_semantic"
            )
            - accuracy("lossless_codec_permuted_ports"),
            "learned_minus_strong_exact_planner": accuracy(
                "lossless_codec_learned_semantic"
            )
            - accuracy("strong_exact_codec_planner_semantic"),
        }
        compare(reported.get("controlled_gaps", {}), gaps, domain + "/gaps")
        cache = len(source["years"]) * len(source["fields"]) * 5
        codecs = reported["codec_memory_writes"]
        for mode, filename in (
            ("factor_residual", "residual.archive"),
            ("strong_exact", "strong-exact.archive"),
        ):
            raw = store.read(prefix + "/codecs/" + domain + "/" + filename)
            require(
                codecs[mode]["archive_sha256"] == sha(raw)
                and codecs[mode]["archive_bytes"] == len(raw),
                "codec artifact differs",
            )
            require(
                codecs[mode]["resident_decoded_cache_bytes"] == cache,
                "decoded cache bytes differ from matrix/mask dtype and shape",
            )
        domains[domain] = {
            "routing": routing_metrics,
            "arms": arms,
            "gaps": gaps,
            "decoded_cache_bytes_per_codec": cache,
            "policy_digest": policy["recomputed_frozen_policy_digest"],
        }
    return {
        "seed": summary["seed"],
        "primary_mode": primary,
        "policy_artifacts": policy,
        "domains": domains,
    }


def aggregate(runs):
    output = {}
    for domain in runs[0]["domains"]:
        entries = [run["domains"][domain] for run in runs]
        paths = [
            ("routing", "semantic", key)
            for key in (
                "known_correct_accepted_rate",
                "known_coverage",
                "unsupported_false_accept_rate",
            )
        ]
        paths += [
            ("arms", arm, key)
            for arm in ARMS
            for key in (
                "exact_answer_rate",
                "composed_exact_answer_rate",
                "answered_mae_physical",
                "answered_rmse_physical",
                "unsupported_numeric_false_accept_rate",
            )
        ]
        paths += [("gaps", key) for key in entries[0]["gaps"]]
        metrics = {}
        for parts in paths:
            values = []
            for entry in entries:
                for part in parts:
                    entry = entry[part]
                values.append(entry)
            observed = [value for value in values if value is not None]
            metrics["/".join(parts)] = {
                "mean": statistics.fmean(observed) if observed else None,
                "minimum": min(observed) if observed else None,
                "maximum": max(observed) if observed else None,
                "seed_values": values,
                "nonmissing_seeds": len(observed),
            }
        output[domain] = metrics
    return output


def audit(run, output, *, legacy_sources=None):
    run, output = Path(run).resolve(strict=True), Path(output).absolute()
    require(
        not output.resolve().is_relative_to(run),
        "audit output must be outside the input run",
    )
    require(not output.exists() and not output.is_symlink(), "audit output must be new")
    store = StoredRun(run, legacy_sources)
    if legacy_sources is None:
        environment, protocol, status = (
            store.json("environment.json"),
            store.json("protocol.json"),
            store.json("execution_status.json"),
        )
        require(
            status["execution"] == "completed"
            and "routing_graph" in status["completed_stages"],
            "routing stage is not completed",
        )
        development = environment["mode"] == "development_only"
        require(
            environment["mode"] in ("development_only", "frozen_protocol_research"),
            "unknown execution mode",
        )
        seeds = protocol["development_seeds"] if development else protocol["seeds"]
        require(
            seeds == environment["selected_seeds"]
            and seeds
            and len(seeds) == len(set(seeds)),
            "invalid selected seeds",
        )
        domains = protocol["routing_graph"][
            "development_domains" if development else "formal_domains"
        ]
        require(
            not development or "unemployment" not in domains,
            "development audit cannot load untouched economy source",
        )
        require(
            store.identity["files"][PACKAGE + "/PROTOCOL.json"]
            == store.read_files["protocol.json"],
            "protocol differs from frozen source",
        )
        prefixes = [f"routing-graph/seed-{seed}" for seed in seeds]
    else:
        summary = store.json("summary.json")
        require(
            summary["development"] is True and "unemployment" not in summary["domains"],
            "legacy audit accepts observed development domains only",
        )
        seeds, domains, prefixes = [summary["seed"]], list(summary["domains"]), [""]
    language, names = (
        literal(store, "route_language.py", "LANGUAGE"),
        literal(store, "numeric_graph.py", "SERIES_NAMES"),
    )
    # Empty prefix is normalized without permitting arbitrary relative paths.
    if legacy_sources is not None:
        original = store.read
        store.read = lambda name: original(name.removeprefix("/"))
    runs = [audit_seed(store, prefix, language, names, domains) for prefix in prefixes]
    require(
        [item["seed"] for item in runs] == seeds
        and all(set(item["domains"]) == set(domains) for item in runs),
        "audited seed/domain inventory differs",
    )
    report = {
        "schema": "memory-cell-v3.independent-routing-audit.v1",
        "legacy_unsealed_development": legacy_sources is not None,
        "all_required_artifacts_verified": legacy_sources is None,
        "seeds": seeds,
        "domain_order": domains,
        "arm_count": len(ARMS),
        "runs": runs,
        "across_seed": aggregate(runs),
        "read_input_fingerprints": store.read_files,
        "scope": "Independent stored-row/trace/source grading and artifact accounting; no training, encoder inference, or model re-execution.",
        "limits": [
            "Source snapshot and read input hashes are checked against the run seal; git commit verification is a separate verifier.",
            "Policy digests and recorded per-hop admission are checked; this does not independently replay the live owner.",
            "Transfer uses shared saved policy artifacts and matching before/after digests; transient intermediate runtime mutations are not observable from these outputs.",
            "A legacy audit cannot recover absent candidate artifacts or establish a historical source snapshot.",
            "Across-seed means describe each fixed workload; repeated template/date queries are not independent safety trials.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded(report) + b"\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--legacy-sources",
        type=Path,
        help="Explicit unsealed source directory; accepts one historical development seed only",
    )
    args = parser.parse_args()
    report = audit(args.run, args.output, legacy_sources=args.legacy_sources)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "seeds": report["seeds"],
                "domains": report["domain_order"],
                "arms": report["arm_count"],
                "legacy": report["legacy_unsealed_development"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
