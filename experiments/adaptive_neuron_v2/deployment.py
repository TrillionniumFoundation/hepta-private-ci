"""Run and independently replay the complete registered native-owner batch."""

import argparse
import json
from pathlib import Path

from .ledger import measured_stage, sha, write_json_exclusive
from .provenance import verify
from .roster import expected_roster, full_profile, protocol, verify_roster


def fitted_inputs(training, expected, source, learning_audit):
    index = json.loads((training / "INDEX.json").read_text())
    if (
        not index["complete"]
        or index["phase"] != "confirmation"
        or index["source"] != source
    ):
        raise ValueError("registered completed confirmation training required")
    keys = [(row["seed"], row["arm"]) for row in index["fits"]]
    wanted = [
        (seed, arm)
        for seed in protocol()["confirmation_seeds"]
        for arm in protocol()["training"]["arms"]
    ]
    if keys != wanted:
        raise ValueError(
            "training fit roster differs from the registered three-arm study"
        )
    audited = json.loads(Path(learning_audit).read_text())
    if (
        audited.get("schema") != "hepta.adaptive-neuron.learning-audit.v2"
        or audited.get("phase") != "confirmation"
        or audited.get("source") != source
        or audited.get("training_index_sha256") != sha(training / "INDEX.json")
        or any(
            audited.get(key) is not True
            for key in (
                "passed",
                "shared_causal_schedule_verified",
                "optimizer_and_history_verified",
                "deployed_models_rebuilt_from_checkpoints",
                "raw_files_unchanged",
            )
        )
    ):
        raise ValueError(
            "independent learning audit must bind the exact training index"
        )
    records = audited["fit_records"]
    if [(row["seed"], row["arm"]) for row in records] != wanted or audited[
        "fits_verified"
    ] != len(wanted):
        raise ValueError("learning audit has an incomplete or unregistered fit roster")
    if any(
        a["checkpoint_sha256"] != b["checkpoint_sha256"]
        for a, b in zip(records, index["fits"], strict=True)
    ):
        raise ValueError("learning audit verified another checkpoint")
    models = {}
    for row in index["fits"]:
        directory = training / row["directory"]
        checkpoint, neural = directory / "checkpoint.json", directory / "neural.json"
        if (
            sha(checkpoint) != row["checkpoint_sha256"]
            or sha(neural) != row["neural_sha256"]
        ):
            raise ValueError("deployed task-trained checkpoint identity changed")
        payload = json.loads(checkpoint.read_text())
        if (payload["seed"], payload["arm"]) != (row["seed"], row["arm"]):
            raise ValueError("checkpoint declares a different training identity")
        models[row["seed"], row["arm"]] = (checkpoint, neural)
    if any((row["seed"], row["training_arm"]) not in models for row in expected):
        raise ValueError("missing trained model required by deployment")
    return models


def run_batch(
    binary, training, destination, source_seal, build_receipt, learning_audit
):
    from .owner.run import run_organ

    destination, training = Path(destination), Path(training)
    with measured_stage(
        destination,
        identity={"stage": "native_deployment"},
        scope="Source verification, roster and profile creation, all native executions, Python reference checks, retries, hashes and summary publication.",
    ) as cost:
        source, config = verify(source_seal), protocol()
        expected = expected_roster(config)
        models = fitted_inputs(training, expected, source, learning_audit)
        (destination / "organs").mkdir()
        rows = []
        for specification in expected:
            checkpoint, neural = models[
                specification["seed"], specification["training_arm"]
            ]
            profile = (
                destination
                / "profiles"
                / f"seed{specification['seed']}.{specification['training_arm']}.json"
            )
            payload = full_profile(json.loads(neural.read_text()), config)
            if profile.exists():
                if json.loads(profile.read_text()) != payload:
                    raise ValueError("shared profile changed during execution")
            else:
                write_json_exclusive(profile, payload)
            plan = specification["plan"]
            root = destination / "organs" / specification["organ"]
            result = run_organ(
                binary,
                root,
                plan["organ"],
                profile,
                checkpoint,
                plan["policy"],
                plan["episodes"],
                source_seal=source_seal,
                build_receipt=build_receipt,
            )
            row = {key: value for key, value in specification.items() if key != "plan"}
            row.update(
                index_sha256=sha(root / "INDEX.json"),
                episode_count=len(result["episodes"]),
            )
            rows.append(row)
            print(
                json.dumps(
                    {
                        "organ": row["organ"],
                        "completed": len(rows),
                        "expected": len(expected),
                    }
                ),
                flush=True,
            )
        verify_roster(rows, expected)
        if verify(source_seal) != source:
            raise ValueError("source identity changed during deployment")
        result = {
            "schema": "hepta.adaptive-neuron.deployment-index.v2",
            "complete": True,
            "source": source,
            "training_index_sha256": sha(training / "INDEX.json"),
            "learning_audit_sha256": sha(learning_audit),
            "binary_sha256": sha(binary),
            "build_receipt_sha256": sha(build_receipt),
            "organs": rows,
        }
        write_json_exclusive(destination / "INDEX.json", result)
        cost.update(
            organs=len(rows),
            episodes=sum(row["episode_count"] for row in rows),
            index_sha256=sha(destination / "INDEX.json"),
        )
    return result


