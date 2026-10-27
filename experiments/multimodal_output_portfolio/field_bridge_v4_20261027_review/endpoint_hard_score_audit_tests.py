"""New V4 access/identity adaptation only; reused score arithmetic is unchanged."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

from . import endpoint_hard_score_audit as audit


def rejected(function):
    try:
        function()
    except ValueError:
        return
    raise AssertionError("Expected an identity/access rejection")


def run(output):
    started = time.perf_counter_ns()
    assert "torch" not in sys.modules, "Test must begin in a fresh process"
    with tempfile.TemporaryDirectory(prefix="v4-endpoint-gate-") as temporary:
        root = Path(temporary)
        rejected(lambda: audit.preflight(root, root / "no-protocol", root / "no-freeze", root / "no-old-run"))
    assert "torch" not in sys.modules, "Incomplete endpoint gate imported a scoring framework"

    import numpy as np
    import torch
    from ..v6.data import SourceCorpus, SourceSplit
    from ..field_bridge_v3_20261027.learning import panels
    from ..field_bridge_v4_20261027.training_qualification import panel_identity
    from ..field_bridge_v3_20261027_review import training_hard_score_audit as low

    protocol_path = Path(__file__).resolve().parent.parent / "field_bridge_v4_20261027/PROTOCOL.json"
    protocol = json.loads(protocol_path.read_text())
    protocol["training"]["panel_batch_size"] = 3
    rng, splits = np.random.default_rng(271099), {}
    for role in audit.ROLES:
        images = torch.from_numpy(rng.integers(0, 256, (10, 1, 28, 28), dtype=np.uint8))
        labels = torch.arange(10, dtype=torch.long)
        hashes = tuple(hashlib.sha256(row.numpy().tobytes()).hexdigest() for row in images)
        ids = tuple(f"synthetic:{role}:{index}:{digest}" for index, digest in enumerate(hashes))
        splits[role] = SourceSplit(images, labels, ids, hashes)
    corpus = SourceCorpus(splits, {"synthetic_only": True})
    checks, batches = 1, 0
    for role in audit.ROLES:
        conditions = protocol["training"]["conditions"] if role.endswith("task") else ["clean"]
        real_builder_output = panels(corpus, role, 17, conditions, protocol)
        expected = json.loads(json.dumps(panel_identity(real_builder_output)))
        rebuilt = audit.rebuild_v4_panel(corpus.splits[role], role, 17, conditions, protocol["training"], expected)
        assert [part["rows"] for part in rebuilt] == [3, 2] * len(conditions)
        for built, independent in zip(real_builder_output, rebuilt, strict=True):
            for section, fields in (("observation", low.OBSERVATION_FIELDS), ("target", low.TARGET_FIELDS)):
                values = independent["public" if section == "observation" else "target"]
                assert all(torch.equal(getattr(getattr(built.batch, section), name), values[name]) for name in fields)
        batches += len(rebuilt)
        checks += 1
        for field in ("public_sha256", "target_sha256", "noise_seed", "source_ids"):
            corrupted = copy.deepcopy(expected)
            row = corrupted["batches"][0]
            if field.endswith("sha256"):
                row[field] = "0" * 64
            elif field == "noise_seed":
                row[field] += 1
            else:
                row[field][0] = list(reversed(row[field][0]))
            corrupted["sha256"] = audit.canonical_sha(corrupted["batches"])
            rejected(lambda: audit.rebuild_v4_panel(corpus.splits[role], role, 17, conditions,
                                                   protocol["training"], corrupted))
            checks += 1
        rejected(lambda: audit.rebuild_v4_panel(corpus.splits[role], role, 29, conditions,
                                               protocol["training"], expected))
        checks += 1
    result = {"schema": "hepta.field-bridge.v4.hard-score-adaptation-contracts.1", "passed": True,
              "checks": checks, "source_panel_batches_exact": batches,
              "incomplete_phase_rejected_before_torch_import": True,
              "public_target_batching_and_metadata_exact": True,
              "changed_metadata_rejected_after_recomputing_its_hash": True,
              "scoring_arithmetic_reused_without_modification": True,
              "real_source_roles_or_outcomes_loaded": False, "generator_models_loaded": 0,
              "generator_forward_calls": 0, "observer_forward_calls": 0,
              "native_calls": 0, "network_calls": 0,
              "script_sha256": audit.file_sha(audit.__file__), "tests_sha256": audit.file_sha(__file__),
              "legacy_score_source_sha256": audit.file_sha(low.__file__),
              "protocol_sha256": audit.file_sha(protocol_path), "wall_ns": time.perf_counter_ns() - started}
    with Path(output).open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"passed": True, "checks": checks, "batches": batches,
                      "generator_and_observer_calls": 0, "receipt_sha256": audit.file_sha(output)}))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
