"""Small CPU state/clock recovery fixtures, including resumed A and B training."""

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest

import torch
from .joint_graph import digest, load_training_checkpoint, strict_json, tensor_digest
from .test_joint_graph import fixture as value_fixture
from .test_population_graph import fixture as population_fixture
from .training_state import clock_checkpoint_digest, resolve_training_initialization, state_digest
from .worker import propose


def bind_initialization(request, state, mode):
    clock = dict(schema_version=1, **request["binding"],
                 last_micros=request["intervals"][0]["start_micros"], sequence=0,
                 state_digest=state_digest(state), predecessor_digest="0"*64)
    request["schema_version"] = 2
    request["initialization"] = dict(mode=mode, clock_checkpoint=clock)
    anchor = clock_checkpoint_digest(clock)
    for plan in request["intervals"]:
        plan["checkpoint_before"] = anchor


class TrainingStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def case(self, factory=value_fixture):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return factory(directory.name)

    def resumed_case(self, factory=value_fixture):
        model, request, inputs, targets, intervals = self.case(factory)
        payload, _ = propose(model, request)
        path = Path(request["base_checkpoint"]["path"]).with_name("first-candidate.pt")
        path.write_bytes(payload)
        checkpoint = hashlib.sha256(payload).hexdigest()
        model, state, metadata = load_training_checkpoint(path, checkpoint)
        offset = metadata["last_end_micros"]-request["intervals"][0]["start_micros"]
        for plan in request["intervals"]:
            plan["start_micros"] += offset
            plan["end_micros"] += offset
        request["target_time_micros"] += offset
        request["operation_id"] += ":resume"
        request["base_checkpoint"] = dict(path=str(path), sha256=checkpoint)
        request["binding"]["model_digest"] = checkpoint
        request["optimizer_steps"] = request["limits"]["max_optimizer_steps"] = 2
        bind_initialization(request, state, "resume")
        return model, request, inputs, targets, intervals, state, metadata

    def test_clock_digest_matches_retained_rust_encoded_checkpoint(self):
        root = Path(__file__).parent/"evidence/20261106/bridge/attempt-02-formatted"
        clock = strict_json((root/"training-clock.json").read_bytes())
        plan = strict_json((root/"training-plan.json").read_bytes())
        self.assertEqual(clock_checkpoint_digest(clock), plan["anchor_digest"])

    def test_large_integer_clock_and_fresh_state_bind_without_float_conversion(self):
        for factory in (value_fixture, population_fixture):
            with self.subTest(backend=factory.__module__):
                model, request, inputs, _, _ = self.case(factory)
                for plan in request["intervals"]:
                    plan["start_micros"] += 9_000_000_000_000_000_000
                    plan["end_micros"] += 9_000_000_000_000_000_000
                request["target_time_micros"] += 9_000_000_000_000_000_000
                state = model.initial_state(inputs)
                bind_initialization(request, state, "fresh")
                resolved = resolve_training_initialization(model, request, None, {}, inputs)
                self.assertEqual(state_digest(resolved), state_digest(state))
                # At this magnitude a floating timestamp comparison loses one microsecond.
                request["initialization"]["clock_checkpoint"]["last_micros"] += 1
                for plan in request["intervals"]:
                    plan["checkpoint_before"] = clock_checkpoint_digest(request["initialization"]["clock_checkpoint"])
                with self.assertRaises(ValueError):
                    resolve_training_initialization(model, request, None, {}, inputs)

    def test_clock_identity_state_time_and_every_interval_anchor_are_checked(self):
        model, request, inputs, _, _ = self.case()
        bind_initialization(request, model.initial_state(inputs), "fresh")
        original = request["initialization"]["clock_checkpoint"]
        changes = {name: digest(f"other-{name}") for name in
                   ("profile_digest", "clock_epoch", "scope_digest", "model_digest", "state_digest")}
        changes.update(generation=2, writer_epoch=2, last_micros=original["last_micros"]+1)
        for name, value in changes.items():
            with self.subTest(field=name):
                changed = copy.deepcopy(request)
                clock = changed["initialization"]["clock_checkpoint"]
                clock[name] = value
                for plan in changed["intervals"]:
                    plan["checkpoint_before"] = clock_checkpoint_digest(clock)
                with self.assertRaises(ValueError):
                    resolve_training_initialization(model, changed, None, {}, inputs)
        changed = copy.deepcopy(request)
        changed["intervals"][-1]["checkpoint_before"] = digest("other-outer-anchor")
        with self.assertRaises(ValueError):
            resolve_training_initialization(model, changed, None, {}, inputs)

    def test_unknown_clock_fields_invalid_sequences_and_ambiguous_schemas_reject(self):
        model, request, inputs, _, _ = self.case()
        bind_initialization(request, model.initial_state(inputs), "fresh")
        original = request["initialization"]["clock_checkpoint"]
        for replacement in (dict(schema_version=True), dict(generation=0), dict(writer_epoch=True),
                            dict(last_micros=-1), dict(sequence=1),
                            dict(predecessor_digest=digest("orphan-predecessor")), dict(extra=1)):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                clock_checkpoint_digest(dict(original, **replacement))
        for replacement in (dict(schema_version=True), dict(schema_version=3), dict(initialization=None),
                            dict(initialization=dict(request["initialization"], mode="reset")),
                            dict(initialization=dict(request["initialization"], extra=True))):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                resolve_training_initialization(model, dict(request, **replacement), None, {}, inputs)
        for sequence in (1, 2**64-1):
            changed = copy.deepcopy(request)
            clock = changed["initialization"]["clock_checkpoint"]
            clock.update(sequence=sequence, predecessor_digest=digest("previous-clock"))
            for plan in changed["intervals"]:
                plan["checkpoint_before"] = clock_checkpoint_digest(clock)
            with self.assertRaises(ValueError):
                resolve_training_initialization(model, changed, None, {}, inputs)

    def test_legacy_and_fresh_requests_never_silently_drop_candidate_state(self):
        model, request, inputs, _, _ = self.case()
        state = model.initial_state(inputs)
        self.assertEqual(state_digest(resolve_training_initialization(model, request, None, {}, inputs)),
                         state_digest(state))
        for explicit in (False, True):
            changed = copy.deepcopy(request)
            if explicit:
                bind_initialization(changed, state, "fresh")
            for saved, metadata in ((state, {}), (None, {"last_end_micros": 17}),
                                    (None, {"optimizer": {}, "binding": {}, "last_end_micros": 17})):
                with self.subTest(explicit=explicit, metadata=metadata), self.assertRaises(ValueError):
                    resolve_training_initialization(model, changed, saved, metadata, inputs)

    def test_resume_rejects_missing_mismatched_or_incomplete_saved_state(self):
        model, request, inputs, _, _, state, metadata = self.resumed_case()
        missing_slot = (state[0][:-1], *state[1:])
        changed_state = tuple(tuple(value.clone() for value in cell) for cell in state)
        changed_state[0][0].add_(.5)
        nonfinite = tuple(tuple(value.clone() for value in cell) for cell in state)
        nonfinite[0][0][0, 0] = float("nan")
        for saved in (None, state[:-1], missing_slot, changed_state, nonfinite):
            with self.subTest(state=saved), self.assertRaises(ValueError):
                resolve_training_initialization(model, request, saved, metadata, inputs)
        for missing in ("optimizer", "binding", "last_end_micros"):
            changed = dict(metadata)
            del changed[missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                resolve_training_initialization(model, request, state, changed, inputs)
        with self.assertRaises(ValueError):
            resolve_training_initialization(model, request, state,
                                            dict(metadata, last_end_micros=metadata["last_end_micros"]+1), inputs)

    def test_complete_resumed_snapshot_is_detached_and_does_not_alias_saved_tensors(self):
        for factory in (value_fixture, population_fixture):
            with self.subTest(backend=factory.__module__):
                model, request, inputs, _, _, state, metadata = self.resumed_case(factory)
                for cell in state:
                    for value in cell:
                        value.requires_grad_()
                resolved = resolve_training_initialization(model, request, state, metadata, inputs)
                before = state_digest(resolved)
                self.assertEqual(before, state_digest(state))
                self.assertEqual(tuple(map(len, resolved)), tuple(map(len, state)))
                for cell, saved_cell in zip(resolved, state):
                    for value, saved in zip(cell, saved_cell):
                        self.assertFalse(value.requires_grad)
                        self.assertNotEqual(value.data_ptr(), saved.data_ptr())
                with torch.no_grad():
                    state[0][0].add_(1)
                self.assertEqual(state_digest(resolved), before)

    def test_second_training_block_uses_same_saved_state_for_every_optimizer_forward(self):
        for factory in (value_fixture, population_fixture):
            with self.subTest(backend=factory.__module__):
                model, request, inputs, targets, intervals, state, metadata = self.resumed_case(factory)
                self.assertNotEqual(metadata["binding"]["model_digest"], request["binding"]["model_digest"])
                initial_digest = state_digest(state)
                reference = copy.deepcopy(model)
                for _ in range(request["optimizer_steps"]):
                    prediction, _ = reference(inputs, intervals, state)
                    loss = (prediction[:, -1]-targets).square().mean()
                    gradients = torch.autograd.grad(loss, tuple(reference.parameters()))
                    with torch.no_grad():
                        for parameter, gradient in zip(reference.parameters(), gradients):
                            parameter.add_(gradient, alpha=-request["learning_rate"])
                with torch.no_grad():
                    expected_output, expected_state = reference(inputs, intervals, state)
                    reset_output, _ = reference(inputs, intervals)
                self.assertGreater(float((expected_output-reset_output).abs().max()), 1e-7)
                payload, receipt = propose(model, request)
                path = Path(request["base_checkpoint"]["path"]).with_name("second-candidate.pt")
                path.write_bytes(payload)
                candidate, final_state, _ = load_training_checkpoint(path, hashlib.sha256(payload).hexdigest())
                self.assertEqual(tensor_digest(candidate.state_dict()), tensor_digest(reference.state_dict()))
                self.assertEqual(receipt["final_prediction"], expected_output[:, -1].tolist())
                self.assertEqual(state_digest(final_state), state_digest(expected_state))
                self.assertEqual(state_digest(state), initial_digest)


if __name__ == "__main__":
    unittest.main()
