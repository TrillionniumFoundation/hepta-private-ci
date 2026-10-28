"""Actual scoped codec failure after neural generation, with charged refusal.

The directory collision is deliberately injected. This verifies a real failure
branch and is not an estimate of spontaneous production failure probability.
"""

import argparse
import json
from pathlib import Path

import torch

from ..closure_v2_20261027.control.adapter import Generator
from ..closure_v2_20261027.control.tasks import make_tasks
from ..continuation_20261027.control.client import sha
from ..v6.data import load_corpus
from ..v6.neural import parameter_hash
from .control import NativeController
from .profile import NduProfile, digest


def run(*, binary, checkpoint, corpus, profile, output):
    torch.set_num_threads(1)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    development = package.parent / "closure_v2_20261027/control/evidence/development-001"
    frozen = json.loads((development / "FROZEN.json").read_text())
    if sha(binary) != frozen["binary_sha256"] or sha(checkpoint) != frozen["generator_sha256"]:
        raise ValueError("Actual owner/strong baseline differs from the frozen identity")
    task = make_tasks(load_corpus(corpus), "test", 1, offset=900)[0]
    generator = Generator(checkpoint)

    def dispatch(action, public_state, directory):
        if action != "keep" or public_state != {"source_ids": task["source_ids"]}:
            raise ValueError("The stress protocol permits one initial generation attempt")
        # Existing write_bundle runs deploy first, then create_new output dir.
        # This empty, scoped collision therefore fails real PNG/text emission
        # after an actual neural encode/two-transition/decode generation.
        directory.mkdir()
        try:
            generator.deliver(task["public"], 0, directory)
        except FileExistsError as error:
            if list(directory.iterdir()) or generator.identity != (
                    parameter_hash(generator.model), parameter_hash(generator.gate)):
                raise ValueError("Failed emission changed the snapshot or wrote unexpected artifacts") from error
            return {"artifact_refs": {}, "artifact_sha256": {}, "public_feedback": 0,
                    "final_state_digest": digest(generator.identity), "terminal_kind": "failed",
                    "generator_calls": 1, "delivery_units": 0,
                    "failure_receipt": {"exception": type(error).__name__, "destination": str(directory),
                        "injection": "create_new output-directory collision after actual neural forward",
                        "actual_neural_forward_completed": True, "actual_media_written": False}}
        raise AssertionError("Deliberately occupied output directory unexpectedly accepted create_new")

    controller = NativeController(binary=binary, readout=development / "MODEL.json",
        calibration=development / "ENCODER_DOMAIN_PROOF.json", generator_checkpoint=checkpoint,
        profile=profile, policy_sha256=digest({"stress_protocol_sha256": sha(__file__)}),
        implementation_paths=(__file__, package.parent / "closure_v2_20261027/control/adapter.py"))
    record = controller.execute(directory=output / "actual-failed-delivery", case="scoped-codec-failure",
        public_state={"source_ids": task["source_ids"]}, dispatch=dispatch, expires=7, media_budget=1,
        forecast="none", recovery="cold")
    expected = (record["initial"]["terminal_kind"], record["final"]["terminal_kind"],
        record["selected_action"], record["executed_action"], record["continuation_kind"],
        record["measurements"]["actual_original_kernel_executions"],
        record["measurements"]["actual_generator_calls"], record["measurements"]["actual_delivery_units"])
    if expected != ("failed", "failed", "swap", "keep", "refused", 17, 1, 0):
        raise ValueError("Actual failure or denied retry was lost from execution/cost accounting")
    if not all(kind in {c["kind"] for c in record["costs"]}
               for kind in ("generator_call", "refused_proposal", "python_cpu_second", "native_cpu_second", "wall_second")):
        raise ValueError("An actual failure cost component is missing")
    (output / "EPISODE.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    result = {"schema": "hepta.ndu.actual-codec-failure-stress.v1", "passed": True,
              "profile_sha256": profile.digest, "binding_sha256": controller.fingerprint,
              "episode_sha256": sha(output / "EPISODE.json"), "measurements": record["measurements"],
              "total_cost": record["total_cost"], "failure_receipt": record["initial"]["failure_receipt"],
              "native_authority": record["final_owner_state"]["owner_authority"],
              "actual_failure_and_refusal_cost_preserved": True,
              "production_failure_rate_claim": False, "semantic_quality_score_claim": False}
    (output / "SUMMARY.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "checkpoint", "corpus", "profile", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    profile = NduProfile.from_dict(json.loads(args.profile.read_text()))
    print(json.dumps(run(binary=args.binary, checkpoint=args.checkpoint, corpus=args.corpus,
                         profile=profile, output=args.output)))
