"""Build declared development maintenance tasks from pinned repository JSON."""

import argparse
import hashlib
import json
from pathlib import Path
import time

from . import data


def _compute(operation, payload):
    if operation == "sum_counts":
        return {"total": sum(payload["counts"])}
    if operation == "count_confirmed":
        return {"confirmed": sum(value is True for value in payload["flags"])}
    if operation == "strict_benefit":
        return {"adopt": payload["candidate"] > max(payload["controls"])}
    if operation == "all_commands_succeeded":
        return {
            "all_successful": bool(payload["exit_codes"])
            and all(code == 0 for code in payload["exit_codes"])
        }
    if operation == "audit_complete":
        return {
            "complete": payload["passed"] == payload["total"]
            and not payload["failures"],
            "failed": len(payload["failures"]),
        }
    if operation == "bundle_unverified":
        return {"unverified": payload["files"] - payload["verified_member_hashes"]}
    if operation == "ci_terminal_pass":
        return {
            "ci_pass": payload["last_observed_status"] == "success"
            and payload["counted_as_pass"] is True
        }
    if operation == "adapter_scale":
        from fractions import Fraction

        scale = Fraction(*payload["alpha"]) / payload["rank"]
        return {"numerator": scale.numerator, "denominator": scale.denominator}
    if operation == "attention_dimensions":
        dim, remainder = divmod(payload["hidden"], payload["attention_heads"])
        if remainder:
            raise ValueError("hidden dimension is not divisible by head count")
        return {"head_dim": dim, "kv_dim": dim * payload["kv_heads"]}
    if operation == "context_budget":
        total = payload["input_tokens_max"] + payload["output_tokens_max"]
        return {"total_tokens": total, "within_context": total <= payload["context"]}
    raise ValueError("unsupported deterministic development operation")


def oracle_answer(record):
    """Strong rule baseline uses model-visible input only, never expected labels."""
    value = json.loads(record["task"]["input"])
    return data.canonical(
        _compute(value["operation"], value["source_excerpt"])
    ).decode()


