"""Run the trained exact owner through a signed terminal-credit admission gate."""

import argparse
import json
import os
from pathlib import Path
import shutil

from experiments.adaptive_neuron_v2.ledger import (
    measured_stage,
    sha,
    write_json_exclusive as write,
)
from experiments.adaptive_neuron_v2.owner.build import verify_build
from experiments.adaptive_neuron_v2.owner.common import (
    charge,
    digest,
    encoder_proof,
    open_request,
    permit,
)
from experiments.adaptive_neuron_v2.owner.reference import Reference, compare
from experiments.adaptive_neuron_v2.owner.run import verify_checkpoint
from experiments.adaptive_neuron_v2.provenance import verify
from experiments.adaptive_neuron_v2.roster import episode_plan, full_profile, protocol
from experiments.free_boundary_neuron.owner.common import canonical

from .gate import CreditGate
from .negative import corrupt_closure, corrupt_settlement, reject
from .provenance import verify_source
from .transport import LoggedProcess, file_manifest, load_rpc

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FAULTS = {
    0: "observer_signature",
    1: "stale_head",
    2: "credit_signature",
    3: "expired",
    4: "closure_acknowledgement_loss",
    5: "settlement_acknowledgement_loss",
}
ADAPTER_FAULTS = {
    6: "cross_episode_valid_closure",
    7: "changed_terminal_binding",
    8: "resource_record_digest",
    9: "settlement_outcome_binding",
    10: "cross_episode_valid_admission",
}


def source_closure(build_receipt):
    source = dict(build_receipt["source_sha256"])
    source.update(
        (str(p.relative_to(ROOT)), sha(p))
        for p in HERE.iterdir()
        if p.suffix in {".py", ".rs"}
    )
    for name in ("PROTOCOL.json", "requirements.txt"):
        source[str((HERE / name).relative_to(ROOT))] = sha(HERE / name)
    return source


def verify_bridge(build_path, binary, protected):
    receipt = json.loads(Path(build_path).read_text())
    if (
        receipt["protected_v2"] != protected
        or receipt["binary_sha256"] != sha(binary)
        or receipt["binary_bytes"] != Path(binary).stat().st_size
        or receipt["qualified_legacy_write_enabled"]
        or not receipt["production_crates_unmodified"]
        or not receipt["outcome_adapter_unmodified"]
    ):
        raise ValueError("Signed bridge build identity differs")
    for name, value in receipt["source_sha256"].items():
        if sha(ROOT / name) != value:
            raise ValueError("Bridge source differs from its built executable: " + name)
    return receipt


