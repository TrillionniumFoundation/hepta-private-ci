"""Score the frozen cross-runner mechanism, keeping recall quality separate."""

import argparse
import hashlib
from pathlib import Path

from artifact_relay import await_artifact
from relay_protocol import PROTOCOL, read, retain


def signature(rows):
    return [
        {key: row[key] for key in ("text", "token_ids", "prompt_sha256")}
        for row in rows
    ]


def inventory(root):
    result = []
    for path in sorted(Path(root).rglob("*")):
        if path.is_symlink():
            raise ValueError("evidence inventory cannot contain symlinks")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            result.append(
                dict(
                    path=str(path.relative_to(root)),
                    bytes=path.stat().st_size,
                    sha256=digest.hexdigest(),
                )
            )
    return dict(
        files=result,
        physical_file_bytes=sum(item["bytes"] for item in result),
        content_unique_bytes=sum(
            {item["sha256"]: item["bytes"] for item in result}.values()
        ),
        symlinks_followed=False,
    )


def evaluate(root, model):
    finished = read(await_artifact("finished", root / "in-finished"))
    source = read(root / "source-identity.json")
    ready = read(root / "in-ready" / "ready.json")
    facts = read(root / "source-facts.json")["facts"]
    source_rows = read(root / "source-adapter.json")["journal"]["rows"]
    target_rows = ready["raw_rows"]
    old = read(root / "source-old-placement-refusal.json")
    expected_calls = PROTOCOL["load_requests"] + 1
    checks = dict(
        distinct_runner_boots=source["boot_id_sha256"]
        != ready["identity"]["boot_id_sha256"],
        distinct_jobs=source["job"] != ready["identity"]["job"],
        exact_checkpoint=read(root / "source-install.json")["manifest_sha256"]
        == ready["manifest_sha256"],
        raw_outputs_preserved=signature(source_rows) == signature(target_rows),
        old_placement_blocked=old["rejected"]
        and old["callbacks_before"] == old["callbacks_after"],
        withdrawal_no_model=finished["withdrawal"]["callbacks_before"]
        == finished["withdrawal"]["callbacks_after"]
        == expected_calls,
        restart_replay_no_model=finished["restart_replay"]["callbacks_before"]
        == finished["restart_replay"]["callbacks_after"]
        == expected_calls,
        source_database_not_transferred=ready["source_database_present"] is False
        and finished["source_database_present"] is False,
        delayed_evidence_refused=finished["evidence"]["current_support_accepted"]
        is False,
        load_completed=ready["load"]["requests"] == PROTOCOL["load_requests"],
    )
    accuracy = {}
    for control in ("adapter", "base", "shuffled"):
        journal = read(root / f"source-{control}.json")["journal"]
        if len(journal["rows"]) != 3 or any(
            journal[key] is not False
            for key in ("fact_input", "retrieval_input", "answer_lexicon_input")
        ):
            raise ValueError("source-only model input contract changed")
        accuracy[control] = dict(
            correct=sum(
                row["text"].strip() == fact["value"]
                for row, fact in zip(journal["rows"], facts, strict=True)
            ),
            total=3,
        )
    accuracy["target_adapter"] = dict(
        correct=sum(
            row["text"].strip() == fact["value"]
            for row, fact in zip(target_rows, facts, strict=True)
        ),
        total=3,
    )
    accuracy["target_load"] = dict(
        correct=sum(
            row["raw_row"]["text"].strip() == facts[row["question_index"]]["value"]
            for row in ready["load"]["rows"]
        ),
        total=PROTOCOL["load_requests"],
    )
    retain(
        root / "file-inventory.json",
        dict(
            source_evidence=inventory(root),
            source_base=inventory(model),
            target_base_copies_required=1,
            base_shared_between_runners=False,
            full_target_inventory_in_separate_artifact=True,
        ),
    )
    report = dict(
        protocol=PROTOCOL,
        checks=checks,
        mechanism_passed=all(checks.values()),
        raw_accuracy=accuracy,
        cold_worker_load={k: v for k, v in ready["load"].items() if k != "rows"},
        source_identity=source,
        target_identity=ready["identity"],
        independent_runner_environments=2,
        physical_hardware_attested=False,
        authority_mode="single source signer, asynchronous artifact relay",
        replicated_authority_exercised_in_this_trial=False,
        direct_cross_host_mtls=False,
        general_memory_blocker_closed=False,
    )
    retain(root / "report.json", report)
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--inventory-only", action="store_true")
    args = parser.parse_args()
    if args.inventory_only:
        retain(
            args.root / "file-inventory.json",
            dict(
                target_evidence=inventory(args.root), target_base=inventory(args.model)
            ),
        )
    else:
        raise SystemExit(evaluate(args.root, args.model))
