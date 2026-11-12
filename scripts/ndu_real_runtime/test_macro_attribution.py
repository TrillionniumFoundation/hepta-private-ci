"""Retained-original integration fixtures; these do not establish policy benefit."""

import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from ndu_real_materials import common
from . import macro_realization as realization
from . import macro_training_pairs
from .content_identity import selection_receipt
from .metacontrol_macro_contract import sha
from .metacontrol_native_pairs import retain_finalizer_input
from .test_macro_realization import fixture, save, sync_steps
from .test_macro_training_fixtures import collection, refresh


def traced_fixture(root, macro="READ", *, initial_index=1, final_index=0):
    data = fixture(root, macro=macro, selected_index=final_index)
    directory = data["directory"]
    steps = json.loads((directory / "trajectory.json").read_bytes())["steps"]
    for index, step in enumerate(steps):
        step["selected_candidate_index"] = (
            initial_index if index < 2 and macro == "READ" else final_index
        )
    if macro == "READ":
        for step in steps[:2]:
            step["candidate_metadata"][0]["text"] = "OLD TEXT"
    sync_steps(directory, steps)
    initial = json.loads((directory / "public-input.json").read_bytes())
    initial.update(step=0, forced_action=steps[0]["action"]["action"])
    if macro == "READ":
        pixels = io.BytesIO()
        Image.new("RGB", (2, 2), "black").save(pixels, format="PNG")
        (directory / "public/initial.png").write_bytes(pixels.getvalue())
        initial["observation"].update(
            path="initial.png", sha256=sha(pixels.getvalue()), kind="overview"
        )
    save(directory / "initial-input.json", initial)
    data["initial_public_input"] = common.binding(
        directory / "initial-input.json", directory
    )
    launch = json.loads((directory / "launch.json").read_bytes())
    launch["host_exchanges"][0].update(
        reply_sha256=data["initial_public_input"]["sha256"],
        reply_bytes=data["initial_public_input"]["bytes"],
    )
    save(directory / "launch.json", launch)
    return data


