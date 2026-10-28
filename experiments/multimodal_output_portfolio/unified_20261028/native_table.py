"""Compile a finite public continuation from actual original-owner witnesses.

This table caches the fixed native state/readout and admission law. It is not a
semantic outcome model: changed generators still need fresh joint trajectories,
costs, selected-policy calibration and actual runtime verification.
"""

import argparse
import json
from pathlib import Path

from ..continuation_20261027.control.client import sha
from .profile import digest


def compile_table(run):
    run = Path(run)
    summary = json.loads((run / "SUMMARY.json").read_text())
    rows, witnesses, identity = {}, {}, None
    for episode in sorted(run.glob("*native_full/EPISODE.json")):
        record = json.loads(episode.read_text())
        binding = {key: record["binding"][key] for key in
                   ("owner_binary", "owner_readout", "owner_calibration", "native_scope_objective")}
        if identity is not None and identity != binding:
            raise ValueError("Cannot combine changed original-owner identities")
        identity = binding
        for feedback, branch in record["forecast_branches"].items():
            if not branch["committed_parent_unchanged"] or not branch["shadow_only"]:
                raise ValueError("Continuation witness must be an actual isolated native fork")
            ticks = branch["ticks"]
            if not all(t["native_transition_executed"] and t["owner_authority"] == "DENY_ALL" for t in ticks):
                raise ValueError("Incomplete original native transition witness")
            decision = ticks[-1]
            proposed = decision["proposed_repair"]
            abstained = any(t["native_abstain"] for t in ticks)
            admitted = proposed and not abstained and record["budget"] >= 2
            key = f"{feedback}:{record['expires']}:{record['budget']}"
            row = {"feedback": int(feedback), "expires": record["expires"], "budget": record["budget"],
                   "native_abstained": abstained, "readout_logit": decision["readout_logit"],
                   "eligibility_q24": decision["eligibility_before_q24"],
                   "selected_action": "swap" if proposed else "keep",
                   "executed_action": "swap" if admitted else "keep",
                   "refused": bool(proposed and not admitted),
                   "fast_cold_kernel_count": 17, "full_cold_kernel_count": 50}
            if key in rows and rows[key] != row:
                raise ValueError("Native continuation is not deterministic within a public key")
            rows[key] = row
            witnesses.setdefault(key, []).append({"episode": str(episode.relative_to(run)),
                "episode_sha256": sha(episode), "branch_sha256": digest(branch),
                "actual_feedback_matched": record["initial"]["public_feedback"] == int(feedback)})
    expected = {f"{feedback}:{expires}:{budget}" for feedback in (-1, 0, 1)
                for expires in (6, 7) for budget in (1, 2)}
    if set(rows) != expected or not summary["all_final_bytes_and_actions_equal"]:
        raise ValueError("The complete finite domain and matched delivery check are required")
    table = {"schema": "hepta.ndu.compiled-native-public-continuation.v1", "identity": identity,
             "source_summary_sha256": sha(run / "SUMMARY.json"), "rows": rows, "witnesses": witnesses,
             "semantic_output_probabilities_included": False, "new_generator_distribution_qualified": False,
             "owner_authority": "DENY_ALL", "host_dispatch_authority_unchanged": True,
             "pricing": "kernel counts only; all measured CPU/wall/codec work remains charged at execution"}
    return {**table, "table_sha256": digest(table)}


def lookup(table, *, feedback, expires, budget, owner_binary_sha256,
           owner_readout_sha256, owner_calibration_sha256):
    body = {key: value for key, value in table.items() if key != "table_sha256"}
    if digest(body) != table.get("table_sha256"):
        raise ValueError("Compiled native continuation bytes changed")
    expected = {"owner_binary": owner_binary_sha256, "owner_readout": owner_readout_sha256,
                "owner_calibration": owner_calibration_sha256}
    if any(table["identity"].get(key) != value for key, value in expected.items()):
        raise ValueError("Compiled continuation belongs to another original owner")
    key = f"{feedback}:{expires}:{budget}"
    if key not in table["rows"]:
        raise ValueError("Public state is outside the actually executed native finite domain")
    return dict(table["rows"][key])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        json.dump(compile_table(args.run), stream, indent=2, sort_keys=True)
        stream.write("\n")
