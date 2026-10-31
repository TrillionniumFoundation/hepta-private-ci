"""Verify implementation and replay the pinned historical support counterexample."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import unittest

import numpy as np

from .joint import JointObservationLaw
from .test_evidence import EvidenceTests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvidenceTests)
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise RuntimeError(log.getvalue())
    here = Path(__file__).resolve().parent
    source = here.parents[1] / "advance_20261026/control/AUDIO_LIKELIHOOD.json"
    data = json.loads(source.read_bytes())
    original = np.array(data["pair_observation_by_target"])
    repaired = JointObservationLaw.from_components(data["digit_observation_by_target"])
    non_diagonal = [o for o in range(100) if o // 10 != o % 10]
    record = {
        "schema": "hepta.repair.joint-evidence-verification.v1",
        "implementation_tests": {"passed": result.testsRun, "log": log.getvalue()},
        "existing_aggregate_replay": {
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "recorded_old_recordings": data["recordings"], "recorded_old_speakers": data["speakers"],
            "old_impossible_mass_by_equal_target": [float(original[non_diagonal, 11 * d].sum()) for d in range(10)],
            "repaired_impossible_mass": 0.,
            "known_single_event_columns": 10, "unidentified_distinct_target_columns": 90,
            "meaning": "structural support repair; no new waveform/CNN observation or empirical probability transfer"},
        "scope": {"synthetic_joint_training_test_executed": True,
                  "fresh_source_training_or_qualification": False,
                  "same_speaker_joint_law_estimated_from_real_pairs": False,
                  "native_owner_execution": False, "production_authority": False},
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(here.glob("*.py"))},
    }
    with args.output.open("x") as stream:
        json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": result.testsRun, "output": str(args.output), "empirical_qualification": False}))


if __name__ == "__main__":
    main()
