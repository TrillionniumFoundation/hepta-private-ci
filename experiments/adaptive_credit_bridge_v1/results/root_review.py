"""Read-only, post-run review of the declared signed-credit resource equations."""

import json
import math
from pathlib import Path

from experiments.adaptive_neuron_v2.ledger import measured_stage
from experiments.adaptive_neuron_v2.ledger import sha
from experiments.adaptive_neuron_v2.ledger import write_json_exclusive


def main():
    root = Path(__file__).resolve().parents[3]
    source = root / "experiments/adaptive_credit_bridge_v1/runs/formal001"
    destination = Path(__file__).with_name("root_review001")
    with measured_stage(
        destination,
        identity={"stage": "independent-post-run-credit-equation-review"},
        scope=(
            "Read all 16 original episode receipts and both audit reports; independently "
            "check account continuity, resource equations, Q32 credit conservation, "
            "signed identity, stopping and raw aggregates. This is a receipt review, "
            "not another cryptographic verifier or owner execution. Interpreter startup "
            "and the final cost-receipt write lie outside this interval."
        ),
    ) as facts:
        summary = json.loads((source / "loop/SUMMARY.json").read_text())
        episodes = sorted((source / "loop/episodes").glob("*.json"))
        assert len(episodes) == 16
        signed = summary["final_signed_status"]["records"]
        assert len(signed) == 48
        totals = dict(observations=0, spikes=0, cells=0, work=0.0, avoided=0)
        previous = dict(balance=16.0, price=0.02)
        previous_signed_head = "0" * 64
        inputs = {}
        for ordinal, path in enumerate(episodes):
            row = json.loads(path.read_text())
            inputs[path.relative_to(source).as_posix()] = sha(path)
            assert row["ordinal"] == ordinal
            assert row["initial_account"]["sequence"] == ordinal
            for key in previous:
                assert row["initial_account"][key] == previous[key]
            assert row["price_used"] == previous["price"]
            observed = row["observations"]
            assert 1 <= observed <= row["request"]["context"]["deadline"]
            assert row["snn_cell_updates"] == 8 * observed
            assert row["work"] == observed + row["spikes"] / 8
            assert row["avoided_observations"] == (
                row["request"]["context"]["deadline"] - observed
            )
            reward, budget, work = row["reward"], row["request"]["budget"], row["work"]
            expected = {
                "balance": min(
                    32.0, previous["balance"] - work + budget + 0.5 * reward
                ),
                "price": min(
                    0.08,
                    max(
                        0.0, previous["price"] + 0.005 * (work - budget - 0.5 * reward)
                    ),
                ),
            }
            for key, value in expected.items():
                assert math.isclose(row["settled_account"][key], value, abs_tol=1e-12)
            assert previous["balance"] >= work
            assert row["terminal_before_credit"]["terminal"]
            assert not row["terminal_before_credit"]["settled"]
            assert row["terminal_after_credit"]["settled"]
            assert row["settlement"]["new_credit_records"] in (0, 1)
            decision, outcome, credit = signed[3 * ordinal : 3 * ordinal + 3]
            for offset, record in enumerate((decision, outcome, credit), start=1):
                assert record["sequence"] == 3 * ordinal + offset
                assert record["predecessor"] == previous_signed_head
                previous_signed_head = record["chain_digest"]
                assert record["fact"]["episode"] == row["case"]
            assert decision["fact"]["kind"] == "AuthenticatedDecisionV2"
            assert decision["fact"]["selected_candidate"] == "execute-trained-readout"
            assert outcome["fact"]["kind"] == "AuthenticatedOutcomeV2"
            assert credit["fact"]["kind"] == "CreditBatchV2"
            expected_q32 = round(reward * 2**32)
            assert outcome["fact"]["value_q32"] == expected_q32
            assert credit["fact"]["value_q32"] == expected_q32
            assert credit["fact"]["outcome"] == outcome["fact"]["outcome"]
            assert credit["fact"]["support_digest"] == outcome["fact"]["support_digest"]
            allocations = credit["fact"]["allocations"]
            assert len(allocations) == 1
            assert allocations[0]["organ"] == row["request"]["organ"]
            assert (
                sum(x["credit_q32"] for x in allocations)
                + credit["fact"]["residual_q32"]
                == expected_q32
            )
            for key, value in dict(
                observations=observed,
                spikes=row["spikes"],
                cells=row["snn_cell_updates"],
                work=work,
                avoided=row["avoided_observations"],
            ).items():
                totals[key] += value
            previous = row["settled_account"]
        assert previous_signed_head == summary["final_signed_status"]["head"]
        for key, native_key in {
            "observations": "owner_ticks",
            "spikes": "actual_spikes",
            "cells": "actual_snn_cell_updates",
            "work": "actual_resource_work",
        }.items():
            assert totals[key] == summary["native"][native_key]
        assert summary["native"]["new_credit_records"] == len(episodes)
        audits = {}
        for name in ("audit", "portable/replay"):
            path = source / name / "AUDIT.json"
            value = json.loads(path.read_text())
            assert value["episodes"] == 16 and value["signed_facts"] == 48
            assert value["independent_snn_prefixes"] == totals["observations"]
            assert value["original_evidence_unchanged"]
            assert value["replay_owner_work"]["owner_ticks"] == 0
            assert value["replay_owner_work"]["new_credit_records"] == 0
            audits[name] = {"sha256": sha(path), "passed": value["passed"]}
        report = {
            "passed": True,
            "review_source_sha256": sha(__file__),
            "input_summary_sha256": sha(source / "loop/SUMMARY.json"),
            "source_seal_sha256": sha(source / "SOURCE_SEAL.json"),
            "episode_inputs": inputs,
            "totals": totals,
            "final_account": previous,
            "signed_facts": len(signed),
            "signed_head": previous_signed_head,
            "frozen_audit_reports": audits,
            "interpretation": (
                "The 144 unpurchased observations are relative to these task deadlines. "
                "This single-seed integration sequence is not an efficacy comparison. "
                "The original frozen audit supplies cryptographic and RPC-order checks; "
                "this independent review recomputes the resource and identity equations."
            ),
        }
        write_json_exclusive(destination / "REVIEW.json", report)
        facts.update(totals=totals, signed_facts=len(signed), passed=True)


if __name__ == "__main__":
    main()
