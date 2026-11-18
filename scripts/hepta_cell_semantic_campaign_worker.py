#!/usr/bin/env python3
"""Execute the separately versioned semantic campaign through a frozen runtime."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from hepta_cell_campaign_worker import write_new, write_raw
from hepta_cell_joint_worker import load_candidate, sha, strict_json
from hepta_cells.maintenance_cycle import run
from hepta_cells.maintenance_metrics import Measurement


def execute(candidate, output, request, *, with_updates=False):
    if (
        type(request) is not dict
        or set(request) != {"request_id", "cell_id", "operation", "payload"}
        or type(request["request_id"]) is not str
        or not 0 < len(request["request_id"].encode()) <= 256
        or request["cell_id"] != "MEM+PRED"
        or request["operation"] != "semantic_maintenance"
        or request["payload"] != {}
    ):
        raise ValueError("one exact semantic-maintenance request is required")
    value, candidate_hash, roots, native = load_candidate(candidate)
    native.close()
    pins = value.get("runtime_identity")
    if (
        not isinstance(pins, dict)
        or not {"source_commit", "source_tree", "binary_sha256", "config_sha256"}
        <= pins.keys()
        or pins["source_commit"] != value["source_bases"]["runtime"]
    ):
        raise ValueError("semantic maintenance requires the frozen runtime identity")
    output = output.resolve()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    write_new(output / "REQUEST.json", request)
    candidate_raw = Path(candidate).read_bytes()
    if hashlib.sha256(candidate_raw).hexdigest() != candidate_hash:
        raise ValueError("candidate changed after admission")
    write_raw(output / "OUTER_CANDIDATE.json", candidate_raw)
    write_new(
        output / "RUNTIME_PINS.json",
        {**pins, "origin_candidate_sha256": candidate_hash},
    )
    build_raw = (roots["artifacts"] / "native/build.json").read_bytes()
    build_hash = hashlib.sha256(build_raw).hexdigest()
    expected = next(
        row["sha256"]
        for row in value["files"]
        if row["root"] == "artifacts" and row["path"] == "native/build.json"
    )
    if build_hash != expected:
        raise ValueError("original build changed after admission")
    write_raw(output / "ORIGINAL_BUILD.json", build_raw)
    write_new(
        output / "RELOCATED_BUILD.json",
        {
            **strict_json(build_raw),
            "hepta_root": str(roots["hia"]),
            "image_path": str(roots["artifacts"] / value["native"]["image"]),
            "original_build_record_sha256": build_hash,
            "relocation_scope": "paths only; original compiler/source/image identities retained",
        },
    )
    with Measurement(
        "semantic_campaign", "runtime_semantic_worker.campaign"
    ) as campaign_cost:
        result = run(
            output / "campaign",
            native_build_record=output / "RELOCATED_BUILD.json",
            runtime_pins=output / "RUNTIME_PINS.json",
            semantic=True,
        )
    updates = None
    if with_updates:
        from qualify_cell_updates import run as run_updates

        updates = run_updates(
            output / "updates",
            output / "RELOCATED_BUILD.json",
            output / "campaign/RESULT.json",
        )
    _, observed_candidate, _, checked_native = load_candidate(candidate)
    checked_native.close()
    if observed_candidate != candidate_hash:
        raise ValueError("outer candidate changed during semantic maintenance")
    counts = {}
    for cell in ("memory", "predictor"):
        database = output / "campaign" / cell / "owner.sqlite"
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            counts[cell] = dict(
                connection.execute(
                    "SELECT phase,COUNT(*) FROM hia_cell_calls GROUP BY phase"
                ).fetchall()
            )
        finally:
            connection.close()
        if set(counts[cell]) != {"completed"}:
            raise ValueError("semantic campaign left a nonterminal native continuation")
    observed = dict(
        schema="hepta.runtime-semantic-maintenance-observation.v1",
        status="campaign_observed",
        request_id=request["request_id"],
        candidate_sha256=candidate_hash,
        runtime_identity=pins,
        native_image_sha256=value["native"]["image_sha256"],
        native_counts=counts,
        campaign_result_sha256=sha(output / "campaign/RESULT.json"),
        campaign_result=result,
        campaign_cost=campaign_cost.result,
        claims=dict(
            transport_requires_outer_owner_evidence=True,
            ordinary_daemon_qualification=False,
            independent_real_task_benefit=False,
        ),
    )
    if updates is not None:
        updates_plan = strict_json((output / "updates/PLAN.json").read_bytes())
        observed.update(
            updates=updates,
            updates_result_sha256=sha(output / "updates/RESULT.json"),
            updates_native_image_sha256=updates_plan["native"]["image_sha256"],
        )
    write_new(output / "OBSERVATION.json", observed)
    return observed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-updates", action="store_true")
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(65537)
    if len(raw) > 65536:
        raise ValueError("request exceeds bound")
    print(
        json.dumps(
            execute(
                args.candidate,
                args.output,
                strict_json(raw),
                with_updates=args.with_updates,
            ),
            sort_keys=True,
            allow_nan=False,
        )
    )