class MacroAttributionTests(unittest.TestCase):
    def test_acquisition_choice_and_written_change_do_not_invent_terminal_effect(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = traced_fixture(Path(tmp))
            report = realization.observe_realization(**data)
            change = report["read_attribution"]
            for key in (
                "read_executed",
                "observation_bytes_changed",
                "new_recognized_text",
                "selected_text_changed",
                "written_text_differs_from_initial_selection",
                "new_reference_matching_candidate",
            ):
                self.assertIs(change[key], True, key)
            self.assertFalse(change["initial_scorer_match_present"])
            self.assertTrue(change["finalizer_scorer_match_present"])
            self.assertIsNone(change["semantic_information_gain"])
            self.assertIsNone(change["terminal_quality_change"])
            self.assertIsNone(report["stages"]["observation"]["new_information"])

    def test_reordered_candidates_do_not_count_as_changed_selected_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = traced_fixture(Path(tmp), initial_index=0, final_index=1)
            directory = data["directory"]
            steps = json.loads((directory / "trajectory.json").read_bytes())["steps"]
            steps[0]["candidate_metadata"] = list(
                reversed(steps[2]["candidate_metadata"])
            )
            sync_steps(directory, steps)
            change = realization.observe_realization(**data)["read_attribution"]
            self.assertFalse(change["new_recognized_text"])
            self.assertFalse(change["selected_text_changed"])
            self.assertFalse(change["written_text_differs_from_initial_selection"])
            self.assertTrue(change["candidate_inventory_changed"])

    def test_legacy_missing_initial_choice_remains_unknown_despite_scored_delivery(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            report = realization.observe_realization(**fixture(Path(tmp)))
            change = report["read_attribution"]
            self.assertIsNone(change["selected_text_changed"])
            self.assertIsNone(change["written_text_differs_from_initial_selection"])
            self.assertIsNone(change["observation_bytes_changed"])
            self.assertIsNone(change["terminal_quality_change"])

    def test_inconsistent_raw_initial_input_or_choice_trace_rejects(self):
        for kind in ("reply", "initial_index", "final_index", "candidate_fields"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                data = traced_fixture(Path(tmp))
                directory = data["directory"]
                if kind == "reply":
                    path = directory / "initial-input.json"
                    path.write_bytes(path.read_bytes() + b" ")
                    data["initial_public_input"] = common.binding(path, directory)
                else:
                    steps = json.loads((directory / "trajectory.json").read_bytes())[
                        "steps"
                    ]
                    if kind == "candidate_fields":
                        steps[0]["candidate_metadata"][0]["unregistered"] = True
                    else:
                        steps[0 if kind == "initial_index" else 2][
                            "selected_candidate_index"
                        ] = False if kind == "initial_index" else 1
                    sync_steps(directory, steps)
                with self.assertRaises(ValueError):
                    realization.observe_realization(**data)

    def pair(self, root):
        inputs = []
        for macro in ("STOP", "READ"):
            stage = root / macro
            stage.mkdir()
            data = traced_fixture(stage, macro, final_index=1 if macro == "STOP" else 0)
            result = data["result"]
            result.update(
                original_operation_id=macro + "/original",
                source_sha256="a" * 64,
                control_profile_sha256="b" * 64,
                utility_profile_sha256="c" * 64,
            )
            if macro == "STOP":
                directory = data["directory"]
                steps = json.loads((directory / "trajectory.json").read_bytes())[
                    "steps"
                ]
                steps[0]["candidate_metadata"][0]["text"] = "OLD TEXT"
                steps[0]["content_selection"] = selection_receipt(
                    steps[0]["candidate_metadata"], 1, steps[0]["action"]
                )
                sync_steps(directory, steps)
            else:
                directory = data["directory"]
                initial = json.loads((directory / "initial-input.json").read_bytes())
                initial["observation"] = json.loads(
                    (directory / "public-input.json").read_bytes()
                )["observation"]
                save(directory / "initial-input.json", initial)
                data["initial_public_input"] = common.binding(
                    directory / "initial-input.json", directory
                )
                launch = json.loads((directory / "launch.json").read_bytes())
                launch["host_exchanges"][0].update(
                    reply_sha256=data["initial_public_input"]["sha256"],
                    reply_bytes=data["initial_public_input"]["bytes"],
                )
                save(directory / "launch.json", launch)
            save(data["directory"] / "result.json", result)
            data["wall_seconds"] = 1.0 if macro == "STOP" else 3.0
            inputs.append(data)
        return inputs

    def test_distinct_matched_originals_measure_terminal_delta_and_observed_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop, read = self.pair(Path(tmp))
            report = realization.observe_realization_pair(stop, read)
            self.assertEqual(
                [
                    report[k]
                    for k in (
                        "selected_text_changed",
                        "delivered_content_changed",
                        "terminal_quality_changed",
                        "read_minus_stop_quality",
                        "read_minus_stop_observed_latency_net",
                        "full_physical_net_difference",
                    )
                ],
                [True, True, True, 1.0, 0.98, None],
            )
            self.assertAlmostEqual(
                report["read_minus_stop_observed_latency_cost"], 0.02
            )
            self.assertFalse(report["policy_efficacy_proved"])

    def test_changed_frontier_source_tariff_or_reused_operation_cannot_claim_effect(
        self,
    ):
        for kind in (
            "source_sha256",
            "control_profile_sha256",
            "operation",
            "tariff",
            "frontier",
            "initial_packet",
            "missing_initial_packet",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                stop, read = self.pair(Path(tmp))
                if kind == "tariff":
                    read["tariff"] *= 2
                elif kind == "missing_initial_packet":
                    read["initial_public_input"] = None
                elif kind == "initial_packet":
                    directory = read["directory"]
                    path = directory / "initial-input.json"
                    initial = json.loads(path.read_bytes())
                    initial["observation"].update(
                        path="initial.png",
                        sha256=sha((directory / "public/initial.png").read_bytes()),
                    )
                    save(path, initial)
                    read["initial_public_input"] = common.binding(path, directory)
                    launch = json.loads((directory / "launch.json").read_bytes())
                    launch["host_exchanges"][0].update(
                        reply_sha256=read["initial_public_input"]["sha256"],
                        reply_bytes=read["initial_public_input"]["bytes"],
                    )
                    save(directory / "launch.json", launch)
                elif kind == "frontier":
                    steps = json.loads(
                        (read["directory"] / "trajectory.json").read_bytes()
                    )["steps"]
                    steps[0]["public_features"] = [0.123]
                    sync_steps(read["directory"], steps)
                else:
                    read["result"][
                        "original_operation_id" if kind == "operation" else kind
                    ] = (
                        stop["result"]["original_operation_id"]
                        if kind == "operation"
                        else "d" * 64
                    )
                    save(read["directory"] / "result.json", read["result"])
                with self.assertRaisesRegex(ValueError, "frontier"):
                    realization.observe_realization_pair(stop, read)

    def test_single_score_cannot_replace_missing_read_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            stop, read = self.pair(Path(tmp))
            read["result"]["terminal_status"] = "Unknown"
            save(read["directory"] / "result.json", read["result"])
            with self.assertRaises(ValueError):
                realization.observe_realization_pair(stop, read)

    def test_collector_keeps_initial_bytes_and_export_admits_the_original_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            output, context = collection(Path(tmp))
            directory = output / "p1-READ"
            final = (directory / "public-input.json").read_bytes()
            initial = json.loads(final)
            initial.update(step=0, forced_action="PREPARE_ROI")
            raw = common.json_bytes(initial)

            class Host:
                steps = []

                def public_step(self):
                    return raw if not self.steps else final

            host = Host()
            retain_finalizer_input(host, directory, "READ")
            self.assertEqual(host.public_step(), raw)
            retained = directory / "initial-public-input.json"
            self.assertEqual(retained.read_bytes(), raw)
            with self.assertRaises(FileExistsError):
                host.public_step()
            launch = json.loads((directory / "launch.json").read_bytes())
            launch["host_exchanges"][0].update(
                reply_sha256=sha(raw), reply_bytes=len(raw)
            )
            save(directory / "launch.json", launch)
            refresh(output)
            report = macro_training_pairs.export(
                output,
                expected_plan_sha256=sha((output / "PLAN.json").read_bytes()),
                context=context,
                expected_source_sha256=macro_training_pairs.source_sha256(),
                allow_fixtures=True,
            )
            self.assertEqual(report["exported_pairs"], 1)
            receipt = report["receipts"][
                report["rows"][0]["branches"]["READ"]["evidence_sha256"]
            ]
            observed = receipt["realization"]
            self.assertEqual(
                observed["optional_inputs"]["initial_public_input"],
                common.binding(retained, directory),
            )
            self.assertFalse(observed["read_attribution"]["observation_bytes_changed"])


if __name__ == "__main__":
    unittest.main()