def build(source_cache, output):
    cache, output = Path(source_cache), Path(output)
    retrieval = json.loads((cache / "retrieval.json").read_bytes())
    sources, bodies = {}, {}
    for item in retrieval["sources"]:
        path = cache / item["file"]
        if Path(item["file"]).name != item["file"]:
            raise ValueError("source cache requires plain filenames")
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if (
            hashlib.sha256(raw).hexdigest() != item["sha256"]
            or blob != item["git_blob"]
        ):
            raise ValueError("pinned source bytes changed")
        sources[item["key"]], bodies[item["key"]] = item, json.loads(raw)
    actual, gates, stem, chain = (
        bodies[key]
        for key in ("hepta_actual", "hepta_gates", "hepta_stem", "chain_family")
    )
    tasks = []

    def add(source, split, family, operation, payload, pointer, instruction):
        tasks.append((source, split, family, operation, payload, pointer, instruction))

    cells = actual["campaign_result"]["cells"]
    add(
        "hepta_actual",
        "train",
        "joint-counter-sum",
        "sum_counts",
        {"counts": [v["completed"] for v in actual["native_counts"].values()]},
        "/native_counts/*/completed",
        'Sum counts. Return {"total":integer}.',
    )
    add(
        "hepta_actual",
        "train",
        "joint-counter-sum",
        "sum_counts",
        {"counts": [v["training"]["validated_updates"] for v in cells.values()]},
        "/campaign_result/cells/*/training/validated_updates",
        'Sum updates. Return {"total":integer}.',
    )
    add(
        "hepta_actual",
        "train",
        "joint-confirmed-count",
        "count_confirmed",
        {"flags": [v["cold_runtime_reobserved"] for v in actual["completed_requests"]]},
        "/completed_requests/*/cold_runtime_reobserved",
        'Count true flags. Return {"confirmed":integer}.',
    )
    add(
        "hepta_actual",
        "train",
        "joint-confirmed-count",
        "count_confirmed",
        {"flags": [v["local_no_update_complete"] for v in cells.values()]},
        "/campaign_result/cells/*/local_no_update_complete",
        'Count true flags. Return {"confirmed":integer}.',
    )
    for name, cell in cells.items():
        successes = cell["decision"]["B_successes"]
        add(
            "hepta_actual",
            "train",
            "joint-strict-benefit",
            "strict_benefit",
            {
                "candidate": successes["candidate"],
                "controls": [v for k, v in successes.items() if k != "candidate"],
            },
            f"/campaign_result/cells/{name}/decision/B_successes",
            'Adopt only if candidate strictly exceeds every control. Return {"adopt":boolean}.',
        )
    saturated = gates["adoption_gate_saturation"]
    add(
        "hepta_gates",
        "train",
        "joint-strict-benefit",
        "strict_benefit",
        {
            "candidate": saturated["maximum_candidate_successes"],
            "controls": [saturated["deterministic_B_successes"]],
        },
        "/adoption_gate_saturation",
        'Can even the maximum strictly exceed the control? Return {"adopt":boolean}.',
    )
    add(
        "hepta_stem",
        "selection",
        "stem-command-completion",
        "all_commands_succeeded",
        {"exit_codes": stem["commands"]["exit_codes"]},
        "/commands/exit_codes",
        'All commands succeed only if every exit code is zero. Return {"all_successful":boolean}.',
    )
    add(
        "hepta_stem",
        "selection",
        "stem-audit-accounting",
        "audit_complete",
        stem["audit"]["checks"],
        "/audit/checks",
        'Audit complete requires passed=total and no failures. Return {"complete":boolean,"failed":integer}.',
    )
    add(
        "hepta_stem",
        "selection",
        "stem-bundle-coverage",
        "bundle_unverified",
        {
            k: stem["private_evidence_bundle"][k]
            for k in ("files", "verified_member_hashes")
        },
        "/private_evidence_bundle",
        'Subtract verified members from files. Return {"unverified":integer}.',
    )
    add(
        "hepta_stem",
        "selection",
        "stem-ci-terminal-status",
        "ci_terminal_pass",
        stem["hosted_ci"],
        "/hosted_ci",
        'CI pass requires success status and counted_as_pass=true. Return {"ci_pass":boolean}.',
    )
    add(
        "chain_family",
        "confirmation",
        "chain-lora-scale",
        "adapter_scale",
        {k: chain["adapter"][k] for k in ("alpha", "rank")},
        "/adapter",
        'Compute alpha[0]/alpha[1]/rank as a reduced fraction. Return {"numerator":integer,"denominator":integer}.',
    )
    add(
        "chain_family",
        "confirmation",
        "chain-attention-shape",
        "attention_dimensions",
        {
            k: chain["architecture"][k]
            for k in ("hidden", "attention_heads", "kv_heads")
        },
        "/architecture",
        'head_dim=hidden/attention_heads; kv_dim=head_dim*kv_heads. Return {"head_dim":integer,"kv_dim":integer}.',
    )
    add(
        "chain_family",
        "confirmation",
        "chain-context-capacity",
        "context_budget",
        {
            **{
                k: chain["numeric_profile"][k]
                for k in ("input_tokens_max", "output_tokens_max")
            },
            "context": chain["architecture"]["context"],
        },
        "/numeric_profile + /architecture/context",
        'total_tokens=input+output; within_context means total<=context. Return {"total_tokens":integer,"within_context":boolean}.',
    )
    now, records, receipts = int(time.time()), [], []
    for index, (
        source_key,
        split,
        family,
        operation,
        payload,
        pointer,
        instruction,
    ) in enumerate(tasks):
        source = sources[source_key]
        task_id = f"repo-maintenance-{index:02d}"
        item = {
            "schema": data.SCHEMA,
            "record_id": task_id,
            "task_id": task_id,
            "source_id": source["sha256"],
            "lineage_id": "joint-hia-20261116"
            if source_key.startswith("hepta_") and source_key != "hepta_stem"
            else source_key,
            "family_id": family,
            "project_id": source["repository"],
            "source": {
                k: source[k]
                for k in ("repository", "revision", "path", "sha256", "git_blob", "url")
            },
            "observed_at": now,
            "available_at": now,
            "split": split,
            "origin_kind": "curated_development",
            "exposure": "development",
            "teacher_id": None,
            "authorization": {
                "training_allowed": split == "train",
                "evaluation_allowed": True,
                "rights_basis": "User authorized this repository experiment in this session",
                "scope": "Local experimental training and semantic artifact evaluation; no deployment",
            },
            "source_projection": {
                "pointer": pointer,
                "payload_sha256": data.digest(payload),
            },
            "task": {
                "input": data.canonical(
                    {
                        "instruction": instruction,
                        "operation": operation,
                        "source_excerpt": payload,
                    }
                ).decode(),
                "verifier": {
                    "name": "json_artifact",
                    "version": "1",
                    "parameters": {"expected": _compute(operation, payload)},
                },
            },
            "final_answer": data.canonical(_compute(operation, payload)).decode(),
            "trajectory": [
                {
                    "index": 0,
                    "actor": "environment",
                    "kind": "observation",
                    "content": data.canonical(payload).decode(),
                    "executed": False,
                    "receipt_sha256": source["sha256"],
                },
                {
                    "index": 1,
                    "actor": "curator",
                    "kind": "action",
                    "content": instruction,
                    "executed": False,
                    "receipt_sha256": None,
                },
            ],
        }
        receipt = data.verify_answer(item, oracle_answer(item))
        item["verified_outcome"] = {
            "success": receipt["success"],
            "receipt_sha256": receipt["receipt_sha256"],
            "verifier_name": "json_artifact",
            "verifier_version": "1",
        }
        records.append(item)
        receipts.append(receipt)
    admission = data.validate_records(records)
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in [("all", records)] + [
        (split, [r for r in records if r["split"] == split]) for split in data.SPLITS
    ]:
        (output / (name + ".jsonl")).write_bytes(
            b"".join(data.canonical(row) + b"\n" for row in rows)
        )
    (output / "oracle-receipts.json").write_bytes(data.canonical(receipts) + b"\n")
    manifest = {
        "schema": "hepta.cell-experiments.development-build.v1",
        "admission": admission,
        "observed_at": now,
        "source_cache_sha256": data.digest(retrieval),
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "external_teacher_runs": 0,
        "independent_confirmation_sources": 0,
        "scope": "New authored maintenance tasks on real repository artifacts; not autonomous code repair",
        "oracle_uses_model_visible_input_only": True,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
        },
    }
    (output / "manifest.json").write_bytes(data.canonical(manifest) + b"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source_cache, args.output), indent=2))
