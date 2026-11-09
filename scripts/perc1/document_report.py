"""One-panel diagnostic evaluation; never substitutes for the PERC-1 gate."""

import base64
from collections import defaultdict
import random
from statistics import mean

from .experiment import actor_context, answer as validate_answer, validate_trace
from .report import CONTRASTS, build_report, evaluation, interval
from .schema import (
    ARMS,
    ActorObservation,
    Cost,
    Invalid,
    canonical,
    integer,
    require,
    sha,
)


def _deployment_charges(conditions, averages, overheads, cost_value, task_count):
    """Alternative deployments pay their own requirements, not all seven arms."""
    once = {}
    for condition in conditions:
        neural = condition not in ("ocr_only", "direct_roi")
        active = condition.endswith("_active")
        representation = "dense" if condition.startswith("dense_") else "global"
        charges = {
            "projection": Cost.parse(overheads["projection_once"]).total
            if neural
            else 0,
            "model_load": overheads["model_load_once"]["proxy_microcredits"]
            if neural
            else 0,
            "collector_startup": overheads["collector_startup_once"][
                "proxy_microcredits"
            ]
            if neural
            else 0,
            "ocr_initialization_only": overheads["ocr_init_once"]["proxy_microcredits"]
            if not neural
            else 0,
            "train_dev_collection": Cost.parse(
                overheads["collection_by_representation"][representation]
            ).total
            if active
            else 0,
            "head_fit": Cost.parse(
                overheads["head_fit_by_representation"][representation]
            ).total
            if active
            else 0,
            "training_label_preparation": (
                Cost.parse(overheads["label_source_read_once"]).total
                + Cost.parse(
                    overheads["label_preparation_by_representation"][representation]
                ).total
            )
            if active
            else 0,
        }
        for value in charges.values():
            integer(value)
        once[condition] = dict(charges, total=sum(charges.values()))
    sensitivity = {}
    for horizon in sorted({1, 32, 1000, integer(task_count, 1)}):
        sensitivity[str(horizon)] = {
            c: {
                "one_time_per_task": once[c]["total"] / horizon,
                "fully_charged_mean_cost": averages[c]["cost"]
                + once[c]["total"] / horizon,
                "fully_charged_utility": averages[c]["utility"]
                - cost_value * once[c]["total"] / horizon,
            }
            for c in conditions
        }
    return {
        "primary_horizon_tasks": task_count,
        "one_time_by_condition": once,
        "at_heldout_horizon": sensitivity[str(task_count)],
        "amortization_sensitivity": sensitivity,
        "scope": "observed local proxy under one reusable initialization/training artifact over N tasks; evaluation is a separate research cost; provider/energy/lifetime costs remain unknown",
    }