def audit_batch(binary, training, root, destination, source_seal, learning_audit):
    from .owner.audit import audit_organ

    root, destination, training = Path(root), Path(destination), Path(training)
    with measured_stage(
        destination,
        identity={"stage": "native_independent_audit"},
        scope="Independent expected roster and model reconstruction, every episode Python validation and native cold replay, immutable raw checks, and complete audit publication.",
    ) as cost:
        source, config = verify(source_seal), protocol()
        expected = expected_roster(config)
        models = fitted_inputs(training, expected, source, learning_audit)
        index = json.loads((root / "INDEX.json").read_text())
        if (
            not index["complete"]
            or index["source"] != source
            or index["binary_sha256"] != sha(binary)
        ):
            raise ValueError("native run identity mismatch")
        if index["training_index_sha256"] != sha(training / "INDEX.json"):
            raise ValueError("deployment used another training batch")
        if index["learning_audit_sha256"] != sha(learning_audit):
            raise ValueError("deployment used another independent learning audit")
        verify_roster(index["organs"], expected)
        if sorted(path.name for path in (root / "organs").iterdir()) != sorted(
            row["organ"] for row in expected
        ):
            raise ValueError("unregistered or missing raw organ directory")
        rows = []
        for row, specification in zip(index["organs"], expected, strict=True):
            organ = root / "organs" / row["organ"]
            checkpoint, neural = models[row["seed"], row["training_arm"]]
            if sha(organ / "INDEX.json") != row["index_sha256"] or sha(
                organ / "TRAINED_CHECKPOINT.json"
            ) != sha(checkpoint):
                raise ValueError(
                    "organ result or deployed checkpoint identity mismatch"
                )
            if json.loads((organ / "MODEL.json").read_text()) != full_profile(
                json.loads(neural.read_text()), config
            ):
                raise ValueError(
                    "native profile changed the frozen model or credit contract"
                )
            audit_path = destination / "organs" / f"{row['organ']}.json"
            audit_path.parent.mkdir(exist_ok=True)
            result = audit_organ(
                binary,
                organ,
                source_seal=source_seal,
                expected_plan=specification["plan"],
                output=audit_path,
            )
            if (
                not result["passed"]
                or result["episodes_verified"]
                != config["deployment"]["episodes_per_organ"]
            ):
                raise ValueError("partial native audit cannot pass")
            rows.append(
                {
                    **row,
                    "audit_sha256": sha(audit_path),
                    "raw_bytes_unchanged": result["raw_bytes_unchanged"],
                }
            )
            print(
                json.dumps(
                    {
                        "audit": row["organ"],
                        "completed": len(rows),
                        "expected": len(expected),
                    }
                ),
                flush=True,
            )
        if verify(source_seal) != source:
            raise ValueError("source identity changed during the native audit")
        result = {
            "schema": "hepta.adaptive-neuron.deployment-audit.v2",
            "passed": True,
            "source": source,
            "learning_audit_sha256": sha(learning_audit),
            "deployment_index_sha256": sha(root / "INDEX.json"),
            "organs": rows,
        }
        write_json_exclusive(destination / "INDEX.json", result)
        cost.update(
            organs=len(rows),
            episodes=sum(row["episode_count"] for row in rows),
            index_sha256=sha(destination / "INDEX.json"),
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "audit"))
    for name in (
        "binary",
        "training",
        "learning-audit",
        "destination",
        "source-seal",
        "build-receipt",
        "root",
    ):
        parser.add_argument(
            "--" + name, type=Path, required=name not in ("build-receipt", "root")
        )
    args = parser.parse_args()
    if args.command == "run":
        if args.build_receipt is None:
            parser.error("run requires --build-receipt")
        run_batch(
            args.binary,
            args.training,
            args.destination,
            args.source_seal,
            args.build_receipt,
            args.learning_audit,
        )
    else:
        if args.root is None:
            parser.error("audit requires --root")
        audit_batch(
            args.binary,
            args.training,
            args.root,
            args.destination,
            args.source_seal,
            args.learning_audit,
        )


if __name__ == "__main__":
    main()
