"""Read-only descriptive MEM12 results, with all missing planned outcomes.

The caller validates the frozen plan. Original provider inputs are re-read;
this is consistency checking and does not authenticate a production observer.
"""

import hashlib
import json
import re
from collections import Counter

from .episodic_local_worker import verify_returned_generation
from .episodic_memory import canonical_bytes
from .episodic_provider_handoff import _pin as pin, _read_regular
from .episodic_retrieval import verify_read_receipt


def selected_text(value):
    """Frozen public full-output parser; it never receives expected labels."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"(?:answer:\s*)?(red|orange|yellow|green|blue|purple|pink|white|unknown)[.!]?",
        value.strip().casefold(),
    )
    return None if match is None else match[1]


def build_report(output, plan, plan_sha):
    """Every planned row remains; bounds concern missing labels, not confidence."""
    rows, writers = [], []
    for case in plan["cases"]:
        writer_path = output / case["case_id"] / "writer" / "RECEIPT.json"
        writers.append(
            {
                "case_id": case["case_id"],
                "receipt": json.loads(writer_path.read_bytes())
                if writer_path.exists()
                else None,
            }
        )
        for arm in plan["arms"]:
            root = output / case["case_id"] / arm
            row = {
                "case_id": case["case_id"],
                "arm": arm,
                "correct": None,
                "status": "UNKNOWN" if root.exists() else "UNATTEMPTED",
                "physical_generations": None if root.exists() else 0,
            }
            try:
                if (root / "ROW.json").exists():
                    retained = json.loads(_read_regular(root / "ROW.json", 1048576))
                    if any(
                        retained[key] != value
                        for key, value in {
                            "case_id": case["case_id"],
                            "arm": arm,
                            "protocol_sha256": plan_sha,
                        }.items()
                    ):
                        raise ValueError("row identity mismatch")
                    row.update(retained, correct=None)
                    if row["status"] == "RETURNED":
                        raw = _read_regular(root / "PROVIDER.json", 1048576)
                        request = _read_regular(
                            root / "actor" / "actor-output.bin", 65536
                        )
                        memory = _read_regular(root / "MEMORY.json", 1048576)
                        if any(
                            pin(data) != row[key]
                            for data, key in (
                                (raw, "provider_pin"),
                                (request, "request_pin"),
                                (memory, "memory_pin"),
                            )
                        ):
                            raise ValueError("retained evidence mismatch")
                        launch_raw = _read_regular(
                            root / "actor" / "RECEIPT.json", 1048576
                        )
                        launch, delivered = json.loads(launch_raw), json.loads(memory)
                        mode, strategy, _ = plan["arms"][arm]
                        request_id = ":".join((plan["cohort_id"], case["case_id"], arm))
                        if (
                            not verify_read_receipt(delivered)
                            or row["request_id"] != request_id
                            or launch["status"] != "EXECUTED"
                            or launch["actor_sha256"] != plan["actor"]["sha256"]
                            or launch["task"]
                            != pin(canonical_bytes(case["public_task"]))
                            or launch["mode"] != ("off" if mode == "off" else "on")
                            or launch["context_sha256"]
                            != delivered["receipt"]["context_sha256"]
                            or launch["context_bytes"]
                            != delivered["receipt"]["context_bytes"]
                            or any(
                                delivered["receipt"][key] != value
                                for key, value in {
                                    "session_id": request_id,
                                    "mode": mode,
                                    "strategy": strategy,
                                    "source_ids": [case["source_id"]],
                                    "replay_seed": case["replay_seed"],
                                    "limit": plan["limits"]["retrieval_records"],
                                    "max_context_bytes": plan["limits"][
                                        "context_bytes"
                                    ],
                                }.items()
                            )
                        ):
                            raise ValueError("actor, public task or memory arm changed")
                        provider = json.loads(raw)
                        directory = (
                            root
                            / "provider"
                            / hashlib.sha256(row["request_id"].encode()).hexdigest()
                        )
                        if (
                            _read_regular(directory / "RECEIPT.json", 1048576) != raw
                            or _read_regular(directory / "request.bin", 65536)
                            != request
                            or provider["profile"] != plan["profile"]
                            or provider["request_id"] != row["request_id"]
                            or provider["request"] != pin(request)
                            or provider["launch_sha256"] != pin(launch_raw)["sha256"]
                            or provider["status"] != "RETURNED"
                            or provider["provider_source"]
                            != plan["sources"][
                                "ndu_real_runtime/episodic_local_provider.py"
                            ]
                            or provider["worker"] != plan["provider_worker"]
                            or provider["local_generation_returned"] is not True
                        ):
                            raise ValueError(
                                "provider original does not match frozen request"
                            )
                        model_raw = _read_regular(
                            directory / "model-input.json", 1048576
                        )
                        if verify_returned_generation(
                            provider, _read_regular(directory / "combined.log", 1048576)
                        ) != model_raw or provider["model_input"] != pin(model_raw):
                            raise ValueError("actual model input record changed")
                        row["model_input_pin"] = pin(model_raw)
                        row["physical_generations"] = 1
                        row["correct"] = (
                            selected_text(provider["result"].get("text"))
                            == case["truth"]
                        )
                        row["selected_text"] = selected_text(
                            provider["result"].get("text")
                        )
                        row["prompt_tokens"] = provider["result"].get("prompt_tokens")
                        row["output_tokens"] = len(provider["result"].get("tokens", []))
                        row["provider_usage"] = {
                            key: provider["result"].get(key)
                            for key in (
                                "user_cpu_seconds",
                                "system_cpu_seconds",
                                "max_rss_kib",
                            )
                        }
                        row["memory_receipt"] = json.loads(memory)["receipt"]
            except (OSError, ValueError, KeyError, TypeError):
                row.update(
                    status="EVIDENCE_INVALID", correct=None, physical_generations=None
                )
            rows.append(row)
    panels, contrasts = {}, {}
    for arm in plan["arms"]:
        group = [row for row in rows if row["arm"] == arm]
        known = sum(row["correct"] is not None for row in group)
        successes = sum(row["correct"] is True for row in group)
        panels[arm] = {
            "planned": len(group),
            "scored": known,
            "successes": successes,
            "missing": len(group) - known,
            "statuses": dict(Counter(row["status"] for row in group)),
            "missing_label_rate_bounds": [
                successes / len(group),
                (successes + len(group) - known) / len(group),
            ],
        }
        if arm == "on_bm25":
            continue
        pairs = [
            (
                next(
                    row
                    for row in rows
                    if row["case_id"] == other["case_id"] and row["arm"] == "on_bm25"
                ),
                other,
            )
            for other in group
        ]
        lower = sum(
            (int(a["correct"]) if a["correct"] is not None else 0)
            - (int(b["correct"]) if b["correct"] is not None else 1)
            for a, b in pairs
        )
        upper = sum(
            (int(a["correct"]) if a["correct"] is not None else 1)
            - (int(b["correct"]) if b["correct"] is not None else 0)
            for a, b in pairs
        )
        contrasts[arm] = {
            "contrast": "on_bm25 minus " + arm,
            "planned_pairs": len(pairs),
            "missing_label_difference_bounds": [lower / len(pairs), upper / len(pairs)],
        }
    return {
        "schema": "hepta.mem12.controlled-diagnostic-report.v1",
        "protocol_sha256": plan_sha,
        "planned_rows": 80,
        "rows": rows,
        "writer_receipts": writers,
        "generated_sources": 8,
        "shared_task_templates": 1,
        "scored_controlled_rows": sum(row["correct"] is not None for row in rows),
        "panels": panels,
        "contrasts": contrasts,
        "known_returned_generations": sum(
            row["physical_generations"] == 1 for row in rows
        ),
        "unsettled_generation_rows": sum(
            row["physical_generations"] is None for row in rows
        ),
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "observer_authenticated": False,
        "native_owner_used": False,
        "natural_task_benefit_established": False,
        "parameter_consolidation_executed": False,
        "limitations": [
            "generated single-template tasks; no natural-source generalization",
            "deterministic A writer; new fixed text parser, not MEM5 public selector",
            "research SQLite forks are not native owner recovery",
            "same limits do not mean identical actual token or setup cost",
            "missing-label bounds are not confidence intervals; no adoption threshold",
            "energy, external effect recovery and original owner authentication unavailable",
        ],
    }
