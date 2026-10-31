"""Fit the joint models from an explicitly pinned, source-separated development file."""

import argparse
import hashlib
import json
from pathlib import Path

from .joint import JointObservationLaw, PairObservation
from .prior import JointPrior


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--learning-rate", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--joint-count-alpha", type=float, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != args.expected_sha256:
        raise ValueError("Actual fitting data differ from the declared byte identity")
    data = json.loads(raw)
    if data.get("schema") != "hepta.repair.paired-development.v1" or data.get("role") != "development":
        raise ValueError("Only explicitly declared development data may fit the new models")
    prior = data["prior_training"]
    reserved = data["excluded_source_groups"]
    model = JointPrior.fit(prior["features"], prior["targets"], prior["source_groups"],
                           steps=args.steps, learning_rate=args.learning_rate, seed=args.seed,
                           excluded_groups=reserved)
    rows = [PairObservation(r["sample_id"], r["source_group"], r["target"],
                            tuple(r["event_ids"]), tuple(r["values"]))
            for r in data["pair_observations"]]
    law = JointObservationLaw.fit_paired(rows, alpha=args.joint_count_alpha, excluded_groups=reserved)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, value in (("joint_prior.json", model.export()), ("joint_likelihood.json", law.export())):
        value["fitting_data_sha256"] = digest
        (args.output / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({"input_sha256": digest, "prior_fitted": True,
                      "known_likelihood_targets": int(law.known_targets.sum()),
                      "source_claim": data.get("source_claim", "unspecified; not independently certified"),
                      "fresh_source_qualification": False, "production_authority": False}))


if __name__ == "__main__":
    main()
