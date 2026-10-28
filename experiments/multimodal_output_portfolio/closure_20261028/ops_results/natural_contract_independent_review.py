"""Run actual source guard methods with small, isolated dependency fixtures.

This is a source-contract regression review, not model, native owner, media codec,
or semantic qualification. The methods are compiled unchanged from the reviewed
repository AST so these fixtures do not reproduce their guard implementation.
"""
import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest


def digest(value):
    payload = value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def extract(path, name, namespace, owner=None):
    tree = ast.parse(path.read_text(), filename=str(path))
    body = tree.body
    if owner:
        body = next(node.body for node in body
                    if isinstance(node, ast.ClassDef) and node.name == owner)
    function = next(node for node in body
                    if isinstance(node, ast.FunctionDef) and node.name == name)
    namespace = dict(namespace)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write("\n")


class TensorFixture:
    def detach(self): return self
    def cpu(self): return self
    def contiguous(self): return self
    def numpy(self): return self
    def tobytes(self): return b"unchanged tensor bytes"


class GuardReview(unittest.TestCase):
    package = None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {"Path": Path, "json": json, "hashlib": hashlib,
                            "digest": digest, "sha": lambda p: digest(Path(p).read_bytes())}

    def episode_fixture(self):
        ontology = {"action": {"1": "open", "2": "close"},
                    "sound": {"3": "quiet", "4": "loud"}}
        parameter_sha = digest(b"weight" + TensorFixture().tobytes())
        model = SimpleNamespace(ontology=copy.deepcopy(ontology), action_ids=[1, 2],
                                sound_ids=[3, 4], parameter_sha=parameter_sha)
        state = {"ontology": copy.deepcopy(ontology), "model": {"weight": TensorFixture()},
                 "parameter_sha256": parameter_sha, "emission_law": {"fixed": True}}
        judge = SimpleNamespace(ontology=copy.deepcopy(ontology), ontology_sha256=digest(ontology),
                                bindings={"source_protocol_sha256": "frozen-source"})
        checkpoint = self.root / "checkpoint.bin"
        checkpoint.write_bytes(b"physical checkpoint fixture")
        called = []

        def executed(**kwargs):
            called.append(kwargs)
            return None, .25, {"samples": []}

        adapter = lambda **kwargs: SimpleNamespace(prepare=None, emit=None, terminal_score=None)
        namespace = {**self.environment, "io": io, "cpu_seconds": lambda: 0.,
                     "torch": SimpleNamespace(load=lambda *a, **k: state, no_grad=contextlib.nullcontext),
                     "parameter_hash": lambda item: item.parameter_sha, "LAW": {"fixed": True},
                     "QualifiedNaturalPort": adapter, "execute_episode": executed}
        complete = extract(self.package / "natural_episode.py", "complete", namespace, "EpisodeRunner")
        runner = SimpleNamespace(judge=judge, tsm=None, pann=None, paths=[],
                                 profile=SimpleNamespace(digest="fixed-profile", observer_sha256="fixed-observer"),
                                 binary=self.root / "owner", owner=self.root,
                                 budget=None, prices=None)
        arguments = dict(model=model, checkpoint=checkpoint, event_directory=self.root,
                         seed=7, route="stochastic", actor=SimpleNamespace(digest="frozen-actor"),
                         output=self.root, case="fixture")
        return complete, runner, arguments, state, called

    def test_valid_vocabulary_reaches_execution_with_bound_identity(self):
        complete, runner, args, _, called = self.episode_fixture()
        _, _, receipt = complete(runner, **args)
        self.assertEqual(len(called), 1)
        binding = receipt["complete_policy_binding"]
        self.assertEqual(binding["task_ontology_sha256"], runner.judge.ontology_sha256)
        self.assertEqual(binding["action_ids"], [1, 2])
        self.assertEqual(binding["sound_ids"], [3, 4])

    def test_model_and_checkpoint_cannot_rewrite_reward_vocabulary_together(self):
        complete, runner, args, state, called = self.episode_fixture()
        args["model"].ontology["action"]["1"] = "rewritten label"
        state["ontology"] = copy.deepcopy(args["model"].ontology)
        with self.assertRaisesRegex(ValueError, "frozen task vocabulary"):
            complete(runner, **args)
        self.assertEqual(called, [])
        self.assertEqual(runner.judge.ontology["action"]["1"], "open")

    def test_category_order_change_rejected_before_execution(self):
        complete, runner, args, _, called = self.episode_fixture()
        args["model"].action_ids = [2, 1]
        with self.assertRaisesRegex(ValueError, "frozen task vocabulary"):
            complete(runner, **args)
        self.assertEqual(called, [])

    def test_scoring_rejects_a_mutated_independent_ontology(self):
        ontology = {"action": {"1": "open"}, "sound": {"2": "quiet"}}
        pin = digest(ontology)
        judge = SimpleNamespace(ontology=copy.deepcopy(ontology), ontology_sha256=pin)
        model = SimpleNamespace(ontology=copy.deepcopy(ontology))
        judge.ontology["action"]["1"] = "changed"
        port = SimpleNamespace(model=model, judge=judge, prepared_binding="unchanged")
        terminal = extract(self.package / "semantic_terminal.py", "terminal_score",
                           {**self.environment, "parameter_hash": lambda _: "unchanged"},
                           "QualifiedNaturalPort")
        with self.assertRaisesRegex(ValueError, "independent task ontology changed"):
            terminal(port, {})

    def test_initialize_rejects_even_partial_access_to_either_holdout(self):
        initialize = extract(self.package / "natural_study.py", "initialize", self.environment, "Study")
        for role in ("policy_calibration", "qualification"):
            with self.subTest(role=role):
                assets = self.root / role
                (assets / "prepared" / role / "partially-accessed-source").mkdir(parents=True)
                study = SimpleNamespace(assets=assets, output=self.root / (role + "-output"))
                with self.assertRaisesRegex(ValueError, "accessed before"):
                    initialize(study)
                self.assertFalse((study.output / "PROTOCOL.json").exists())

    def heldout_fixture(self, matching):
        output, assets = self.root / "study", self.root / "assets"
        output.mkdir()
        source = {"protocol_sha256": "frozen-source"}
        freeze_path = output / "POLICY_FREEZE.json"
        save(freeze_path, {"schema": "hepta.closure.natural-policy-freeze.v1",
                           "source_protocol_sha256": "frozen-source",
                           "independent_observer_adequate": True, "frozen_files": []})
        directory = assets / "prepared" / "policy_calibration" / "source"
        directory.mkdir(parents=True)
        save(directory / "RECEIPT.json", {"heldout_freeze_sha256":
                                          digest(freeze_path.read_bytes()) if matching else "old-freeze"})
        reached = []

        def rows(*args):
            reached.append(args)
            raise LookupError("guard passed; stop before dataset access")

        validate = extract(self.package / "data_prepare_v2.py", "validate_freeze",
                           {**self.environment, "TRAIN_ROLES": ("generator_train", "observer_train", "development")})
        heldout = extract(self.package / "natural_study.py", "heldout",
                          {**self.environment, "validate_freeze": validate, "generator_rows": rows}, "Study")
        return heldout, SimpleNamespace(output=output, assets=assets, source=source), reached

    def test_holdout_receipt_from_another_freeze_is_rejected_before_rows(self):
        heldout, study, reached = self.heldout_fixture(False)
        with self.assertRaisesRegex(ValueError, "another policy freeze"):
            heldout(study, "policy_calibration")
        self.assertEqual(reached, [])

    def test_same_holdout_freeze_can_reach_source_loading(self):
        heldout, study, reached = self.heldout_fixture(True)
        with self.assertRaisesRegex(LookupError, "stop before dataset access"):
            heldout(study, "policy_calibration")
        self.assertEqual(len(reached), 1)

    def test_failed_first_emission_then_success_preserves_physical_evidence(self):
        media = self.root / "failed-first.mkv"
        media.write_bytes(b"partial physical output")
        receipt = {"terminal_kind": "delivered", "host_refusals": [],
                   "cpu_admission_threshold_exceeded": False,
                   "emissions": [{"terminal_kind": "failed", "failure": {"kind": "codec"}},
                                 {"terminal_kind": "delivered"}]}
        release = extract(self.package / "natural_gradient.py", "release_training_media",
                          {**self.environment, "save": save})
        result = release(self.root, receipt, False)
        self.assertTrue(result["retained"])
        self.assertEqual(media.read_bytes(), b"partial physical output")

    def test_ordinary_release_removes_only_verified_own_media(self):
        media = self.root / "clean.png"
        media.write_bytes(b"clean physical fixture")
        untouched = self.root / "not-media.json"
        untouched.write_bytes(b"do not remove")
        artifacts = {"artifact_refs": {"image": str(media)},
                     "artifact_sha256": {"image": digest(media.read_bytes())}}
        receipt = {"terminal_kind": "delivered", "host_refusals": [],
                   "cpu_admission_threshold_exceeded": False,
                   "emissions": [{"terminal_kind": "delivered"}],
                   "native_execution": {"initial": artifacts, "final": artifacts}}
        save(self.root / "EPISODE.json", receipt)
        release = extract(self.package / "natural_gradient.py", "release_training_media",
                          {**self.environment, "save": save})
        result = release(self.root, receipt, False)
        self.assertFalse(result["retained"])
        self.assertFalse(media.exists())
        self.assertEqual(untouched.read_bytes(), b"do not remove")
        self.assertTrue((self.root / "EPISODE.json").exists())
        self.assertTrue((self.root / "MEDIA_RELEASE.json").exists())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    GuardReview.package = args.repo / "experiments/multimodal_output_portfolio/closure_20261028"
    names = ("natural_episode.py", "semantic_terminal.py", "natural_gradient.py", "natural_study.py",
             "natural_port.py", "data_prepare_v2.py")
    pins = {name: digest((GuardReview.package / name).read_bytes()) for name in names}
    stream = io.StringIO()
    started = time.monotonic()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(GuardReview))
    unchanged = pins == {name: digest((GuardReview.package / name).read_bytes()) for name in names}
    report = {"schema": "hepta.closure.natural-contract-independent-review.v1",
              "source_sha256": pins, "source_unchanged_during_review": unchanged,
              "review_source_sha256": digest(Path(__file__).read_bytes()),
              "tests_run": result.testsRun, "tests_passed": result.wasSuccessful(),
              "elapsed_seconds": time.monotonic() - started, "test_output": stream.getvalue(),
              "method": "Unchanged actual AST methods, isolated dependency fixtures; standard library only.",
              "scope": "Vocabulary identity, heldout reuse rejection, recovered-failure evidence retention.",
              "not_executed": ["Torch model", "original native owner", "real media delivery", "qualification source access"],
              "remaining_limitations": ["Physical timing conditional-exogeneity is not established by these guards.",
                  "No strict bounded future CPU or NDU-tail certificate.",
                  "Base NaturalPort reconstruction scorer is a legacy mechanism; new study exclusively uses QualifiedNaturalPort.",
                  "Natural efficacy, semantic adequacy and real replay parity await their separate registered execution."]}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(stream.getvalue(), end="")
    print(json.dumps({"report": str(args.output), "sha256": digest(args.output.read_bytes()),
                      "source_unchanged": unchanged}))
    raise SystemExit(0 if result.wasSuccessful() and unchanged else 1)


if __name__ == "__main__":
    main()