def episode(root, inputs, specification, ordinal, head):
    case, organ = specification["case"], "research.signed-credit.seed601"
    context = tuple(specification["context"])
    model, calibration = root / "MODEL.json", root / "CALIBRATION.json"
    policy = {"readout": "snn", "credit": "live"}
    request = open_request(
        case,
        organ,
        model,
        calibration,
        policy,
        context,
        specification["budget"],
        account_sequence=ordinal,
    )
    records = root / "rpc" / case
    records.mkdir(parents=True)
    gate = CreditGate(root / "GATE.jsonl")
    gate.require_next()
    processes = []

    def start(kind):
        process = LoggedProcess(
            inputs[kind + "_binary"],
            root / kind,
            records,
            f"{kind}.{len(processes):03d}",
        )
        processes.append(process)
        return process

    owner, signed = start("owner"), start("signed")
    outputs, checks = [], []
    try:
        opened = owner.call({"command": "Open", "request": request})
        reference = Reference(
            json.loads(model.read_text()),
            context,
            policy,
            opened["status"]["initial_account"],
        )
        binding = {
            "case": case,
            "organ": organ,
            "model_sha256": sha(model),
            "checkpoint_sha256": sha(root / "TRAINED_CHECKPOINT.json"),
            "owner_binary_sha256": inputs["owner_binary_sha256"],
        }
        admission = {
            **binding,
            "context": context,
            "budget": specification["budget"],
            "initial_account": reference.initial,
            "admission": "execute-trained-readout",
            "future_evidence_included": False,
        }
        gate.append(
            "opened",
            case,
            {
                "request": request,
                "status": opened["status"],
                "binding": binding,
                "admission_support_json": canonical(admission).decode(),
            },
        )
        if ordinal == 10:
            previous = json.loads(
                (root / "episodes/research.case.0000.json").read_text()
            )
            reject(
                root, gate, "admitted", previous["admission"], ADAPTER_FAULTS[ordinal]
            )
            checks.append(ADAPTER_FAULTS[ordinal])
        decision = signed.call(
            {
                "command": "Decision",
                "case": case,
                "organ": organ,
                "expected_head": head,
                "support_json": canonical(admission).decode(),
            }
        )
        gate.append("admitted", case, decision)
        if decision["new_signed_facts"] != 1:
            raise AssertionError(
                "New episode did not create exactly one signed decision"
            )
        for index, value in enumerate(specification["observations"]):
            gate.require_observation()
            observation = {
                "event_id": f"observation.{index}",
                "value": value,
                "elapsed": index + 1,
                "evidence_digest": digest(
                    [
                        "adaptive-neuron.causal-observation.v2",
                        specification["stream_id"],
                        index,
                        value,
                    ]
                ),
            }
            output = owner.call({"command": "Observe", "observation": observation})
            compare(output["readout"], reference.observe(value))
            outputs.append(output)
            if output["terminal"]:
                break
        else:
            raise AssertionError("The exact native owner failed to terminate")
        terminal = owner.call({"command": "Status"})
        action = "abstain" if output["native_abstain"] else output["readout"]["action"]
        selected = {"positive": 1, "negative": -1, "abstain": 0}[action]
        reward = float(selected * specification["truth"]) if selected else 0.05
        outcome_digest = digest(
            [
                "adaptive-neuron.observed-outcome.v2",
                specification["stream_id"],
                specification["truth"],
                selected,
                reward,
            ]
        )
        support = {
            **binding,
            "terminal_checkpoint": terminal["checkpoint"],
            "outcome_digest": outcome_digest,
            "reward": reward,
            "native_terminal": True,
            "terminal_status": terminal,
            "actual_resource_work": reference.work,
            "signed_admission_chain": decision["decision"]["chain_digest"],
            "observations_consumed": len(outputs),
        }
        closure_request = {
            "command": "Closure",
            **{
                key: support[key]
                for key in (
                    "case",
                    "organ",
                    "terminal_checkpoint",
                    "outcome_digest",
                    "reward",
                )
            },
            "expected_head": decision["decision"]["chain_digest"],
            "support_json": canonical(support).decode(),
            "fault": "none",
        }
        gate.append("terminal", case, {**support, "closure_request": closure_request})
        write(
            root / "terminal" / f"{case}.json",
            {
                "support": support,
                "closure_request": closure_request,
                "owner_request": request,
                "specification": specification,
            },
        )
        fault = FAULTS.get(ordinal)
        if fault in {"observer_signature", "stale_head", "credit_signature", "expired"}:
            account_before = file_manifest(root / "owner")
            rejected = signed.call({**closure_request, "fault": fault})
            gate.append("closure_rejected", case, rejected)
            expected_facts = 1 if fault == "credit_signature" else 0
            if rejected["new_signed_facts"] != expected_facts:
                raise AssertionError(
                    "Rejected closure produced unauthorized signed facts"
                )
            # The gate must reject before it can send Settle to the original API.
            for operation in (gate.require_next, lambda: gate.settle(owner)):
                try:
                    operation()
                except PermissionError:
                    checks.append("adapter_denied_unsigned_transition")
                else:
                    raise AssertionError("Rejected closure admitted future work")
            if file_manifest(root / "owner") != account_before:
                raise AssertionError(
                    "Refused signed closure changed original owner files"
                )
            if owner.call({"command": "Status"}) != terminal:
                raise AssertionError(
                    "Failed signature changed terminal SNN/owner state"
                )
            # The unchanged owner independently retains its active reservation.
            probe = start("owner")
            probe.call(
                {
                    "command": "Open",
                    "request": {
                        **request,
                        "case": case + ".blocked",
                        "expected_account_sequence": ordinal,
                    },
                },
                expect_error=True,
            )
            probe.close()
            checks.append("original_owner_blocks_next_episode")
            signed.close()
            owner.call({"command": "Close"})
            owner.close()
            owner, signed = start("owner"), start("signed")
            if (
                owner.call({"command": "Resume", "request": request})["status"]
                != terminal
            ):
                raise AssertionError(
                    "Cold rejection recovery changed the terminal state"
                )
            gate = CreditGate(root / "GATE.jsonl")
            checks.append("rejected_terminal_cold_recovered")
        accepted = signed.call(closure_request)
        if fault == "credit_signature" and (
            accepted["outcome"]["disposition"] != "IdempotentReplay"
            or accepted["credit"]["disposition"] != "Appended"
        ):
            raise AssertionError(
                "Partial signed closure did not reconcile idempotently"
            )
        if fault == "closure_acknowledgement_loss":
            signed.close()
            owner.call({"command": "Close"})
            owner.close()
            owner, signed = start("owner"), start("signed")
            owner.call({"command": "Resume", "request": request})
            gate = CreditGate(root / "GATE.jsonl")
            if gate.phase != "terminal":
                raise AssertionError(
                    "Unacknowledged closure incorrectly advanced adapter"
                )
            accepted = signed.call(closure_request)
            if accepted["new_signed_facts"] != 0:
                raise AssertionError(
                    "Closure acknowledgement retry duplicated signed facts"
                )
            checks.append("signed_commit_before_adapter_ack_recovered")
        if ordinal == 6:
            previous = json.loads(
                (root / "episodes/research.case.0000.json").read_text()
            )
            reject(
                root,
                gate,
                "closure_accepted",
                previous["closure"],
                ADAPTER_FAULTS[ordinal],
            )
            checks.append(ADAPTER_FAULTS[ordinal])
        elif ordinal == 7:
            corrupt_closure(root, gate, accepted)
            checks.append(ADAPTER_FAULTS[ordinal])
        gate.append("closure_accepted", case, accepted)
        expected_settlement = reference.settle(specification["budget"], reward)
        if fault == "settlement_acknowledgement_loss":
            gate.settle(owner, lose_acknowledgement=True)
            owner.call({"command": "Close"})
            owner.close()
            owner = start("owner")
            if not owner.call({"command": "Resume", "request": request})["settled"]:
                raise AssertionError("Cold native settlement was lost")
            gate = CreditGate(root / "GATE.jsonl")
            checks.append("native_commit_before_adapter_ack_recovered")
        if ordinal in (8, 9):
            committed = gate.settle(owner, lose_acknowledgement=True)
            corrupt_settlement(root, gate, committed, ADAPTER_FAULTS[ordinal])
            checks.append(ADAPTER_FAULTS[ordinal])
        settlement = gate.settle(owner)
        account = json.loads(settlement["record"]["payload_json"])
        compare(
            {"balance": account["after_balance"], "price": account["after_price"]},
            expected_settlement,
        )
        retry = gate.settle(owner)
        if not retry["duplicate_settlement_ignored"] or retry["new_credit_records"]:
            raise AssertionError("Exact retry minted resource credit twice")
        repeated = signed.call(closure_request)
        if repeated["new_signed_facts"] or any(
            repeated[k]["disposition"] != "IdempotentReplay"
            for k in ("outcome", "credit")
        ):
            raise AssertionError("Exact signed retry appended another fact")
        owner.call(
            {
                "command": "Observe",
                "observation": {
                    "event_id": "after-terminal",
                    "value": 1,
                    "elapsed": len(outputs) + 1,
                    "evidence_digest": digest([case, "forbidden-future-work"]),
                },
            },
            expect_error=True,
        )
        final = owner.call({"command": "Close"})
        if not final["settled"] or not final["terminal"]:
            raise AssertionError("Native terminal settlement did not persist")
        result = {
            "case": case,
            "ordinal": ordinal,
            "fault": fault,
            "checks": checks,
            "request": request,
            "specification": specification,
            "terminal_before_credit": terminal,
            "terminal_after_credit": final,
            "closure": accepted,
            "admission": decision,
            "settlement": settlement,
            "decision": action,
            "reward": reward,
            "observations": len(outputs),
            "avoided_observations": context[2] - len(outputs),
            "work": reference.work,
            "spikes": reference.spikes,
            "snn_cell_updates": reference.cells,
            "initial_account": reference.initial,
            "settled_account": expected_settlement,
            "price_used": reference.price,
            "gate_head": gate.head,
        }
        write(root / "episodes" / f"{case}.json", result)
        return result, accepted["after"]["head"]
    finally:
        for process in processes:
            process.close()