def evaluate(
    frozen, dataset, executions, evaluator, cost_value, overheads, bootstrap=2000
):
    targets = evaluation(evaluator, frozen, dataset)
    episodes = {
        e["id"]: e for e in dataset.episodes.values() if e["split"] == "confirmation"
    }
    require(
        episodes and len({e["family"] for e in episodes.values()}) == 1,
        "diagnostic requires one nonempty task panel",
    )
    require(200 <= integer(bootstrap) <= 10000, "invalid bootstrap count")
    conditions = list(ARMS) + ["ocr_only", "direct_roi", "random"]
    rows, phase_totals, native_traces = {}, defaultdict(lambda: defaultdict(int)), []
    for result in executions:
        trace = result["trace"]
        episode_id, mode = trace["episode_id"], result["mode"]
        condition = (
            result["representation"] + "_" + mode
            if mode in ("fixed", "active")
            else mode
        )
        require(
            episode_id in episodes
            and condition in conditions
            and (episode_id, condition) not in rows,
            "unexpected/duplicate pilot execution",
        )
        require(
            trace["manifest_sha256"] == sha(frozen), "pilot manifest identity changed"
        )
        require(
            sum(s.get("proposal") is not None for s in trace["steps"]) <= 2,
            "pilot exceeds one-extra-observation call cap",
        )
        if mode in ("fixed", "active"):
            require(
                result["valid_native_trace"] is True, "native arm lost trace validation"
            )
            audit = validate_trace(trace, frozen, dataset)
            require(
                audit["pending_reservation"] == 0 and audit["spent"] == result["spent"],
                "unsettled/changed pilot cost",
            )
            native_traces.append(trace)
        else:
            require(
                trace["schema"] == "perc1.document-comparator.v1"
                and result["valid_native_trace"] is False,
                "comparator must not claim native validation",
            )
            require(
                sum(Cost.parse(s["cost"]).total for s in trace["steps"])
                == integer(result["spent"]),
                "comparator cost mismatch",
            )
            require(
                result["spent"] <= frozen["budget"]["cap"]
                and all(s["status"] != "unknown" for s in trace["steps"]),
                "comparator exceeded budget or has unsettled cost",
            )
            observed = set()
            for index, step in enumerate(trace["steps"]):
                require(
                    step["input_sha256"]
                    == sha(
                        actor_context(
                            dataset, episodes[episode_id], trace["steps"][:index]
                        )
                    ),
                    "comparator actor prefix changed",
                )
                require(
                    step["cost"]["training"] == step["cost"]["evaluation"] == 0,
                    "offline costs entered online comparator",
                )
                if mode in ("ocr_only", "direct_roi"):
                    require(
                        step["cost"]["encoding"] == 0,
                        "OCR comparator charged an unused neural encoder",
                    )
                if step.get("observation") is not None:
                    obs = step["observation"]
                    source_id = obs["source_id"]
                    require(
                        source_id in episodes[episode_id]["source_ids"],
                        "comparator saw another task source",
                    )
                    source, raw = dataset.sources[source_id], dataset.read(source_id)
                    try:
                        decoded = base64.b64decode(obs["raw_base64"], validate=True)
                    except (ValueError, TypeError) as error:
                        raise Invalid("invalid comparator capture encoding") from error
                    require(
                        decoded == raw
                        and obs["raw_sha256"] == source["sha256"] == sha(raw)
                        and obs["locator"] == source["locator"],
                        "comparator capture/source binding changed",
                    )
                    if mode in ("ocr_only", "direct_roi"):
                        require(
                            obs["schema"] == "perc1.document-ocr-observation.v1",
                            "OCR comparator claimed a neural observation",
                        )
                        ocr = obs["ocr"]
                        require(
                            ocr["capture_sha256"] == source["sha256"]
                            and type(ocr["text"]) is str
                            and ocr["text_sha256"] == sha(ocr["text"].encode()),
                            "OCR text/source binding changed",
                        )
                    else:
                        ActorObservation.parse(
                            obs,
                            source,
                            raw,
                            frozen["encoder"],
                            result["representation"] + "_fixed",
                        )
                    observed.add(source_id)
            validate_answer(trace["answer"], observed)
        visible = canonical(
            actor_context(dataset, episodes[episode_id], trace["steps"])
        ) + canonical(trace["answer"])
        for step in trace["steps"]:
            obs = step.get("observation")
            if obs and "raw_base64" in obs:
                visible += base64.b64decode(obs["raw_base64"])
            for phase, cost in step["cost"].items():
                phase_totals[condition][phase] += cost
        require(
            not any(c.encode() in visible for c in evaluator["canaries"]),
            "sealed canary reached actor",
        )
        target, answer = targets[episode_id], trace["answer"]
        fidelity = mean(
            answer["fields"].get(k) == v for k, v in target["fields"].items()
        )
        success = float(answer["text"] == target["answer"] and fidelity == 1)
        rows[episode_id, condition] = {
            "task_success": success,
            "critical_fidelity": fidelity,
            "cost": result["spent"],
            "utility": success - cost_value * result["spent"],
        }
    require(
        set(rows) == {(e, c) for e in episodes for c in conditions},
        "incomplete paired pilot matrix",
    )
    groups = sorted({e["group"] for e in episodes.values()})
    group_ids = {
        g: [e for e, value in episodes.items() if value["group"] == g] for g in groups
    }
    metrics = ("task_success", "critical_fidelity", "cost", "utility")
    cells = {
        (g, c, m): mean(rows[e, c][m] for e in group_ids[g])
        for g in groups
        for c in conditions
        for m in metrics
    }
    averages = {
        c: {m: mean(cells[g, c, m] for g in groups) for m in metrics}
        for c in conditions
    }
    deployment = _deployment_charges(
        conditions, averages, overheads, cost_value, len(episodes)
    )
    rng = random.Random(20261109)
    draws = [rng.choices(groups, k=len(groups)) for _ in range(bootstrap)]
    effects = {}
    for metric in metrics:
        effects[metric] = {}
        comparisons = {
            name: dict(zip(ARMS, weights)) for name, weights in CONTRASTS.items()
        }
        comparisons.update(
            {
                c + "_vs_direct_roi": {c: 1, "direct_roi": -1}
                for c in conditions
                if c != "direct_roi"
            }
        )
        for name, weights in comparisons.items():
            per_group = {
                g: sum(w * cells[g, c, metric] for c, w in weights.items())
                for g in groups
            }
            samples = [mean(per_group[g] for g in draw) for draw in draws]
            effects[metric][name] = {
                "estimate": mean(per_group.values()),
                "ci95": interval(samples),
            }
    try:
        build_report(frozen, dataset, native_traces, evaluator)
    except Invalid as error:
        protocol_gate = {
            "status": "HOLD",
            "reason": str(error),
            "validation_relaxed": False,
        }
    else:
        raise Invalid(
            "single-panel pilot unexpectedly passed complete PERC-1 prerequisites"
        )
    return {
        "schema": "perc1.document-pilot-report.v1",
        "status": "HOLD",
        "scientific_qualified": False,
        "structural_validation": "PASS",
        "manifest_sha256": sha(frozen),
        "episodes": len(episodes),
        "source_groups": len(groups),
        "families": sorted({e["family"] for e in episodes.values()}),
        "independent_training_replicates": 0,
        "deterministic_fit_campaigns": 1,
        "paired_native_traces": len(native_traces),
        "comparator_executions": len(executions) - len(native_traces),
        "arms": averages,
        "effects": effects,
        "deployment_charges": deployment,
        "complete_protocol_gate": protocol_gate,
        "confidence_method": "paired document-source-group percentile bootstrap; one fitted campaign; unadjusted exploratory intervals",
        "bootstrap_replicates": bootstrap,
        "cost_value": cost_value,
        "utility_scope": "arms/effects retain online utility; deployment_charges adds condition-specific initialization/projection/training costs over explicit N=1,32,1000 task horizons; commercial full cost unknown",
        "representation_scope": "train-only PCA of frozen MobileNet crop features enters acquisition heads; terminal OCR ignores latents, so this panel does not test a learned semantic decoder",
        "costs": {
            "online_by_condition_and_phase": {
                k: dict(v) for k, v in phase_totals.items()
            },
            "training_once": overheads["training_once"],
            "evaluation_once": evaluator["cost"],
            "projection_once": overheads["projection_once"],
            "collection_by_representation": overheads["collection_by_representation"],
            "head_fit_by_representation": overheads["head_fit_by_representation"],
            "label_preparation_by_representation": overheads[
                "label_preparation_by_representation"
            ],
            "label_source_read_once": overheads["label_source_read_once"],
            "model_load_once": overheads["model_load_once"],
            "collector_startup_once": overheads["collector_startup_once"],
            "ocr_init_once": overheads["ocr_init_once"],
            "audit_finalization_once": overheads["audit_finalization_once"],
            "campaign_proxy_total_excluding_evaluation": sum(
                sum(v.values()) for v in phase_totals.values()
            )
            + Cost.parse(overheads["training_once"]).total
            + overheads["model_load_once"]["proxy_microcredits"]
            + overheads["collector_startup_once"]["proxy_microcredits"]
            + Cost.parse(overheads["audit_finalization_once"]).total,
            "campaign_scope": "sum of all seven online conditions plus measured shared training/initialization/finalization, each once; dataset preparation outside this driver is unmeasured",
            "provider_billing": None,
            "energy_joules": None,
        },
        "hold_reasons": [
            "One controlled explicit-rectangle, single-word quality-recovery panel; no learned localization or general task claim.",
            "Frozen OCR performs terminal decoding; learned latent value is tested only through acquisition, not as a replacement for exact text recognition.",
            "Document groups are disjoint; template, organization and real operator independence remain unverified.",
            "One deterministic fit per representation; changing a seed does not supply independent training repeats.",
            "Local producer and OCR receipts are recomputable observations, not independent attestation or commercial billing.",
            "Online utility uses a frozen local time/byte tariff proxy; energy, provider prices and the actual deployment reuse horizon remain unknown.",
            "No preregistered confirmatory thresholds or multiple-comparison correction; production source/budget owners are not integrated.",
        ],
        "baseline_scope": {
            "fixed": "counterbalanced frozen catalog sequence",
            "direct_roi": "strong OCR-only source chosen by public requested geometry",
            "ocr_only": "initial OCR only",
            "random": "public catalog random read under identical quote/call cap",
        },
    }
