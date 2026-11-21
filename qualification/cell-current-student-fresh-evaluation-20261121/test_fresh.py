"""Synthetic receipt/callback controls; zero model or native child executions."""

import copy
from pathlib import Path
import tempfile
import unittest

from cell_experiments import chat_protocol
import fresh_contract as c


class CharacterTokenizer:
    """Character IDs expose the complete-template terminator in a small control."""

    def encode(self, text, **kwargs):
        return list(text.encode())

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        text = "".join("<" + m["role"] + ">" + m["content"] + ("!" if m["role"] == "assistant" else "")
                       for m in messages)
        return text + ("<assistant>" if add_generation_prompt else "")


class FreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.weights = {"schema": "hepta.current-student-fresh-weights.v1", "training_candidate_digest": c.TRAINING_CANDIDATE,
                        "created_at_ns": "1", "models": {mode: {} for mode in c.MODES}}
        self.excluded = {"owners": ["jaraco"], "content_sha256s": []}
        self.selection = {"schema": "hepta.current-student-fresh-selection.v1", "weights_digest": c.digest(self.weights),
                          "excluded_inventory_digest": c.digest(self.excluded), "repositories": list(c.REPOSITORIES),
                          "caps": c.CAPS, "request_policy": c.POLICY, "automatic_retry": False,
                          "as_of": c.AS_OF,
                          "commit_order": c.COMMIT_ORDER,
                          "old_raw_policy_comparable": False, "owner_root": str(self.root / "e2-fresh-synthetic")}
        self.publication = {"selection_digest": c.digest(self.selection), "commit": "a" * 40, "published_at_ns": "2"}
        self.tokenizer = CharacterTokenizer()

    def binding(self, name, value):
        path = self.root / name
        c.write_new(path, value)
        return {"path": str(path), "sha256": c.sha(path)}

    def request(self, prompt="repair"):
        return {"record_id": "synthetic", "task": {"input": prompt, "messages": [{"role": "user", "content": prompt}]}}

    def native_artifacts(self, index, record, pair):
        """Synthetic files exercise byte bindings; they are not native receipts."""
        root = self.root / f"synthetic-native-{index}"
        root.mkdir()
        record["task_spec_path"] = str(root / "TASK_SPEC.json")
        record["native_result_sha256s"] = {}
        for side in ("before", "after"):
            folder = root / (side + "-run")
            (folder / "sandbox-output").mkdir(parents=True)
            expected = record["original_source_sha256" if side == "before" else "original_after_sha256"]
            case = {"project_id": record["project_id"], "source_path": "module.py", "source_sha256": expected,
                    "host_net_namespace": "host-net", "host_pid_namespace": "host-pid", "test_files": []}
            attestation = {"source_sha256": expected, "tests_readonly": True, "dependencies_readonly": True,
                           "package_readonly": True, "host_canary_visible": False, "effective_capabilities": "0",
                           "net_namespace": "synthetic-net", "pid_namespace": "synthetic-pid", "network_interfaces": [[1, "lo"]], "test_files": {}, "root_test_files": {}}
            c.write_new(folder / "CASE.json", case)
            c.write_new(folder / "sandbox-output/SANDBOX_ATTESTATION.json", attestation)
            (folder / "STDOUT.txt").write_text("synthetic stdout only\n")
            (folder / "STDERR.txt").write_text("")
            (folder / "sandbox-output/junit.xml").write_text('<testsuite><testcase classname="test" name="case">'
                + ('<failure message="synthetic failure"/>' if side == "before" else '') + '</testcase></testsuite>')
            pair[side].update(patched_source_sha256=expected, stdout_sha256=c.sha(folder / "STDOUT.txt"),
                stderr_sha256=c.sha(folder / "STDERR.txt"), case_sha256=c.sha(folder / "CASE.json"),
                junit_sha256=c.sha(folder / "sandbox-output/junit.xml"),
                sandbox_attestation_sha256=c.sha(folder / "sandbox-output/SANDBOX_ATTESTATION.json"))
            c.write_new(folder / "RESULT.json", pair[side])
            record["native_result_sha256s"][side] = c.sha(folder / "RESULT.json")

    def test_publication_and_owner_gate_precede_content(self):
        result = c.validate_selection(self.selection, self.weights, self.excluded, self.publication)
        self.assertEqual(result["jaraco/inflect"], "BEFORE_SCAN_REFUSAL")
        with self.assertRaises(ValueError):
            c.record_guard({"schema": "hepta.current-student-fresh-task.v1", "project_id": "jaraco/inflect",
                            "source_group": "github-owner:jaraco"}, self.selection, self.excluded, self.publication)
        for mutate in (lambda p: p.update(published_at_ns="1"), lambda p: p.update(selection_digest="b" * 64)):
            publication = copy.deepcopy(self.publication)
            mutate(publication)
            with self.assertRaises(ValueError):
                c.validate_selection(self.selection, self.weights, self.excluded, publication)

    def test_complete_target_includes_terminator_and_full_retrieval_input(self):
        receipt = c.complete_capacity(self.request(), "x" * 383, self.tokenizer, chat_protocol)
        self.assertEqual(receipt["reference_continuation_tokens"], 384)
        with self.assertRaises(ValueError):
            c.complete_capacity(self.request(), "x" * 384, self.tokenizer, chat_protocol)
        overhead = c.prefix_measure(self.request("x"), self.tokenizer, chat_protocol)["input_tokens"] - 1
        request = self.request("x" * (4096 - overhead))
        self.assertEqual(c.prefix_measure(request, self.tokenizer, chat_protocol)["input_tokens"], 4096)
        request["task"]["messages"].append({"role": "user", "content": "retrieved memory"})
        with self.assertRaises(ValueError):
            c.prefix_measure(request, self.tokenizer, chat_protocol)

    def test_finite_slot_set_and_native_dependencies(self):
        slots = c.Slots(self.selection, self.excluded)
        with self.assertRaises(ValueError):
            slots.claim("scan", (5,), {})
        with self.assertRaises(ValueError):
            slots.claim("material", (0, 1), {})
        slots.claim("scan", (0,), {})
        slots.claim("material", (0, 0), {})
        with self.assertRaises(ValueError):
            slots.claim("qualification_native", (0, 0, "after"), {})
        slots.claim("qualification_native", (0, 0, "before"), {})
        slots.claim("qualification_native", (0, 0, "after"), {})
        for mode in c.MODES:
            for arm in c.ARMS:
                for index in range(4):
                    slots.claim("generation", (mode, arm, index), {})
        with self.assertRaises((ValueError, FileExistsError)):
            slots.claim("generation", (c.MODES[0], c.ARMS[0], 0), {})
        self.assertEqual(len(list(slots.root.glob("generation--*.json"))), 24)

    def test_four_independent_synthetic_records_and_earlier_candidate_refusal(self):
        records, audit = [], []
        for index, project in enumerate(c.REPOSITORIES[:4]):
            h = lambda key: c.digest([index, key])
            record = {"schema": "hepta.current-student-fresh-task.v1", "record_id": "synthetic-" + str(index),
                      "project_id": project, "source_group": "github-owner:" + project.split("/")[0],
                      "repository_metadata": self.binding(f"metadata-{index}.json", {"full_name": project,
                          "owner": {"login": project.split("/")[0]}, "id": index + 1, "fork": False}),
                      "training_allowed": False, "evaluation_allowed": True, "previously_exposed": False,
                      "split": "confirmation", "origin_kind": "curated_development",
                      "weights_digest": self.selection["weights_digest"], "source_access_started_at_ns": "3",
                      "source_preparation_completed_at_ns": "4",
                      "source_path": "module.py", "allowed_function": "repair", "original_parent": "a" * 40,
                      "source_position": [0, 0],
                      "original_commit": "b" * 40, "original_source_sha256": h("before"), "original_after_sha256": h("after"),
                      "before_after_function_AST_sha256": [h("before-ast"), h("after-ast")], "test_AST_sha256s": [h("test")],
                      "task": self.request()["task"], "task_spec_sha256": h("spec"), "expected_cases": [["test", "case"]]}
            side = {"actual_wait_returncode": 0, "failures": 0, "errors": 0, "skipped": 0,
                    "tests": 1, "cases": [{"classname": "test", "name": "case", "failure": None, "error": None}],
                    "timed_out": False, "sandbox_attestation_sha256": h("attest"), "success": True}
            pair = {"status": "ORIGINAL_NATIVE_PAIR_PASSED", "repository": project, "commit": "b" * 40,
                    "parent": "a" * 40, "source_path": "module.py", "function": "repair",
                    "commit_index": 0, "source_index": 0,
                    "task_spec_sha256": h("spec"), "before": {**side, "actual_wait_returncode": 1, "failures": 1,
                        "cases": [{"classname": "test", "name": "case", "failure": "synthetic failure", "error": None}]},
                    "after": side, "same_original_case_set": True, "expected_cases": record["expected_cases"]}
            self.native_artifacts(index, record, pair)
            record["native_pair"] = self.binding(f"pair-{index}.json", pair)
            notice = self.binding(f"notice-{index}.json", {"synthetic": True})
            record["license_review"] = self.binding(f"license-{index}.json", {"material_retention_conditions_satisfied": True,
                "task_spec_sha256": h("spec"), "original_notices": [{**notice, "bytes": Path(notice["path"]).stat().st_size}]})
            records.append(record)
            scan = self.binding(f"scan-{index}.json", {"schema": "hepta.current-student-fresh-history.v1",
                "status": "ORDERED_STATIC_SCAN_COMPLETE",
                "canonical_repository": project,
                "commits": [{"source_candidates": [{"status": "REQUIRES_QUALIFICATION"}]}]})
            terminal = self.binding(f"terminal-{index}.json", {"status": "QUALIFIED", "record_id": record["record_id"],
                "task_digest": c.digest(record)})
            audit.append({"project_id": project, "status": "SELECTED", "scan": scan,
                          "attempts": [{"position": [0, 0], "result": terminal}]})
        panel = {"schema": "hepta.current-student-fresh-panel.v1", "selection_digest": c.digest(self.selection),
                 "tasks": records, "selection_audit": self.binding("audit.json", {"repositories": audit})}
        c.panel_guard(panel, self.selection, self.excluded, self.publication)
        for invalid in (-1, True, "0"):
            changed = copy.deepcopy(records[0])
            pair = c.read_bound(changed["native_pair"])
            pair["after"]["errors"] = invalid
            changed["native_pair"] = self.binding(f"invalid-count-{invalid}.json", pair)
            with self.assertRaisesRegex(ValueError, "nonnegative integers"):
                c.record_guard(changed, self.selection, self.excluded, self.publication)
        raw = Path(records[0]["task_spec_path"]).parent / "before-run/STDOUT.txt"
        original = raw.read_bytes()
        raw.write_bytes(original + b"tampered")
        with self.assertRaisesRegex(ValueError, "actual native output"):
            c.record_guard(records[0], self.selection, self.excluded, self.publication)
        raw.write_bytes(original)
        changed, pair = copy.deepcopy(records[0]), c.read_bound(records[0]["native_pair"])
        pair["before"]["failures"] = 2
        changed["native_pair"] = self.binding("forged-count.json", pair)
        actual_result = Path(changed["task_spec_path"]).parent / "before-run/RESULT.json"
        original = actual_result.read_bytes()
        actual_result.write_bytes(c.canonical(pair["before"]))
        changed["native_result_sha256s"]["before"] = c.sha(actual_result)
        with self.assertRaisesRegex(ValueError, "actual JUnit"):
            c.record_guard(changed, self.selection, self.excluded, self.publication)
        actual_result.write_bytes(original)
        broken = copy.deepcopy(panel)
        broken["tasks"][1]["previously_exposed"] = True
        with self.assertRaises(ValueError):
            c.panel_guard(broken, self.selection, self.excluded, self.publication)
        audit[0]["attempts"] = []
        panel["selection_audit"] = self.binding("bad-audit.json", {"repositories": audit})
        with self.assertRaises(ValueError):
            c.panel_guard(panel, self.selection, self.excluded, self.publication)


if __name__ == "__main__":
    unittest.main()
