"""Independent signatures, causal ordering, native recovery and resource audit."""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from experiments.adaptive_neuron_v2.ledger import (
    measured_stage,
    sha,
    write_json_exclusive as write,
)
from experiments.adaptive_neuron_v2.owner.common import charge, digest
from experiments.adaptive_neuron_v2.owner.reference import Reference, compare
from experiments.adaptive_neuron_v2.owner.run import verify_checkpoint
from experiments.adaptive_neuron_v2.provenance import verify
from experiments.adaptive_neuron_v2.roster import episode_plan, protocol

from .crypto_reference import TrustReference, cryptographic_proofs, verify_fact
from .gate import CreditGate
from .provenance import verify_source
from .run import ADAPTER_FAULTS, ROOT
from .transport import LoggedProcess, file_manifest, load_rpc


def audit(root, destination, source_seal, bridge_seal=None):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    with measured_stage(
        destination,
        identity={"stage": "signed-credit-independent-audit"},
        scope=(
            "Every original raw receipt, independent Ed25519 verification, Python SNN and account "
            "reconstruction, 16 fresh owner processes, 16 historical closure retries and durable-gate corruption checks."
        ),
    ) as cost:
        inputs = json.loads((root / "INPUTS.json").read_text())
        if not inputs["development_only"] and (
            bridge_seal is None
            or verify_source(bridge_seal, source_seal) != inputs["integration_source"]
        ):
            raise ValueError("Formal audit requires the committed bridge source seal")
        if verify(source_seal) != inputs["protected_v2"]:
            raise ValueError("Protected scientific source identity differs")
        for name, value in inputs["source_sha256"].items():
            if sha(ROOT / name) != value:
                raise ValueError("Integration source no longer matches run: " + name)
        for kind in ("owner", "signed"):
            if sha(inputs[kind + "_binary"]) != inputs[kind + "_binary_sha256"]:
                raise ValueError("Exact executable identity changed")
        model, _ = verify_checkpoint(
            root / "MODEL.json", root / "TRAINED_CHECKPOINT.json"
        )
        plan = json.loads((root / "PLAN.json").read_text())["episodes"]
        expected_plan = episode_plan(protocol(), 601, "id_test")
        for entry in expected_plan:
            entry["case"] = "research." + entry["case"]
        if plan != expected_plan:
            raise ValueError("Integration tasks differ from the fixed task sequence")
        gate = CreditGate(root / "GATE.jsonl")
        if gate.phase != "settled" or gate.case != plan[-1]["case"]:
            raise AssertionError("Last durable gate did not settle")
        original_before = {
            kind: file_manifest(root / kind) for kind in ("owner", "signed")
        }
        signed_rows = [
            json.loads(p.read_text())
            for p in sorted((root / "rpc").glob("*/signed.*/rpc.*.json"))
        ]
        fixture = json.loads((root / "signed/HOST_FIXTURE.json").read_text())
        trust_reference = TrustReference(fixture)
        crypto, authentications = cryptographic_proofs(signed_rows, fixture)
        signed = LoggedProcess(
            inputs["signed_binary"], root / "signed", destination / "rpc", "signed.000"
        )
        episode_audits, total_prefixes, previous_account = [], 0, None
        try:
            status = signed.call({"command": "Status"})["status"]
            facts = status["records"]
            if len(facts) != 48 or status["sequence"] != 48:
                raise AssertionError("Expected exactly three signed facts per episode")
            previous_head = "0" * 64
            for index, fact in enumerate(facts):
                if (
                    fact["sequence"] != index + 1
                    or fact["predecessor"] != previous_head
                ):
                    raise AssertionError("Native signed ledger is not one causal chain")
                if fact["fact"]["authentication_digest"] not in authentications:
                    raise AssertionError(
                        "Signed ledger fact lacks independently valid evidence"
                    )
                verify_fact(fact, authentications, trust_reference)
                previous_head = fact["chain_digest"]
            for ordinal, specification in enumerate(plan):
                case = specification["case"]
                result = json.loads((root / "episodes" / (case + ".json")).read_text())
                terminal = json.loads(
                    (root / "terminal" / (case + ".json")).read_text()
                )
                rows = load_rpc(root / "rpc" / case)
                rows.sort(key=lambda value: value["sent_monotonic_ns"])
                observed = [
                    row
                    for row in rows
                    if row["request"]["command"] == "Observe" and row["response"]["ok"]
                ]
                decisions = [
                    row
                    for row in rows
                    if row["request"]["command"] == "Decision"
                    and row["response"]["result"]["accepted"]
                ]
                closures = [
                    row
                    for row in rows
                    if row["request"]["command"] == "Closure"
                    and row["response"]["result"]["accepted"]
                ]
                settlements = [
                    row for row in rows if row["request"]["command"] == "Settle"
                ]
                if (
                    len(decisions) != 1
                    or not closures
                    or not settlements
                    or not observed
                ):
                    raise AssertionError(
                        "Missing an actual stage of the signed feedback loop"
                    )
                if not (
                    decisions[0]["received_monotonic_ns"]
                    < observed[0]["sent_monotonic_ns"]
                    and observed[-1]["received_monotonic_ns"]
                    < closures[0]["sent_monotonic_ns"]
                    and closures[0]["received_monotonic_ns"]
                    < settlements[0]["sent_monotonic_ns"]
                ):
                    raise AssertionError("Signed causal ordering was not enforced")
                if previous_account is not None:
                    compare(
                        result["initial_account"],
                        {**previous_account, "sequence": ordinal},
                    )
                reference = Reference(
                    model,
                    specification["context"],
                    {"readout": "snn", "credit": "live"},
                    result["initial_account"],
                )
                for tick, row in enumerate(observed):
                    request, response = (
                        row["request"]["observation"],
                        row["response"]["result"],
                    )
                    if (
                        request["value"] != specification["observations"][tick]
                        or request["elapsed"] != tick + 1
                    ):
                        raise AssertionError(
                            "Owner received future or changed evidence"
                        )
                    if set(request) != {
                        "event_id",
                        "value",
                        "elapsed",
                        "evidence_digest",
                    }:
                        raise AssertionError(
                            "Owner observation contains undeclared information"
                        )
                    compare(response["readout"], reference.observe(request["value"]))
                    if response["terminal"] != (tick == len(observed) - 1):
                        raise AssertionError(
                            "An actual tick occurred after terminal stopping"
                        )
                    total_prefixes += 1
                previous_account = reference.settle(
                    specification["budget"], result["reward"]
                )
                last = observed[-1]["response"]["result"]
                action = (
                    "abstain" if last["native_abstain"] else last["readout"]["action"]
                )
                selected = {"positive": 1, "negative": -1, "abstain": 0}[action]
                reward = float(selected * specification["truth"]) if selected else 0.05
                observed_outcome = digest(
                    [
                        "adaptive-neuron.observed-outcome.v2",
                        specification["stream_id"],
                        specification["truth"],
                        selected,
                        reward,
                    ]
                )
                if (
                    result["reward"] != reward
                    or terminal["support"]["outcome_digest"] != observed_outcome
                ):
                    raise AssertionError(
                        "Signed utility does not match the actually observed task outcome"
                    )
                compare(result["settled_account"], previous_account)
                d, o, c = [
                    entry["fact"] for entry in facts[ordinal * 3 : ordinal * 3 + 3]
                ]
                expected_kinds = [
                    "AuthenticatedDecisionV2",
                    "AuthenticatedOutcomeV2",
                    "CreditBatchV2",
                ]
                if [v["kind"] for v in (d, o, c)] != expected_kinds or any(
                    v["episode"] != case for v in (d, o, c)
                ):
                    raise AssertionError("Signed facts are not bound to this episode")
                decision_support = hashlib.sha256(
                    decisions[0]["request"]["support_json"].encode()
                ).hexdigest()
                outcome_support = hashlib.sha256(
                    terminal["closure_request"]["support_json"].encode()
                ).hexdigest()
                if d["support_digest"] != decision_support or any(
                    v["support_digest"] != outcome_support for v in (o, c)
                ):
                    raise AssertionError(
                        "Signed terminal support differs from actual owner checkpoint"
                    )
                reward_q32 = round(result["reward"] * (1 << 32))
                if (
                    o["value_q32"] != reward_q32
                    or c["value_q32"] != reward_q32
                    or c["residual_q32"] != 0
                    or c["allocations"]
                    != [
                        {
                            "organ": "research.signed-credit.seed601",
                            "credit_q32": reward_q32,
                        }
                    ]
                ):
                    raise AssertionError(
                        "Signed organ credit does not conserve observed utility"
                    )
                replay = signed.call(terminal["closure_request"])
                if (
                    replay["new_signed_facts"] != 0
                    or replay["after"]["head"] != status["head"]
                ):
                    raise AssertionError(
                        "Historical closure retry advanced the signed ledger"
                    )
                owner = LoggedProcess(
                    inputs["owner_binary"],
                    root / "owner",
                    destination / "rpc",
                    f"owner.{ordinal:03d}",
                )
                try:
                    restored = owner.call(
                        {"command": "Resume", "request": terminal["owner_request"]}
                    )
                    if restored["status"] != result["terminal_after_credit"]:
                        raise AssertionError(
                            "Fresh original owner changed spiking or terminal state"
                        )
                    retried = owner.call(
                        {
                            "command": "Settle",
                            "reward": result["reward"],
                            "outcome_digest": terminal["support"]["outcome_digest"],
                        }
                    )
                    if (
                        not retried["duplicate_settlement_ignored"]
                        or retried["new_credit_records"]
                    ):
                        raise AssertionError(
                            "Cold replay duplicated native resource settlement"
                        )
                    owner.call({"command": "Close"})
                finally:
                    owner.close()
                episode_audits.append(
                    {
                        "case": case,
                        "prefixes": len(observed),
                        "signed_sequence": (ordinal + 1) * 3,
                        "cold_replay": True,
                    }
                )
        finally:
            signed.close()
        if {
            kind: file_manifest(root / kind) for kind in ("owner", "signed")
        } != original_before:
            raise AssertionError(
                "Full replay mutated original native or signed evidence"
            )
        negative = [
            json.loads(p.read_text())
            for p in sorted((root / "negative").glob("*.json"))
        ]
        if sorted(row["label"] for row in negative) != sorted(ADAPTER_FAULTS.values()):
            raise AssertionError("Missing a real receipt-binding rejection fixture")
        if any(
            row["gate_before"] != row["gate_after"] or not row["owner_files_unchanged"]
            for row in negative
        ):
            raise AssertionError(
                "Receipt-binding rejection changed gate or owner state"
            )
        for name, data in (
            ("torn", (root / "GATE.jsonl").read_bytes()[:-1]),
            (
                "tampered",
                (root / "GATE.jsonl")
                .read_bytes()
                .replace(b'"sequence":1,', b'"sequence":9,', 1),
            ),
        ):
            path = destination / (name + ".jsonl")
            path.write_bytes(data)
            try:
                CreditGate(path)
            except ValueError:
                pass
            else:
                raise AssertionError("Damaged gate journal did not fail closed")
        replay_signed = [
            row
            for row in load_rpc(destination / "rpc")
            if "trust_proof" in row["response"].get("result", {})
        ]
        replay_crypto, _ = cryptographic_proofs(replay_signed, fixture)
        changed_trust = deepcopy(signed_rows[0]["response"]["result"]["trust_proof"])
        changed_trust["signers"][0]["verifying_key"] = "1" * 64
        changed_fact = deepcopy(facts[1])
        changed_fact["fact"]["support_digest"] = "2" * 64
        for label, value, operation in (
            (
                "signer_list_substitution",
                changed_trust,
                lambda: trust_reference.verify_trust(changed_trust),
            ),
            (
                "signed_payload_fact_mismatch",
                changed_fact,
                lambda: verify_fact(changed_fact, authentications, trust_reference),
            ),
        ):
            try:
                operation()
            except AssertionError as error:
                write(
                    destination / (label + ".json"),
                    {"rejected": True, "reason": str(error), "candidate": value},
                )
            else:
                raise AssertionError(
                    "Independent crypto binding audit accepted " + label
                )
        owner_replay = [
            json.loads(p.read_text())
            for p in sorted((destination / "rpc").glob("owner.*/rpc.*.json"))
        ]
        result = {
            "development_only": inputs["development_only"],
            "integration_source": inputs["integration_source"],
            "passed": True,
            "episodes": len(plan),
            "independent_snn_prefixes": total_prefixes,
            "signed_facts": 48,
            "original_evidence_unchanged": True,
            "all_actual_decisions_precede_neural_work": True,
            "all_actual_signed_closures_precede_resource_settlement": True,
            "cold_signed_and_native_replay_idempotent": True,
            "torn_and_tampered_gate_rejected": True,
            "receipt_binding_rejections": [row["label"] for row in negative],
            "cryptography": crypto,
            "all_signed_fact_payloads_independently_reconstructed": True,
            "signer_list_and_payload_substitution_rejected": True,
            "replay_cryptography": replay_crypto,
            "replay_owner_work": charge(owner_replay),
            "episode_audits": episode_audits,
            "run_inputs_sha256": sha(root / "INPUTS.json"),
            "run_summary_sha256": sha(root / "SUMMARY.json"),
            "protected_v2": inputs["protected_v2"],
        }
        write(destination / "AUDIT.json", result)
        cost.update(
            episodes=16,
            signed_facts=48,
            independent_snn_prefixes=total_prefixes,
            audit_sha256=sha(destination / "AUDIT.json"),
        )
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "destination", "source-seal"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bridge-seal", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            audit(args.run, args.destination, args.source_seal, args.bridge_seal),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
