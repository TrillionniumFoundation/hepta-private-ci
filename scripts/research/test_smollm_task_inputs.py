"""Task-content controls without launching the model or reading confirmation data."""

import copy
import unittest

from smollm_learning_process_v1 import DISTINCT_TASK_INPUTS
from smollm_learning_process_v1 import LEGACY_TASK_INPUTS
from smollm_learning_process_v1 import freeze_task_inputs
from smollm_learning_process_v1 import validate_frozen_task_inputs
from smollm_learning_process_v1 import validate_probe_inputs


class TaskInputsTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "operation": "isolated-task-input-test",
            "task_input_profile": DISTINCT_TASK_INPUTS,
            "source_prompt": "Answer yes or no. Is 135 greater than 134?",
        }
        self.next_prompt = "Answer yes or no. Is 8517 greater than 8516?"
        self.context = freeze_task_inputs(self.config, self.next_prompt)
        self.frozen = dict(self.context, next_prompt=self.next_prompt)

    def test_source_and_successor_use_distinct_frozen_content(self):
        context = validate_frozen_task_inputs(self.config, self.frozen)
        source, successor = (context["task_inputs"][key] for key in ("source-task", "next-task"))
        self.assertEqual(source["prompt"], self.config["source_prompt"])
        self.assertEqual(successor["prompt"], self.next_prompt)
        self.assertNotEqual(source["prompt"], successor["prompt"])
        for inputs in (source, successor):
            validate_probe_inputs(context, inputs)
            validate_probe_inputs(context, copy.deepcopy(inputs))  # Cold readback keeps the exact input.

    def test_probe_refuses_prompt_role_request_id_and_extra_field_changes(self):
        for label in ("source-task", "next-task"):
            for key, value in (
                ("prompt", "a different prompt"),
                ("prompt", self.next_prompt if label == "source-task" else self.config["source_prompt"]),
                ("request_id", "unregistered-task"),
                ("mode", "another-mode"),
                ("caller_claim", True),
            ):
                with self.subTest(label=label, key=key, value=value):
                    changed = dict(self.context["task_inputs"][label], **{key: value})
                    with self.assertRaises(ValueError):
                        validate_probe_inputs(self.context, changed)

    def test_distinct_profile_requires_bounded_explicit_source_prompt(self):
        for value in (None, "", " ", self.next_prompt, "x" * 2049, 7):
            with self.subTest(value=value):
                config = dict(self.config, source_prompt=value)
                with self.assertRaises(ValueError):
                    freeze_task_inputs(config, self.next_prompt)
        config = dict(self.config)
        del config["source_prompt"]
        with self.assertRaises(ValueError):
            freeze_task_inputs(config, self.next_prompt)

    def test_recovery_refuses_mapping_or_pinned_config_substitution(self):
        for key in ("task_inputs", "task_input_profile"):
            changed = dict(self.frozen)
            del changed[key]
            with self.assertRaises(ValueError):
                validate_frozen_task_inputs(self.config, changed)
        changed = copy.deepcopy(self.frozen)
        changed["task_inputs"]["source-task"]["prompt"] = self.next_prompt
        with self.assertRaises(ValueError):
            validate_frozen_task_inputs(self.config, changed)
        with self.assertRaises(ValueError):
            validate_frozen_task_inputs(dict(self.config, source_prompt="replacement"), self.frozen)
        with self.assertRaises(ValueError):
            validate_frozen_task_inputs(self.config, {"next_prompt": self.next_prompt})

    def test_legacy_replay_is_explicitly_shared_and_cannot_claim_distinct_source(self):
        config = {"operation": "legacy-task-input-test"}
        context = validate_frozen_task_inputs(config, {"next_prompt": self.next_prompt})
        self.assertEqual(context["task_input_profile"], LEGACY_TASK_INPUTS)
        self.assertEqual(context["task_inputs"]["source-task"]["prompt"], self.next_prompt)
        self.assertEqual(context["task_inputs"]["next-task"]["prompt"], self.next_prompt)
        with self.assertRaises(ValueError):
            freeze_task_inputs(dict(config, source_prompt="ignored source would be unsafe"), self.next_prompt)
        with self.assertRaises(ValueError):
            freeze_task_inputs(dict(config, task_input_profile="caller-defined-profile"), self.next_prompt)


if __name__ == "__main__":
    unittest.main()
