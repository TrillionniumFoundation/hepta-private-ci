"""Independent reduction of immutable durable events and credit settlements.

No calls to the registered statistics, owner audit, or metric helpers. This
review recomputes all 2,880 episode metrics and the frozen seed-level contrasts.
"""

import time

STARTED = time.perf_counter()
CPU_STARTED = time.process_time()

import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import traceback

from scipy.optimize import brentq
from scipy.special import betainc


REPO = Path(__file__).resolve().parents[4]
RUN = Path("/dev/shm/hepta-adaptive-v2-batch001/scientific001")
DEST = Path(__file__).resolve().parent / "statistics"
INPUTS = {}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_bytes(path):
    path = Path(path)
    value = path.read_bytes()
    INPUTS[str(path)] = hashlib.sha256(value).hexdigest()
    return value


def read(path):
    return json.loads(read_bytes(path))


def publish(path, value):
    data = (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    if len(data) > 512000:
        raise ValueError("bounded review artifact exceeded")
    with Path(path).open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def close(first, second, message, tolerance=1e-11):
    require(
        math.isfinite(first)
        and math.isfinite(second)
        and abs(first - second) <= tolerance * (1 + abs(second)),
        message,
    )


def add_work(total, values):
    for key, value in values.items():
        total[key] = (
            max(total.get(key, 0), value)
            if key.startswith("peak_")
            else total.get(key, 0) + value
        )


def compare_metrics(actual, expected):
    require(set(actual) == set(expected), "metric field schema")
    for key, value in actual.items():
        if isinstance(value, str):
            require(value == expected[key], f"metric {key}")
        else:
            close(value, expected[key], f"metric {key}")


def review():
    config = read(REPO / "experiments/adaptive_neuron_v2/PROTOCOL.json")
    seal_path = (
        REPO / "experiments/adaptive_neuron_v2/results/registration001/SOURCE_SEAL.json"
    )
    seal = read(seal_path)
    for relative, identity in seal["inputs"].items():
        require(
            digest(REPO / relative) == identity["sha256"], f"sealed source {relative}"
        )
        INPUTS[str(REPO / relative)] = identity["sha256"]
    complete = read(RUN / "COMPLETE.json")
    require(
        complete["complete"] and not (RUN / "FAILED.json").exists(),
        "complete science run",
    )
    native_root, audit_root = RUN / "raw/native", RUN / "raw/audit"
    native_index, audit_index = (
        read(native_root / "INDEX.json"),
        read(audit_root / "INDEX.json"),
    )
    registered = read(RUN / "statistics/STATISTICS.json")
    require(
        native_index["complete"] and audit_index["passed"] and registered["complete"],
        "complete registered evidence",
    )
    require(
        registered["deployment_index_sha256"]
        == audit_index["deployment_index_sha256"]
        == digest(native_root / "INDEX.json"),
        "native index binding",
    )
    require(
        registered["audit_index_sha256"] == digest(audit_root / "INDEX.json"),
        "audit index binding",
    )
    require(
        complete["facts"]["statistics_sha256"]
        == digest(RUN / "statistics/STATISTICS.json"),
        "batch statistics binding",
    )
    for artifact in (native_index, audit_index, registered):
        require(
            artifact["source"]["seal_sha256"] == digest(seal_path),
            "source seal binding",
        )
        require(
            artifact["source"]["source_commit"] == seal["source_commit"],
            "source commit binding",
        )
    expected = [
        (seed, split, v["id"])
        for seed in config["confirmation_seeds"]
        for split in config["deployment"]["splits"]
        for v in config["deployment"]["variants"]
    ]
    for artifact in (native_index, audit_index):
        require(
            [(r["seed"], r["split"], r["variant"]) for r in artifact["organs"]]
            == expected,
            "complete registered organ roster",
        )
    require(len(expected) == 180, "registered organ count")
    audit_records = {r["organ"]: r for r in audit_index["organs"]}
    registered_seeds = {
        (r["seed"], r["split"], r["variant"]): r for r in registered["seed_means"]
    }
    variants = {v["id"]: v for v in config["deployment"]["variants"]}
    seed_rows, organ_records, episodes_by_arm, shared_streams = [], [], {}, {}
    execution_work, replay_work = {}, {}
    total_episodes, total_ticks, total_cells, total_spikes = 0, 0, 0, 0
    for row in native_index["organs"]:
        name, seed, split, variant = (
            row["organ"],
            row["seed"],
            row["split"],
            row["variant"],
        )
        organ_root = native_root / "organs" / name
        native = read(organ_root / "INDEX.json")
        plan = read(organ_root / "PLAN.json")
        audit_path = audit_root / "organs" / f"{name}.json"
        audit = read(audit_path)
        binding = audit_records[name]
        require(
            digest(organ_root / "INDEX.json")
            == row["index_sha256"]
            == binding["index_sha256"],
            "organ index binding",
        )
        require(digest(audit_path) == binding["audit_sha256"], "organ audit binding")
        require(
            audit["passed"]
            and audit["raw_bytes_unchanged"]
            and not audit["development_only"],
            "successful immutable native audit",
        )
        require(
            native["complete"] and not native["development_only"],
            "complete formal native organ",
        )
        require(
            digest(organ_root / "PLAN.json") == native["plan_sha256"],
            "organ plan binding",
        )
        for relative, h in audit["raw_file_hashes"].items():
            path = organ_root / relative
            require(digest(path) == h, f"audited raw evidence {path}")
            INPUTS[str(path)] = h
        model = read(organ_root / "MODEL.json")
        training_arm = variants[variant]["training_arm"]
        trained_root = RUN / "learning/confirmation" / f"seed_{seed}" / training_arm
        require(
            digest(organ_root / "TRAINED_CHECKPOINT.json")
            == digest(trained_root / "checkpoint.json"),
            "owner uses trained checkpoint bytes",
        )
        require(
            model["neural"] == read(trained_root / "neural.json"),
            "owner deploys complete trained model",
        )
        require(
            len(plan["episodes"])
            == len(native["episodes"])
            == audit["episodes_verified"]
            == 16,
            "complete episode group",
        )
        policy = variants[variant]
        balance, shadow = 16.0, 0.02
        episode_rows = []
        audit_metrics = {r["case"]: r["metrics"] for r in audit["episode_metrics"]}
        for episode_number, (spec, receipt) in enumerate(
            zip(plan["episodes"], native["episodes"], strict=True)
        ):
            case = spec["case"]
            require(
                case == receipt["case"] == f"case.{episode_number:04d}",
                "ordered episode identity",
            )
            stream_key = (seed, split, episode_number)
            if stream_key in shared_streams:
                require(
                    spec == shared_streams[stream_key],
                    "same information/budget schedule across nine arms",
                )
            else:
                shared_streams[stream_key] = spec
            episode_root = organ_root / case
            episode = read(episode_root / "EPISODE.json")
            require(
                digest(episode_root / "EPISODE.json") == receipt["episode_sha256"],
                "episode receipt binding",
            )
            require(episode["specification"] == spec, "executed registered stream")
            events_data = read_bytes(episode_root / "events.jsonl")
            events = [json.loads(line) for line in events_data.splitlines()]
            require(
                hashlib.sha256(events_data).hexdigest()
                == episode["raw_files"]["events.jsonl"]["sha256"],
                "durable event binding",
            )
            require(0 < len(events) <= spec["context"][2], "purchased causal prefix")
            close(
                episode["initial_account"]["balance"],
                balance,
                "previous balance feeds next episode",
            )
            close(
                episode["initial_account"]["price"],
                shadow,
                "previous price feeds next episode",
            )
            require(
                episode["initial_account"]["sequence"] == episode_number,
                "account sequence",
            )
            applied_price = (
                0.0
                if policy["credit"] == "off"
                else 0.02
                if policy["credit"] == "frozen"
                else shadow
            )
            actual_work, spikes, cells = 0.0, 0, 0
            fallbacks, applied = 0, 0
            for tick, event in enumerate(events, 1):
                observation, output = event["observation"], event["output"]
                require(
                    observation["elapsed"] == tick
                    and observation["value"] == spec["observations"][tick - 1],
                    "only observed prefix supplied",
                )
                require(
                    balance - actual_work >= 2.0 - 1e-10,
                    "actual observation reserved before execution",
                )
                require(
                    output["terminal"] == (tick == len(events)),
                    "first terminal stops native trajectory",
                )
                require(
                    output["owner_authority"] == "DENY_ALL"
                    and output["native_transition_executed"],
                    "research authority and actual owner execution",
                )
                require(
                    not output["duplicate_event_ignored"], "no duplicate event counted"
                )
                readout = output["readout"]
                require(readout is not None, "readout applied to every measured tick")
                applied += 1
                fallbacks += output["native_abstain"]
                close(readout["used_price"], applied_price, "episode price held fixed")
                close(
                    readout["effective_cost"],
                    spec["context"][1] + 2 * applied_price,
                    "price enters stopping cost",
                )
                expected_cells = 8 if policy["readout"] == "snn" else 0
                require(
                    output["actual_snn_cell_updates"]
                    == readout["actual_snn_cell_updates"]
                    == expected_cells,
                    "actual neural cell work",
                )
                if not expected_cells:
                    require(
                        output["actual_spikes"] == 0,
                        "same-info raw baseline executes no SNN",
                    )
                tick_spikes = output["actual_spikes"]
                require(
                    tick_spikes == readout["spikes"] and 0 <= tick_spikes <= 8,
                    "actual spike count",
                )
                tick_work = 1 + tick_spikes / 8
                close(
                    output["actual_resource_work"],
                    tick_work,
                    "actual purchased resource work",
                )
                close(readout["actual_work"], tick_work, "readout resource work")
                actual_work += tick_work
                spikes += tick_spikes
                cells += expected_cells
                close(
                    readout["state_after"]["balance"],
                    balance - actual_work,
                    "debit executed work",
                )
            final = events[-1]["output"]
            decision = (
                "abstain" if final["native_abstain"] else final["readout"]["action"]
            )
            require(
                decision in ("positive", "negative", "abstain"),
                "actual terminal action",
            )
            covered = decision != "abstain"
            correct = covered and (1 if decision == "positive" else -1) == spec["truth"]
            reward = 0.05 if not covered else 1.0 if correct else -1.0
            next_shadow = min(
                0.08,
                max(
                    0.0, shadow + 0.005 * (actual_work - spec["budget"] - 0.5 * reward)
                ),
            )
            uncapped_balance = balance - actual_work + spec["budget"] + 0.5 * reward
            next_balance, overflow = (
                min(32.0, uncapped_balance),
                max(0.0, uncapped_balance - 32.0),
            )
            settlement = json.loads(episode["settlement"]["record"]["payload_json"])
            for key, value in [
                ("actual_work", actual_work),
                ("after_price", next_shadow),
                ("after_balance", next_balance),
                ("balance_overflow", overflow),
                ("reward", reward),
            ]:
                close(settlement[key], value, f"native settlement {key}")
            credit = settlement["native_credit"]
            require(
                credit["conservation_residual_q32"] == 0
                and credit["native_function"] == "finalize_credit_batch",
                "original native credit finalizer conservation",
            )
            require(
                credit["authority"] == "DENY_ALL"
                and not credit["production_ledger_append"]
                and not credit["signature_admission"],
                "research sidecar scope preserved",
            )
            actual = {
                "actual_resource_work": actual_work,
                "actual_snn_cell_updates": cells,
                "actual_spikes": spikes,
                "applied_readouts": applied,
                "avoided_later_observations": spec["context"][2] - len(events),
                "balance_after": next_balance,
                "balance_before": balance,
                "balance_overflow": overflow,
                "budget_forced_abstention": final["readout"][
                    "budget_forced_abstention"
                ],
                "correct": correct,
                "covered": covered,
                "decision": decision,
                "native_fallbacks": fallbacks,
                "observations": len(events),
                "price_used": applied_price,
                "reward": reward,
                "shadow_price_after": next_shadow,
                "shadow_price_before": shadow,
                "utility": reward - len(events) * spec["context"][1],
            }
            for reported in (
                episode["metrics"],
                receipt["metrics"],
                audit_metrics[case],
            ):
                compare_metrics(actual, reported)
            episode_rows.append(actual)
            total_episodes += 1
            total_ticks += len(events)
            total_cells += cells
            total_spikes += spikes
            add_work(execution_work, episode["work"])
            balance, shadow = next_balance, next_shadow
        close(audit["final_account"]["balance"], balance, "final durable balance")
        close(audit["final_account"]["price"], shadow, "final durable price")
        add_work(replay_work, audit["work"])
        key = (seed, split, variant)
        reported_seed = registered_seeds[key]
        means = {
            metric: math.fsum(float(e[metric]) for e in episode_rows) / 16
            for metric in reported_seed["means"]
        }
        for metric, value in means.items():
            close(value, reported_seed["means"][metric], f"seed {key} metric {metric}")
        correct_count, covered_count = (
            sum(e["correct"] for e in episode_rows),
            sum(e["covered"] for e in episode_rows),
        )
        accuracy = correct_count / covered_count if covered_count else None
        require(
            accuracy == reported_seed["conditional_accuracy"], "conditional accuracy"
        )
        seed_rows.append(
            {"seed": seed, "split": split, "variant": variant, "means": means}
        )
        episodes_by_arm[key] = episode_rows
        organ_records.append(
            {
                "organ": name,
                "native_index_sha256": row["index_sha256"],
                "audit_sha256": binding["audit_sha256"],
                "episode_count": len(episode_rows),
                "purchased_observations": sum(e["observations"] for e in episode_rows),
                "actual_spikes": sum(e["actual_spikes"] for e in episode_rows),
            }
        )
    require(
        total_episodes == registered["episodes"] == 2880 and len(seed_rows) == 180,
        "complete statistics sample",
    )
    for actual, reported, label in [
        (execution_work, registered["execution_work"], "execution"),
        (replay_work, registered["independent_replay_work"], "replay"),
    ]:
        require(actual.keys() == reported.keys(), f"{label} work schema")
        for key, value in actual.items():
            close(value, reported[key], f"{label} work {key}")
    require(
        total_ticks == execution_work["owner_ticks"]
        and total_cells == execution_work["actual_snn_cell_updates"]
        and total_spikes == execution_work["actual_spikes"],
        "event-derived totals",
    )
    means = {(r["seed"], r["split"], r["variant"]): r["means"] for r in seed_rows}
    settings = config["statistics"]
    contrasts = []
    df = len(config["confirmation_seeds"]) - 1
    tail = settings["family_alpha"] / (2 * len(settings["primary_contrasts"]))
    # Independent numerical quantile inversion, not scipy.stats.t.ppf.
    quantile = brentq(
        lambda q: 0.5 * betainc(df / 2, 0.5, df / (df + q * q)) - tail,
        0.0,
        100.0,
        xtol=1e-13,
    )
    for (first, second), reported in zip(
        settings["primary_contrasts"], registered["primary_contrasts"], strict=True
    ):
        difference = [
            means[seed, "ood_test", first]["utility"]
            - means[seed, "ood_test", second]["utility"]
            for seed in config["confirmation_seeds"]
        ]
        average = math.fsum(difference) / 10
        variance = math.fsum((x - average) ** 2 for x in difference) / 9
        sem = math.sqrt(variance / 10)
        lower, upper = average - quantile * sem, average + quantile * sem
        require(
            reported["first"] == first
            and reported["second"] == second
            and reported["split"] == "ood_test",
            "registered contrast identity",
        )
        for a, b in zip(difference, reported["paired_differences"], strict=True):
            close(a, b, "paired seed difference")
        for key, value in [
            ("mean_difference", average),
            ("standard_error", sem),
            ("lower", lower),
            ("upper", upper),
            ("confidence_level", 0.975),
        ]:
            close(value, reported[key], f"paired interval {key}")
        require(
            reported["superiority_established"] == (lower > 0.005),
            "frozen superiority rule",
        )
        contrasts.append(
            {
                "first": first,
                "second": second,
                "independent_seeds": 10,
                "paired_differences": difference,
                "mean_difference": average,
                "standard_error": sem,
                "confidence_level": 0.975,
                "lower": lower,
                "upper": upper,
                "superiority_established": lower > 0.005,
            }
        )
    trajectory = []
    for reported in registered["trajectory_changes"]:
        first, second = reported["first"], reported["second"]
        changed_times, changed_actions, pairs = 0, 0, 0
        for seed, split in itertools.product(
            config["confirmation_seeds"], config["deployment"]["splits"]
        ):
            for a, b in zip(
                episodes_by_arm[seed, split, first],
                episodes_by_arm[seed, split, second],
                strict=True,
            ):
                pairs += 1
                changed_times += a["observations"] != b["observations"]
                changed_actions += a["decision"] != b["decision"]
        actual = {
            "first": first,
            "second": second,
            "paired_episodes": pairs,
            "different_stopping_times": changed_times,
            "different_terminal_actions": changed_actions,
        }
        require(actual == reported, "actual trajectory influence")
        trajectory.append(actual)
    for group in registered["descriptive_summaries"]:
        for metric, value in group["means"].items():
            expected_value = (
                math.fsum(
                    means[seed, group["split"], group["variant"]][metric]
                    for seed in config["confirmation_seeds"]
                )
                / 10
            )
            close(value, expected_value, "descriptive baseline retained")
    require(
        all(digest(path) == h for path, h in INPUTS.items()),
        "all input bytes unchanged during independent reduction",
    )
    manifest_hash = hashlib.sha256(
        json.dumps(INPUTS, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema": "hepta.adaptive-neuron.independent-statistics-review.v1",
        "passed": True,
        "source_commit": seal["source_commit"],
        "source_seal_sha256": digest(seal_path),
        "original_statistics_sha256": digest(RUN / "statistics/STATISTICS.json"),
        "input_files_verified": len(INPUTS),
        "input_manifest_sha256": manifest_hash,
        "raw_inputs_unchanged": True,
        "organs": 180,
        "episodes": 2880,
        "independent_seeds": 10,
        "same_causal_stream_groups": len(shared_streams),
        "actual_owner_ticks": total_ticks,
        "actual_neural_cell_updates": total_cells,
        "actual_spikes": total_spikes,
        "credit_settlements_independently_recomputed": total_episodes,
        "all_deployed_checkpoint_bytes_verified": True,
        "student_t_quantile_by_incomplete_beta_inversion": quantile,
        "primary_contrasts": contrasts,
        "trajectory_changes": trajectory,
        "organ_records": organ_records,
        "seed_means": seed_rows,
        "all_descriptive_summaries_verified": True,
        "work_totals_verified": True,
        "scope": "Recompute all episode utility, stopping time, spike/resource counts and credit prices/balances from durable events and terminal actions; verify all original raw hashes, model/checkpoint bindings and frozen seed-level inference. Does not rerun native execution or replace the already-complete cold replay audit. This study uses the original credit finalizer with a DENY_ALL research sidecar; production signed admission belongs to a separate qualification.",
    }


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=False)
    publish(
        DEST / "START.json",
        {
            "script_sha256": digest(__file__),
            "run": str(RUN),
            "scope": "From first script statements before substantive imports; excludes Python interpreter startup, prior interactive inspection and script authoring.",
        },
    )
    try:
        result = review()
        publish(DEST / "REVIEW.json", result)
        publish(
            DEST / "COMPLETE.json",
            {
                "passed": True,
                "review_sha256": digest(DEST / "REVIEW.json"),
                "wall_seconds": time.perf_counter() - STARTED,
                "cpu_seconds": time.process_time() - CPU_STARTED,
                "scope": "Own Python process including imports, raw evidence checks and independent reductions; excludes final receipt write and is additional to original batch costs.",
            },
        )
        print(
            json.dumps(
                {
                    k: result[k]
                    for k in (
                        "passed",
                        "episodes",
                        "actual_owner_ticks",
                        "actual_neural_cell_updates",
                        "actual_spikes",
                        "primary_contrasts",
                        "trajectory_changes",
                    )
                }
            )
        )
    except BaseException:
        publish(
            DEST / "FAILED.json",
            {
                "passed": False,
                "traceback": traceback.format_exc(),
                "wall_seconds": time.perf_counter() - STARTED,
                "cpu_seconds": time.process_time() - CPU_STARTED,
            },
        )
        raise
