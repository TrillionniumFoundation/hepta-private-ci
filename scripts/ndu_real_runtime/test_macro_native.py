"""Actual isolated OCR macros with fixture-trained control; no corpus efficacy."""

from dataclasses import replace
import json
from pathlib import Path
import sys
import unittest

from ndu_real_materials import isolate
from . import macro_actor, macro_realization
from .episode import EpisodeHost
from .metering import file_sha
from .metacontrol_macro_contract import SEQUENCES, digest
from . import test_content_identity_native as legacy_native
from .test_macro_actor import fixture_deployment
from .test_macro_policy import CONTEXT


@unittest.skipUnless(sys.platform == "linux", "requires native Linux actor isolation")
class NativeMacroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        legacy_native.NativeContentIdentityTests.setUpClass.__func__(cls)

    def profile_for(self, policy, name):
        from .neural import STATE_WIDTH

        context = replace(
            CONTEXT,
            encoder_sha256=self.profile["model_sha256"],
            answer_sha256=self.profile["model_sha256"],
            generator_sha256=file_sha(Path(macro_actor.__file__).with_name("ocr.py")),
            public_state_sha256=macro_actor.codec_sha256(),
            **macro_actor.host_context(self.config, self.host.utility_profile_sha256),
        )
        deployment = fixture_deployment(
            policy,
            width=STATE_WIDTH,
            weights=self.profile["model_sha256"],
            control=self.host.control_profile_sha256,
            context=context,
        )
        path = Path(self.temporary.name) / "model" / f"macro-{name}.json"
        path.write_text(json.dumps(deployment, sort_keys=True))
        return {
            **self.profile,
            "original_operation_id": f"fixture/native-macro/{name}",
            "macro_policy": {"path": str(path), "sha256": file_sha(path)},
        }

    def test_training_and_exploration_overrides_are_rejected_before_launch(self):
        for training in (False, True):
            name = f"override-{training}"
            profile = self.profile_for("STOP", name)
            directory = Path(self.temporary.name) / name
            with self.subTest(training=training), self.assertRaises(ValueError):
                EpisodeHost(
                    self.config,
                    self.case,
                    profile,
                    directory,
                    training=training,
                    exploration=("WRITE_TEXT", "STOP"),
                )
            self.assertFalse((directory / "launch.json").exists())

    def test_native_stop_and_read_reselect_deliver_and_score(self):
        for policy, macro in (("STOP", "STOP"), ("tuned-fixed", "READ")):
            with self.subTest(macro=macro):
                profile = self.profile_for(policy, macro)
                host = EpisodeHost(
                    self.config,
                    self.case,
                    profile,
                    Path(self.temporary.name) / f"macro-{macro}",
                )
                self.assertFalse(host.training)
                result = host.run()
                self.assertEqual(
                    result["terminal_status"], "Completed", result["error"]
                )
                self.assertEqual(result["actions"], SEQUENCES[macro])
                state_pin = digest(host.steps[0]["controller"]["macro_public_state"])
                self.assertEqual(
                    {
                        step["controller"]["macro_public_state_sha256"]
                        for step in host.steps
                    },
                    {state_pin},
                )
                self.assertTrue(host.launch["enforced_before_actor_exec"])
                self.assertEqual(host.launch["launch_receipt"]["network"], "DENY")
                ready = json.loads(host.launch["stdout"].splitlines()[0])
                self.assertEqual(
                    ready["macro_policy_sha256"], profile["macro_policy"]["sha256"]
                )
                index = SEQUENCES[macro].index("WRITE_TEXT")
                finalizer = host.steps[index]
                selection = finalizer["content_selection"]
                self.assertEqual(
                    finalizer["selected_candidate_index"], selection["selected_index"]
                )
                self.assertIs(type(host.steps[0]["selected_candidate_index"]), int)
                self.assertEqual(
                    selection["selected_candidate"],
                    finalizer["candidate_metadata"][selection["selected_index"]],
                )
                self.assertEqual(
                    selection["candidate_set_sha256"],
                    digest([digest(c) for c in finalizer["candidate_metadata"]]),
                )
                self.assertFalse(finalizer["ocr"]["annotations_read"])
                self.assertEqual(finalizer["ocr"]["exit_code"], 0)
                self.assertNotIn(
                    "never-disclose-this-reference-marker", host.launch["stdout"]
                )
                if macro == "READ":
                    self.assertEqual(
                        Path(finalizer["ocr"]["argv"][1]).name, "observed-01.png"
                    )
                    self.assertNotEqual(
                        file_sha(host.public / "overview.png"),
                        file_sha(host.public / "observed-01.png"),
                    )
                    self.assertEqual(
                        file_sha(host.actor_output / "ocr-02.tsv"),
                        finalizer["ocr"]["stdout_sha256"],
                    )
                snapshot = host.snapshots[-1]
                delivery = json.loads((snapshot / "delivery.json").read_text())
                score = json.loads((snapshot / "evaluation.json").read_text())
                self.assertEqual(
                    delivery["text"], selection["selected_candidate"]["text"]
                )
                self.assertEqual(
                    score["delivery_sha256"], file_sha(snapshot / "delivery.json")
                )
                self.assertEqual(result["score_components"], score)
                self.assertEqual(
                    result, json.loads((host.output / "result.json").read_text())
                )
                observed = macro_realization.observe_realization(
                    host.output,
                    result,
                    macro,
                    result["deployment_meter"]["wall_seconds"],
                    self.config["latency_weight"],
                    {
                        **self.config,
                        "isolator_sha256": file_sha(Path(isolate.__file__)),
                    },
                    expected_source_sha256=digest(macro_realization.source_manifest()),
                )
                self.assertTrue(observed["stages"]["selection"]["selected_used"])
                self.assertTrue(observed["stages"]["execution"]["scored"])
                self.assertFalse(observed["full_physical_cost_observed"])
                self.assertFalse(observed["policy_efficacy_evaluated"])


if __name__ == "__main__":
    unittest.main()