def run(
    destination,
    preserved,
    bridge_build,
    source_seal,
    *,
    development=False,
    bridge_seal=None,
):
    root, preserved, bridge_build = map(Path, (destination, preserved, bridge_build))
    root, preserved, bridge_build = (
        root.resolve(),
        preserved.resolve(),
        bridge_build.resolve(),
    )
    with measured_stage(
        root,
        identity={"stage": "signed-credit-closed-loop-qualification"},
        scope=(
            "Input and build verification, local fixture trust setup, every real native tick, "
            "signed append, refusal, cold recovery, complete RPC persistence and Python references."
        ),
    ) as cost:
        protected = verify(source_seal)
        if not development and bridge_seal is None:
            raise ValueError(
                "Formal integration requires a separately committed bridge source seal"
            )
        integration_source = (
            {"development_only": True}
            if development
            else verify_source(bridge_seal, source_seal)
        )
        owner_binary = (
            preserved
            / "sealed-builds/build01/target/release/examples/adaptive_neuron_host"
        )
        owner_build = preserved / "scientific001/BUILD01.json"
        bridge_binary = bridge_build / "target/release/signed_credit_bridge"
        verify_build(owner_build, owner_binary, source_seal, protected)
        bridge_receipt = verify_bridge(
            bridge_build / "BUILD_RECEIPT.json", bridge_binary, protected
        )
        if not development and (
            bridge_receipt.get("development_only", True)
            or bridge_receipt["integration_source"] != integration_source
        ):
            raise ValueError(
                "A development binary cannot enter the formally sealed integration"
            )
        identities = source_closure(bridge_receipt)
        source = preserved / "scientific001/learning/confirmation/seed_601/meta_theta"
        for name in ("owner", "signed", "rpc", "terminal", "episodes", "negative"):
            (root / name).mkdir()
        shutil.copy2(source / "checkpoint.json", root / "TRAINED_CHECKPOINT.json")
        shutil.copy2(source / "neural.json", root / "NEURAL.json")
        config = protocol()
        write(
            root / "MODEL.json",
            full_profile(json.loads((root / "NEURAL.json").read_text()), config),
        )
        _, checkpoint = verify_checkpoint(
            root / "MODEL.json", root / "TRAINED_CHECKPOINT.json"
        )
        if checkpoint.get("development_only") or checkpoint["arm"] != "meta_theta":
            raise ValueError("A formal jointly meta-trained checkpoint is required")
        permit(root / "owner")
        encoder_proof(root / "MODEL.json", root / "CALIBRATION.json")
        plan = episode_plan(config, 601, "id_test")
        for value in plan:
            value["case"] = "research." + value["case"]
        write(
            root / "PLAN.json",
            {
                "integration_qualification_only": True,
                "seed": 601,
                "episodes": plan,
                "fault_schedule": FAULTS,
                "adapter_fault_schedule": ADAPTER_FAULTS,
            },
        )
        inputs = {
            "development_only": development,
            "integration_source": integration_source,
            "owner_binary": str(owner_binary),
            "signed_binary": str(bridge_binary),
            "owner_binary_sha256": sha(owner_binary),
            "signed_binary_sha256": sha(bridge_binary),
            "checkpoint_sha256": sha(root / "TRAINED_CHECKPOINT.json"),
            "model_sha256": sha(root / "MODEL.json"),
            "owner_build_sha256": sha(owner_build),
            "signed_build_sha256": sha(bridge_build / "BUILD_RECEIPT.json"),
            "protected_v2": protected,
            "source_sha256": identities,
            "trust_scope": "Local user-authorized synthetic research only; distinct fixture signers share one researcher; no organizational-independence claim.",
        }
        write(root / "INPUTS.json", inputs)
        declared = json.loads((HERE / "PROTOCOL.json").read_text())
        if (
            declared["owner_binary_sha256"] != inputs["owner_binary_sha256"]
            or declared["checkpoint_sha256"] != inputs["checkpoint_sha256"]
            or declared["protected_v2_seal_sha256"] != sha(source_seal)
            or declared["fault_schedule"] != {str(k): v for k, v in FAULTS.items()}
            or declared["adapter_fault_schedule"]
            != {str(k): v for k, v in ADAPTER_FAULTS.items()}
        ):
            raise ValueError(
                "Input or fault schedule differs from the integration protocol"
            )
        fixture = {
            "schema": "hepta.local-research.signed-credit-host.v1",
            "research_only": True,
            "study_digest": digest([inputs, sha(root / "PLAN.json")]),
            "owner_binary_sha256": inputs["owner_binary_sha256"],
            "trained_checkpoint_sha256": inputs["checkpoint_sha256"],
            "model_sha256": inputs["model_sha256"],
            **{
                role + "_seed": list(os.urandom(32))
                for role in ("root", "generator", "observer", "allocator")
            },
        }
        write(root / "signed/HOST_FIXTURE.json", fixture)
        os.chmod(root / "signed/HOST_FIXTURE.json", 0o600)
        write(
            root / "signed/RESEARCH_PERMIT.json",
            {
                "schema": "hepta.local-research.signed-credit-permit.v1",
                "allowed_root": str(root / "signed"),
                "production_credentials": False,
                "external_effects": False,
            },
        )
        init = LoggedProcess(
            bridge_binary, root / "signed", root / "rpc/setup", "signed.000"
        )
        try:
            head = init.call({"command": "Init"})["status"]["head"]
        finally:
            init.close()
        results = []
        for ordinal, specification in enumerate(plan):
            result, head = episode(root, inputs, specification, ordinal, head)
            results.append(result)
        signed = LoggedProcess(
            bridge_binary, root / "signed", root / "rpc/final", "signed.000"
        )
        try:
            final = signed.call({"command": "Status"})
        finally:
            signed.close()
        if final["status"]["sequence"] != 48 or verify(source_seal) != protected:
            raise AssertionError("Signed fact closure or protected source changed")
        if source_closure(bridge_receipt) != identities:
            raise AssertionError("Integration source changed during the run")
        all_rpc = [row for p in sorted((root / "rpc").iterdir()) for row in load_rpc(p)]
        owner_rows = [
            json.loads(p.read_text())
            for p in sorted((root / "rpc").glob("*/owner.*/rpc.*.json"))
        ]
        signed_rows = [
            json.loads(p.read_text())
            for p in sorted((root / "rpc").glob("*/signed.*/rpc.*.json"))
        ]
        summary = {
            "development_only": development,
            "integration_source": integration_source,
            "passed": True,
            "episodes": len(results),
            "signed_facts": 48,
            "faults_qualified": list(FAULTS.values()) + list(ADAPTER_FAULTS.values()),
            "native": charge(owner_rows),
            "signed_rpc_count": len(signed_rows),
            "signed_physical_rpc_micros": sum(
                row["response"]["physical_rpc_micros"] for row in signed_rows
            ),
            "signed_facts_appended": sum(
                row["response"].get("result", {}).get("new_signed_facts", 0)
                for row in signed_rows
            ),
            "ledger_recovery_records": sum(
                row["response"].get("result", {}).get("ledger_recovery_records", 0)
                for row in signed_rows
            ),
            "root_signature_activations": len(signed_rows),
            "evidence_signatures_generated": sum(
                len(row["response"].get("result", {}).get("signed_evidence", []))
                for row in signed_rows
            ),
            "typed_signed_append_attempts": sum(
                row["response"].get("result", {}).get("typed_append_attempts", 0)
                for row in signed_rows
            ),
            "rpc_count": len(all_rpc),
            "final_signed_status": final["status"],
            "episode_index": [
                {
                    "case": row["case"],
                    "sha256": sha(root / "episodes" / (row["case"] + ".json")),
                }
                for row in results
            ],
        }
        write(root / "SUMMARY.json", summary)
        cost.update(
            episodes=16, signed_facts=48, summary_sha256=sha(root / "SUMMARY.json")
        )
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("destination", "preserved", "bridge-build", "source-seal"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge-seal", type=Path)
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    result = run(
        args.destination,
        args.preserved,
        args.bridge_build,
        args.source_seal,
        development=args.development,
        bridge_seal=args.bridge_seal,
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("passed", "episodes", "signed_facts", "faults_qualified")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
