"""Finite adversarial trace fixtures; these execute no model or qualification."""

import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest

import hepta_neural_diverse_v3 as target


def fixture():
    data = target.training_data()
    context = dict(
        profile=target.PROFILE,
        plan_sha256="22" * 32,
        recipe="11" * 32,
        observer="66" * 32,
        model_plan="77" * 32,
        training_data=target.DATA_SHA256,
        training_rows=target.identity(data["ordered_training_row_sha256"]),
        training_schedule=target.identity(data["update_schedule"]),
        distinct_source_rows=60,
        row_exposures=300,
        optimizer_steps=30,
        physical_microbatch=1,
        expected_input_tokens=15600,
    )
    objective = dict(
        profile=target.PROFILE,
        execution=context,
        recipe=context["recipe"],
        source_sha256="44" * 32,
        optimizer_steps=30,
        microsteps=300,
        distinct_source_rows=60,
        row_exposures=300,
        answer_tokens=300,
        eos_tokens=0,
        actual_input_tokens=15600,
        trace=dict(path="/fixture/" + target.TRACE, bytes=200000, sha256="55" * 32),
        same_work_as_legacy_ten_single_rows=False,
        loss_scope="ten-row-mean-two-original-answer-token-CE-gradient-per-optimizer-step",
    )
    raw = dict(
        input="33" * 32,
        source=dict(
            binary_diverse60_observed="44" * 32,
            binary_diverse60_training_data=target.DATA_SHA256,
        ),
        training=dict(
            steps=30,
            loss=[],
            tokens=15600,
            supervised_tokens=300,
            supported_profile_flops=0,
            flop_scope="profiler-supported-operators-only-not-total-work",
            objective=objective,
        ),
    )
    events = [
        dict(
            event="start",
            profile=target.PROFILE,
            input=raw["input"],
            recipe=context["recipe"],
            plan_sha256=context["plan_sha256"],
            source=objective["source_sha256"],
            source_rows=data["ordered_training_row_sha256"],
            training_data_sha256=target.DATA_SHA256,
            update_schedule_sha256=context["training_schedule"],
            pid=123,
            start_monotonic_ns=1,
        )
    ]
    consumed, clock = dict(steps=[]), 1
    loss = format(math.log(2), ".17g")
    for update, batch in enumerate(data["update_schedule"]):
        for ordinal, index in enumerate(batch):
            clock += 1
            fields = dict(
                optimizer_step=update,
                row_ordinal=ordinal,
                source_row_index=index,
                source_row_sha256=data["ordered_training_row_sha256"][index],
                input_ids=data["training_token_ids"][index],
            )
            events.append(
                dict(
                    event="microstep",
                    **fields,
                    answer_token_ids=[10407, 4607],
                    target_index=("yes", "no").index(
                        data["training_rows"][index]["expected_output"]
                    ),
                    answer_logits=["0", "0"],
                    loss=loss,
                    backward_completed=True,
                    completed_monotonic_ns=clock,
                    completed_process_cpu_ns=clock,
                )
            )
            consumed["steps"].append(dict(**fields, supervised_tokens=1))
        clock += 1
        events.append(
            dict(
                event="optimizer-step",
                optimizer_step=update,
                microsteps=10,
                gradient_l2_squared="1",
                optimizer_completed=True,
                completed_monotonic_ns=clock,
                completed_process_cpu_ns=clock,
            )
        )
        raw["training"]["loss"].append(
            format(math.fsum([float(loss)] * 10) / 10, ".17g")
        )
    events.append(
        dict(
            event="complete",
            optimizer_steps=30,
            microsteps=300,
            tokens=15600,
            supervised_tokens=300,
            completed_monotonic_ns=clock + 1,
        )
    )
    return events, raw, consumed, data, context


