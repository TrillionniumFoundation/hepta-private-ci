"""Actual controller gate counterexamples; no Torch or training execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_terminal_result_json_admission import identity, sha, terminal_gate


class TerminalEventAccountingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.parent_dir = self.root / "parents" / "hcsn-s101-lr0.001"
        self.parent_dir.mkdir(parents=True)
        self.prior = {"model_configuration": {"width": 16}, "source_before": {},
                      "epochs": [{"epoch": 1}], "episodes_train": 4,
                      "effective_batch_size": 2, "main_updates": 2,
                      "memorization": {"passed": False}}
        prepared = self.root / 'prepared'
        prepared.mkdir()
        manifest_path = prepared / 'data-manifest.json'
        manifest_path.write_text(json.dumps({'confirmation_access': False,
            'episodes': [{'id': name, 'partition': 'train'} for name in 'abcd']}))
        plan_path = self.parent_dir / 'plan.json'
        plan_path.write_text(json.dumps({'prepared': str(prepared),
            'manifest_sha256': sha(manifest_path), 'batch_size': 2}))
        self.prior['plan_sha256'] = sha(plan_path)
        parent_result = self.parent_dir / "result.json"
        parent_result.write_text(json.dumps(self.prior), encoding="utf-8")
        self.parent = {"name": self.parent_dir.name, "seed": 101,
                       "learning_rate": 0.001, "result_sha256": sha(parent_result),
                       "whole_process_wall_seconds": 10.0}
        self.contract = {"parent_campaign": str(self.parent_dir.parent),
                         "maximum_epochs": 2, "cumulative_active_wall_seconds": 43200,
                         "data_manifest_sha256": sha(manifest_path)}
        self.row = {"returncode": 0, "hard_timeout_sent": False, "process_started": True,
                    "whole_process_wall_seconds": 2.0, "child_cpu_seconds": 1.0}
        self.result = {"schema": "hcsn-c2-soft-wall-continuation-v1",
            "production_execution": True, "confirmation_access": False, "arm": "hcsn",
            "seed": 101, "learning_rate": 0.001, "parent": str(self.parent_dir),
            "parent_outer": self.parent, "parent_report": identity(parent_result),
            "model_configuration": self.prior["model_configuration"],
            "status": "completed_development", "training_adequacy_established": False,
            "source_and_parent_inputs_unchanged": True,
            "common_and_physical_weights_unchanged": True,
            "source_before": {}, "source_after": {}, "parent_retained_epochs": 1,
            "cumulative_epochs_completed": 2, "retained_main_updates_at_resume": 2,
            "logical_main_updates": 4, "new_main_updates": 2,
            "actual_executed_main_updates_logged_all_phases": 4,
            "epochs": [{"epoch": 2, "complete": True, "phase_process_wall_seconds": 1.0}],
            "parent_full_outer_wall_charged": 10.0, "cumulative_active_wall_cap_seconds": 43200,
            "stop_reason": "epoch_cap_not_convergence"}
        # Deliberately opaque synthetic bytes: these tests establish journal
        # admission only, never checkpoint decoding or independent training replay.
        for filename, field in [("development_logits.pt", "selected_development_logits"),
                ("resume-start.pt", "resume_start_checkpoint"),
                ("RESUME-START.json", "resume_start_receipt")]:
            path = self.root / filename
            path.write_bytes(b"synthetic structural fixture")
            self.result[field] = identity(path)
        for filename, field in [("last.pt", "last_checkpoint_sha256"),
                                ("best.pt", "best_checkpoint_sha256")]:
            path = self.root / filename
            path.write_bytes(b"synthetic structural fixture")
            self.result[field] = sha(path)
        self.events = [{"kind": "resume_start_committed",
            "receipt": self.result["resume_start_receipt"],
            "checkpoint": self.result["resume_start_checkpoint"]},
            {"kind": "epoch_started", "epoch": 2, "episode_order": ["a", "b", "c", "d"]}]
        for number in (1, 2):
            self.events.extend([
                {"kind": "update_started", "phase": "main",
                 "episode_ids": ["a", "b"] if number == 1 else ["c", "d"]},
                {"kind": "optimizer_started", "phase": "main", "logical_next_update": number + 2},
                {"kind": "optimizer_completed", "phase": "main", "number": number + 2,
                 "new_number": number}])
        (self.root / 'checkpoints').mkdir()
        checkpoint_path = self.root / 'checkpoints/epoch-0002.pt'
        checkpoint_path.write_bytes((self.root / 'last.pt').read_bytes())
        (self.root / 'commits').mkdir()
        self.commit_path = self.root / 'commits/epoch-0002.json'
        self.commit = {'schema': 'hcsn-c2-complete-epoch-commit-v1',
            'epoch': self.result['epochs'][0], 'checkpoint_path': str(checkpoint_path),
            'checkpoint': identity(checkpoint_path), 'logical_main_updates': 4, 'previous_commit': None}
        self.commit_path.write_text(json.dumps(self.commit))
        self.result['last_commit'] = {'path': str(self.commit_path), **identity(self.commit_path)}
        self.events.extend([{"kind": "epoch_completed", **self.result["epochs"][0],
                             "commit": self.result['last_commit']},
                            {"kind": "finished", "status": "completed_development"}])
        self.gate = terminal_gate()

    def invoke(self, events=None, raw=None):
        if raw is None:
            events = self.events if events is None else events
            raw = b"".join((json.dumps(row) + "\n").encode() for row in events)
        event_path = self.root / "events.jsonl"
        event_path.write_bytes(raw)
        self.result["events"] = identity(event_path)
        path = self.root / "result.json"
        path.write_text(json.dumps(self.result), encoding="utf-8")
        output = self.gate(self.row, path, self.parent, self.contract)
        self.assertEqual(output["whole_process_wall_seconds"], 2.0)
        self.assertEqual(output["child_cpu_seconds"], 1.0)
        return output

    def test_complete_two_update_journal_is_admitted(self):
        self.assertTrue(self.invoke()["terminal_evidence_complete"])

    def test_hash_matching_empty_journal_is_rejected(self):
        self.assertFalse(self.invoke(raw=b"")["terminal_evidence_complete"])

    def test_torn_final_record_is_rejected(self):
        raw = b"".join((json.dumps(row) + "\n").encode() for row in self.events)
        self.assertFalse(self.invoke(raw=raw[:-1])["terminal_evidence_complete"])

    def test_duplicate_json_key_is_rejected(self):
        raw = b"".join((json.dumps(row) + "\n").encode() for row in self.events)
        raw = raw.replace(b'"new_number": 1', b'"new_number": 0, "new_number": 1')
        self.assertFalse(self.invoke(raw=raw)["terminal_evidence_complete"])

    def test_nonfinite_json_field_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[4]["ignored"] = float("nan")
        self.assertFalse(self.invoke(events)["terminal_evidence_complete"])

    def test_missing_optimizer_start_is_rejected(self):
        self.assertFalse(self.invoke(self.events[:3] + self.events[4:])["terminal_evidence_complete"])

    def test_duplicate_optimizer_completion_is_rejected(self):
        self.assertFalse(self.invoke(self.events[:5] + [self.events[4]] + self.events[5:])["terminal_evidence_complete"])

    def test_wrong_logical_step_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[4]["number"] = 99
        self.assertFalse(self.invoke(events)["terminal_evidence_complete"])

    def test_boolean_update_counter_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[4]["new_number"] = True
        self.assertFalse(self.invoke(events)["terminal_evidence_complete"])

    def test_epoch_summary_disagreement_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[-2]["phase_process_wall_seconds"] = 2.0
        self.assertFalse(self.invoke(events)["terminal_evidence_complete"])

    def test_finished_failure_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[-1]["status"] = "failed"
        self.assertFalse(self.invoke(events)["terminal_evidence_complete"])

    def test_records_after_finished_are_rejected(self):
        self.assertFalse(self.invoke(self.events + [self.events[-1]])["terminal_evidence_complete"])

    def test_missing_second_update_is_rejected(self):
        self.assertFalse(self.invoke(self.events[:5] + self.events[8:])["terminal_evidence_complete"])

    def test_float_terminal_counters_are_rejected(self):
        for name in ('parent_retained_epochs', 'retained_main_updates_at_resume',
                     'logical_main_updates', 'new_main_updates',
                     'actual_executed_main_updates_logged_all_phases', 'cumulative_epochs_completed'):
            with self.subTest(counter=name):
                original = self.result[name]
                self.result[name] = float(original)
                self.assertFalse(self.invoke()['terminal_evidence_complete'])
                self.result[name] = original

    def test_float_epoch_row_is_rejected(self):
        self.result['epochs'][0]['epoch'] = 2.0
        self.assertFalse(self.invoke()['terminal_evidence_complete'])

    def test_premature_epoch_cap_stop_is_rejected(self):
        self.contract['maximum_epochs'] = 200
        self.assertFalse(self.invoke()['terminal_evidence_complete'])

    def test_empty_epoch_order_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[1]['episode_order'] = []
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_wrong_epoch_population_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[1]['episode_order'][-1] = 'unseen'
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_empty_batch_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[2]['episode_ids'] = []
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_repeated_first_batch_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[5]['episode_ids'] = ['a', 'b']
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_missing_epoch_commit_is_rejected(self):
        self.commit_path.unlink()
        self.assertFalse(self.invoke()['terminal_evidence_complete'])

    def test_foreign_epoch_commit_is_rejected(self):
        events = copy.deepcopy(self.events)
        events[-2]['commit'] = {'path': '/missing', 'bytes': 0, 'sha256': '0' * 64}
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_hash_consistent_wrong_commit_chain_is_rejected(self):
        self.commit['previous_commit'] = {'path': '/missing', 'bytes': 0, 'sha256': '0' * 64}
        self.commit_path.write_text(json.dumps(self.commit))
        receipt = {'path': str(self.commit_path), **identity(self.commit_path)}
        events = copy.deepcopy(self.events)
        events[-2]['commit'] = receipt
        self.result['last_commit'] = receipt
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_missing_epoch_checkpoint_is_rejected(self):
        (self.root / 'checkpoints/epoch-0002.pt').unlink()
        self.assertFalse(self.invoke()['terminal_evidence_complete'])

    def test_empty_epoch_checkpoint_is_rejected(self):
        (self.root / 'checkpoints/epoch-0002.pt').write_bytes(b'')
        self.commit['checkpoint'] = identity(self.root / 'checkpoints/epoch-0002.pt')
        self.commit_path.write_text(json.dumps(self.commit))
        receipt = {'path': str(self.commit_path), **identity(self.commit_path)}
        events = copy.deepcopy(self.events)
        events[-2]['commit'] = receipt
        self.result['last_commit'] = receipt
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_hash_consistent_float_commit_epoch_is_rejected(self):
        self.commit['epoch'] = {**self.result['epochs'][0], 'epoch': 2.0}
        self.commit_path.write_text(json.dumps(self.commit))
        receipt = {'path': str(self.commit_path), **identity(self.commit_path)}
        events = copy.deepcopy(self.events)
        events[-2]['commit'] = receipt
        self.result['last_commit'] = receipt
        self.assertFalse(self.invoke(events)['terminal_evidence_complete'])

    def test_final_checkpoint_alias_disagreement_is_rejected(self):
        path = self.root / 'last.pt'
        path.write_bytes(b'other hash-consistent checkpoint')
        self.result['last_checkpoint_sha256'] = sha(path)
        self.assertFalse(self.invoke()['terminal_evidence_complete'])


if __name__ == "__main__":
    unittest.main()
