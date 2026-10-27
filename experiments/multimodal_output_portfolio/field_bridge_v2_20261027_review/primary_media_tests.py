"""Exercise the independent prospective auditor using only old validation data."""

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
from unittest.mock import patch
import zipfile

import numpy as np

from ..field_bridge_20261027.run import setup
from ..v6.data import make_batch
from ..v6.neural import parameter_hash
from ..field_bridge_v2_20261027.learning import make_model
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from ..field_bridge_v2_20261027.primary_common import P
from ..field_bridge_v2_20261027.primary_evaluate import deploy_batch
from ..field_bridge_v2_20261027.primary_media import MediaStore
from ..field_bridge_v2_20261027.primary_runtime import fit_controllers
from . import primary_media_audit as verifier
from .primary_audit_support import file_sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    corpus, observers, originals, _ = setup(args, audit=True)
    # The verifier receives the registered logical 'test' role, but this mock
    # substitutes eight previously exposed validation sources at every load.
    # No expanded corpus or reserved target is loaded by this contract.
    old_batch = make_batch(corpus, "validation", 8, 271027, offset=700, corruption="clean")
    model = make_model(originals[17], 17, P["recipe"])
    rng = np.random.default_rng(271031)
    def synthetic(n, role):
        x0, x1 = rng.random((n, 8)), rng.random((n, 8))
        returns = np.column_stack((x0[:, 0], x1[:, 1], x0[:, 2]+x1[:, 2], x1[:, 3], x0[:, 4]))*.2
        return dict(x0=x0, x1=x1, returns=returns, role=role)
    cases, media = {}, MediaStore(args.out/"media.zip")
    definitions = {"fixed": "A_frozen_fixed", "native": "D_frozen_native",
                   "history": "H_frozen_history", "reset": "I_field_reset"}
    with NativeFastBridge(args.native, P["native_library_sha256"]) as bridge:
        fitted = fit_controllers(synthetic(32, "train"), synthetic(16, "development"), bridge, "audit-contract")
        for control, arm in definitions.items():
            readout = None if control == "fixed" else fitted["models"]["native" if control == "reset" else control]
            rows, native = io.StringIO(), io.StringIO()
            deploy_batch(model, readout, control, 4, bridge, observers, old_batch, 17*100003,
                         dict(seed=17, arm=arm, split="test", corruption="clean", batch_start=0, batch_seed=271027),
                         args.out/"temporary", media, rows, native)
            cases[control] = ([json.loads(line) for line in rows.getvalue().splitlines()], native.getvalue())
    storage = media.close()
    frozen = {"seeds": {"17": {"fixed_action": 4, "readouts": {"frozen": fitted["models"], "field": fitted["models"]}}}}
    model_hashes = {"17-frozen": parameter_hash(model), "17-field": parameter_hash(model)}
    def check_case(control, rows=None, native=None, referenced=None):
        recorded_rows, recorded_native = cases[control]
        report = {"rows": 0, "batches": 0, "feature_max_discrepancy": 0., "score_max_discrepancy": {}}
        with zipfile.ZipFile(args.out/"media.zip") as archive, NativeFastBridge(args.native, P["native_library_sha256"]) as bridge, \
                patch.object(verifier, "P", {**P, "evaluation_batch_size": 8}), \
                patch.object(verifier, "make_batch", return_value=old_batch) as source:
            verifier.verify_group(recorded_rows if rows is None else rows, archive,
                set() if referenced is None else referenced,
                io.StringIO(recorded_native if native is None else native), bridge, corpus, observers,
                frozen, model_hashes, report, hashlib.sha256())
            assert source.call_count == 1
        assert report["rows"] == 8 and report["feature_max_discrepancy"] == 0.
        assert max(report["score_max_discrepancy"].values()) == 0.
    referenced, passes = set(), []
    for control in definitions:
        check_case(control, referenced=referenced)
        passes.append("complete_"+control+"_byte_feature_score_action_native_replay")
    with zipfile.ZipFile(args.out/"media.zip") as archive:
        assert referenced == set(archive.namelist())
    corruptions = []
    def rejects(name, control, mutate_rows=None, mutate_native=None):
        rows, native = deepcopy(cases[control][0]), cases[control][1]
        if mutate_rows is not None:
            mutate_rows(rows)
        if mutate_native is not None:
            lines = [json.loads(line) for line in native.splitlines()]
            mutate_native(lines)
            native = "".join(json.dumps(line)+"\n" for line in lines)
        try:
            check_case(control, rows=rows, native=native)
        except (ValueError, KeyError, StopIteration):
            corruptions.append(name)
        else:
            raise AssertionError("Corruption was accepted: "+name)
    rejects("cas_address_change", "fixed", lambda rows: rows[0]["artifacts"][0]["paths"].update(image="other.png"))
    rejects("decision_byte_change", "fixed", lambda rows: rows[0].update(decision_bytes_utf8="{}"))
    rejects("private_source_change", "fixed", lambda rows: rows[0]["source_ids"].reverse())
    rejects("public_feature_change", "fixed", lambda rows: rows[0]["public_features0"].__setitem__(0, .314159))
    rejects("unchosen_execution", "fixed", lambda rows: rows[0]["resources"].update(finish_unchosen_continuations_executed=1))
    rejects("observer_score_change", "fixed", lambda rows: rows[0]["audit"].update(utility=.1234567))
    rejects("native_input_change", "native", mutate_native=lambda records: records[0]["request"]["features_q24"].__setitem__(0, 0))
    rejects("native_state_change", "native", mutate_native=lambda records: records[0]["native"]["ticks"][1]["activation_q24"].__setitem__(0, 123))
    rejects("native_feature_hash_change", "native", lambda rows: rows[0]["native_batch_summary"].update(feature_matrix_sha256="0"*64))
    rejects("missing_native_record", "native", mutate_native=lambda records: records.pop())
    receipt = {"schema": "hepta.field-bridge.v2.independent-primary-audit-contract.1", "passed": True,
        "positive_paths": passes, "negative_guards": corruptions, "old_validation_source_ids": old_batch.source_ids,
        "reserved_test_retention_loaded_or_scored": False, "synthetic_runtime_fitting": True,
        "logical_test_role_is_mocked_to_old_validation": True, "positive_rows": 32,
        "exact_feature_score_discrepancy": 0., "media": storage,
        "source_sha256": {name: file_sha(Path(__file__).with_name(name)) for name in
                          ("primary_media_audit.py", "primary_audit_support.py", "primary_media_tests.py")}}
    (args.out/"PRIMARY_INDEPENDENT_AUDIT_CONTRACT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"passed": True, "positive_paths": len(passes), "negative_guards": len(corruptions)}))


if __name__ == "__main__":
    main()