class DiverseTraceTests(unittest.TestCase):
    def setUp(self):
        self.arguments = fixture()

    def verify(self, arguments=None):
        return target.validate_trace(
            *(self.arguments if arguments is None else arguments)
        )

    def test_full_order_recounts_thirty_updates_and_sixty_distinct_rows(self):
        self.assertEqual(
            self.verify(),
            dict(
                optimizer_updates=30,
                gradient_microsteps=300,
                distinct_source_rows=60,
                input_tokens=15600,
                answer_supervised_tokens=300,
                eos_supervised_tokens=0,
            ),
        )
        self.assertNotIn("torch", sys.modules)

    def test_legacy_profiles_and_changed_work_context_refuse(self):
        for key, value in (
            ("profile", "canonical-positive-zero-binary-batch-observed-v2"),
            ("optimizer_steps", 10),
            ("row_exposures", 100),
            ("distinct_source_rows", 10),
            ("physical_microbatch", True),
            ("expected_input_tokens", 15600.0),
            ("training_data", "00" * 32),
            ("training_schedule", "00" * 32),
            ("training_rows", "00" * 32),
        ):
            arguments = copy.deepcopy(self.arguments)
            arguments[4][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(arguments)

    def test_missing_replayed_or_reordered_actual_exposures_refuse(self):
        events = self.arguments[0]
        for changed in (
            events[:-1],
            events[:1] + [events[2]] + events[2:],
            events[:1] + events[2:3] + events[1:2] + events[3:],
        ):
            arguments = (changed, *self.arguments[1:])
            with self.subTest(length=len(changed)), self.assertRaises(ValueError):
                self.verify(arguments)

    def test_row_identity_tokens_label_and_scalar_binding_refuse_changes(self):
        original = self.arguments[0][1]
        for key, value in (
            ("source_row_index", 59),
            ("source_row_sha256", "00" * 32),
            ("input_ids", [1, 999, 2]),
            ("answer_token_ids", [10407.0, 4607]),
            ("target_index", 1 - original["target_index"]),
            ("row_ordinal", False),
            ("optimizer_step", False),
            ("backward_completed", False),
        ):
            arguments = copy.deepcopy(self.arguments)
            arguments[0][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(arguments)

    def test_nonfinite_loss_wrong_ce_gradient_clock_and_completion_refuse(self):
        for index, key, value in (
            (1, "answer_logits", ["nan", "0"]),
            (1, "answer_logits", ["-1e308", "1e308"]),
            (1, "loss", "0"),
            (1, "completed_monotonic_ns", 0),
            (1, "completed_process_cpu_ns", True),
            (11, "gradient_l2_squared", "0"),
            (11, "optimizer_completed", False),
            (331, "microsteps", 100),
            (331, "tokens", 15601),
            (331, "supervised_tokens", 300.0),
        ):
            arguments = copy.deepcopy(self.arguments)
            arguments[0][index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                self.verify(arguments)

    def test_full_objective_source_and_mean_loss_are_bound(self):
        for key, value in (
            ("microsteps", 100),
            ("eos_tokens", 1),
            ("distinct_source_rows", 10),
            ("source_sha256", "00" * 32),
            ("actual_input_tokens", 15600.0),
            ("same_work_as_legacy_ten_single_rows", True),
        ):
            arguments = copy.deepcopy(self.arguments)
            arguments[1]["training"]["objective"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(arguments)
        arguments = copy.deepcopy(self.arguments)
        arguments[1]["training"]["loss"][29] = "0"
        with self.assertRaises(ValueError):
            self.verify(arguments)

    def test_independent_consumption_cannot_relabel_or_omit_scheduled_rows(self):
        for changed in ("source_row_index", "source_row_sha256", "supervised_tokens"):
            arguments = copy.deepcopy(self.arguments)
            arguments[2]["steps"][10][changed] = "wrong"
            with self.subTest(field=changed), self.assertRaises(ValueError):
                self.verify(arguments)

    def test_closed_context_and_trace_reject_missing_or_additional_fields(self):
        for location in (0, 1, 11, 331):
            arguments = copy.deepcopy(self.arguments)
            arguments[0][location]["untrusted_extra"] = True
            with self.subTest(location=location), self.assertRaises(ValueError):
                self.verify(arguments)
        arguments = copy.deepcopy(self.arguments)
        del arguments[4]["physical_microbatch"]
        with self.assertRaises(ValueError):
            self.verify(arguments)

    def test_frozen_data_file_cannot_be_replaced_with_new_training_examples(self):
        self.assertEqual(target.training_data(), self.arguments[3])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            changed = copy.deepcopy(self.arguments[3])
            changed["training_rows"][0]["prompt"] += " changed"
            path.write_bytes(target.canonical(changed) + b"\n")
            with self.assertRaisesRegex(
                ValueError, "exact frozen diverse60 public payload"
            ):
                target.training_data(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
