"""Synthetic access/census checks; never materialize the reused real sources."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from . import source_guard as guard


def prior_fixture():
    models = [{"seed": seed, "arm": arm, "sha256": f"model-{seed}-{arm}"}
              for seed in (17, 29, 43, 59, 71)
              for arm in ("mean", "old_constraint", "matched_floor", "matched_floor_warmdual")]
    spec = {"models": models, "source_identity": {"source_pairs": 1000},
            "role_assignment_sha256": "original-assignment"}
    result = {"models": [{**row, "rows": 16000, "shape_per_metric": [1000, 8, 2]} for row in models],
        "status": "completed", "protocol_sha256": "prior-protocol", "outcomes_used_for_selection": False,
        "source_identity": spec["source_identity"]}
    access = {"protocol_sha256": "prior-protocol", "source_identity": spec["source_identity"],
        "role_assignment_sha256": "original-assignment", "role": "repair_test",
        "origin_role": "unallocated_test", "start": 0, "count": 1000}
    return spec, result, access


class ReuseGuardTests(unittest.TestCase):
    def test_original_completed_census_cannot_be_shortened_or_relabelled(self):
        spec, result, access = prior_fixture()
        guard.validate_prior_execution(spec, result, access, "prior-protocol")
        changes = (lambda r, a: r["models"].pop(),
                   lambda r, a: r["models"].__setitem__(0, deepcopy(r["models"][1])),
                   lambda r, a: r["models"][0].update(sha256="wrong-model"),
                   lambda r, a: r["models"][0].update(rows=15999),
                   lambda r, a: r.update(status="partial"),
                   lambda r, a: a.update(origin_role="test"),
                   lambda r, a: a.update(count=999))
        for change in changes:
            with self.subTest(change=change):
                changed_result, changed_access = deepcopy(result), deepcopy(access)
                change(changed_result, changed_access)
                with self.assertRaises(ValueError):
                    guard.validate_prior_execution(spec, changed_result, changed_access, "prior-protocol")

    def exercise_access(self, root, callback):
        assignment_path, timeline_path = root / "assignment.json", root / "timeline.json"
        assignment_path.write_text("synthetic assignment")
        timeline_path.write_text("synthetic timeline")
        protocol_path = root / "protocol.json"
        protocol_path.write_text("synthetic frozen protocol")
        output = root / "new-access"
        assignment = {"source_role": "repair_test", "origin_role": "unallocated_test",
            "study_role": "native_candidate_reuse", "pair_start": 0, "pair_count": 1000,
            "source_identity": {"individual_sources": 2000, "ordered_source_ids_sha256": "synthetic"},
            "registered_unix_ns": 0, "prior_dependencies": {
                "original_assignment": {"sha256": "original-assignment"},
                "completed_execution": {"sha256": "completed-twenty-models"}}}
        spec = {**assignment, "output": str(output),
                "reuse_assignment_sha256": guard.sha(assignment_path), "timeline_sha256": guard.sha(timeline_path)}
        module = types.ModuleType(guard.__package__ + ".protocol")
        module.verify = lambda path: spec
        with patch.object(guard, "ASSIGNMENT", assignment_path), patch.object(guard, "TIMELINE", timeline_path), \
                patch.object(guard, "verify_assignment", return_value=assignment), \
                patch.dict(sys.modules, {module.__name__: module}):
            callback(protocol_path, output, spec)

    def test_new_access_is_required_before_any_source_materialization(self):
        def check(protocol_path, output, spec):
            output.mkdir()
            # No existing repair access may silently substitute for this file.
            with self.assertRaises(FileNotFoundError):
                guard.materialize(Path("nonexistent-source-cache"), protocol_path, output)
            self.assertEqual(list(output.iterdir()), [])
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_access(Path(directory), check)

    def test_new_access_rejects_prior_record_and_changed_role_or_census(self):
        def check(protocol_path, output, spec):
            original = guard.register_access(protocol_path, output)
            self.assertEqual(guard.verify_access(protocol_path, output), original)
            path = output / "access-registration.json"
            mutations = ({"source_role": "test"}, {"origin_role": "test"}, {"pair_count": 999},
                         {"protocol_sha256": "wrong-protocol"}, {"source_previously_observed": False},
                         {"unique_new_source_pairs": 1000}, {"opened_unix_ns": 0})
            for mutation in mutations:
                path.write_text(json.dumps({**original, **mutation}))
                with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                    guard.verify_access(protocol_path, output)
            path.write_text(json.dumps(prior_fixture()[2]))
            with self.assertRaises(ValueError):
                guard.verify_access(protocol_path, output)
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_access(Path(directory), check)

    def test_access_cannot_overwrite_or_move_frozen_output(self):
        def check(protocol_path, output, spec):
            with self.assertRaises(ValueError):
                guard.register_access(protocol_path, output.with_name("foreign-output"))
            first = guard.register_access(protocol_path, output)
            with self.assertRaises(FileExistsError):
                guard.register_access(protocol_path, output)
            self.assertEqual(guard.verify_access(protocol_path, output), first)
        with tempfile.TemporaryDirectory() as directory:
            self.exercise_access(Path(directory), check)


if __name__ == "__main__":
    unittest.main()
