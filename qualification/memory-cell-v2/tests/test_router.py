"""Development-only router checks; seeds 8001/8003, no frozen evaluation data."""

import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

from v2.router import RouteRequest, Router, RouteSpec


SPECS = (
    RouteSpec("knowledge", "semantic", ("fact bank",)),
    RouteSpec("experience", "episodic", ("episode log",)),
    RouteSpec("procedures", "procedural", ("action guide",)),
)
CUES = {
    "knowledge": ("attribute", "property"),
    "experience": ("occurrence", "chronology"),
    "procedures": ("recipe", "instruction"),
    None: ("weather", "forecast"),
}


def training(seed=8001):
    rng = random.Random(seed)
    texts, labels, families = [], [], []
    templates = (
        "Retrieve the {cue} for item:{key}.",
        "Please consult {cue}; handle key:{key}.",
        "I need {cue} associated with record:{key}.",
    )
    for index, template in enumerate(templates):
        for label, cues in CUES.items():
            for cue in cues:
                for repeat in range(3):
                    key = f"{rng.getrandbits(32):08x}{repeat:02d}"
                    texts.append(template.format(cue=cue, key=key))
                    labels.append(label)
                    families.append(f"development-wording-{index}")
    return texts, labels, families


class RouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = Router(SPECS, seed=8001)
        texts, labels, families = training()
        cls.receipt = cls.router.fit(texts, labels, families=families)

    def test_learned_rephrasing_uses_cues_not_templates_or_random_keys(self):
        rng = random.Random(8003)
        requests, expected = [], []
        for label, cues in CUES.items():
            for cue in cues:
                for template in (
                    "Given ticket:{key}, explain its {cue} now.",
                    "Could a {cue} be retrieved? ticket:{key} awaits.",
                ):
                    key = f"{rng.getrandbits(64):016x}007"
                    requests.append(RouteRequest(template.format(cue=cue, key=key)))
                    expected.append(label)
        actual = self.router.route(requests, mode="learned")
        self.assertEqual([item.route_id for item in actual], expected)
        self.assertEqual(
            [item.route_id for item in self.router.route(requests, mode="literal")],
            [None] * len(requests),
        )
        self.assertLess(self.receipt["final_loss"], self.receipt["initial_loss"] / 10)
        self.assertFalse(self.receipt["calibrated"])
        self.assertEqual(self.receipt["optimizer_steps"], 600)
        self.assertFalse(
            any(
                any(char.isdigit() for char in token)
                for token in self.router.vocabulary
            )
        )

    def test_typed_route_and_public_schema_aliases(self):
        requests = [
            RouteRequest("key:a10", cell_type="semantic"),
            RouteRequest("key:a20", cell_type="unknown"),
            RouteRequest("key:a30", scope="production", cell_type="episodic"),
        ]
        self.assertEqual(
            [item.route_id for item in self.router.route(requests, "typed")],
            ["knowledge", None, None],
        )
        requests = [
            RouteRequest("scope:research type:episodic key:a10"),
            RouteRequest("Use the FACT BANK for key:a20"),
            RouteRequest("action guide, key:a30 please"),
            RouteRequest("domain:knowledge key:a40"),
        ]
        self.assertEqual(
            [item.route_id for item in self.router.route(requests, "literal")],
            ["experience", "knowledge", "procedures", "knowledge"],
        )

    def test_unknown_scope_type_and_ambiguous_addresses_abstain(self):
        requests = [
            RouteRequest("scope:production attribute"),
            RouteRequest("type:imaginary property"),
            RouteRequest("domain:unregistered attribute"),
            RouteRequest("fact bank and episode log"),
            RouteRequest("type:semantic action guide"),
            RouteRequest("type:"),
        ]
        for mode in ("literal", "learned"):
            with self.subTest(mode=mode):
                actual = self.router.route(requests, mode)
                self.assertEqual(
                    [item.route_id for item in actual], [None] * len(requests)
                )
                self.assertEqual(
                    [item.reason for item in actual],
                    [
                        "unknown_scope",
                        "unknown_type",
                        "unknown_route",
                        "ambiguous_address",
                        "ambiguous_address",
                        "malformed_declaration",
                    ],
                )
        actual = self.router.route(
            [
                RouteRequest("attribute chronology"),
                RouteRequest("zebra xylophone key:111"),
            ]
        )
        self.assertEqual(
            [item.reason for item in actual],
            ["ambiguous_learned_evidence", "no_learned_evidence"],
        )

    def test_literal_terminal_period_does_not_admit_identifier_prefixes(self):
        texts = [
            "Read semantic.",
            "Consult the fact bank. Then stop.",
            "Use procedures.",
            "Read semantic.foo",
            "Read semantic-extra",
            "Read presemantic",
        ]
        decisions = self.router.route([RouteRequest(text) for text in texts], "literal")
        self.assertEqual(
            [d.route_id for d in decisions],
            ["knowledge", "knowledge", "procedures", None, None, None],
        )

    def test_learned_never_reads_explicit_type_or_external_target(self):
        requests = [
            RouteRequest("property ticket:202", cell_type=value)
            for value in (None, "semantic", "episodic", "unknown")
        ]
        decisions = self.router.route(requests)
        self.assertEqual(decisions, [decisions[0]] * len(requests))
        self.assertEqual(decisions[0].route_id, "knowledge")
        with self.assertRaises(TypeError):
            RouteRequest("property", target="knowledge")
        with self.assertRaises(ValueError):
            self.router.route([{"text": "property", "domain": "knowledge"}])

    def test_shared_type_requires_an_unambiguous_address(self):
        router = Router(
            (
                RouteSpec("alpha", "semantic"),
                RouteSpec("beta", "semantic"),
                RouteSpec("episodes", "episodic"),
            )
        )
        requests = [
            RouteRequest("type:semantic"),
            RouteRequest("type:semantic domain:alpha"),
            RouteRequest("type:episodic domain:alpha"),
        ]
        self.assertEqual(
            [item.route_id for item in router.route(requests, "literal")],
            [None, "alpha", None],
        )
        requests = [
            RouteRequest("key:a123", cell_type="semantic"),
            RouteRequest("domain:beta key:a123", cell_type="semantic"),
        ]
        self.assertEqual(
            [item.route_id for item in router.route(requests, "typed")], [None, "beta"]
        )

    def test_template_confounded_or_single_family_training_rejected(self):
        texts, labels, families = training()
        for bad_families in (["one"] * len(families), [str(label) for label in labels]):
            with (
                self.subTest(families=set(bad_families)),
                self.assertRaises(ValueError),
            ):
                Router(SPECS).fit(texts, labels, families=bad_families)
        with self.assertRaises(ValueError):
            Router(SPECS).fit(texts, ["unregistered"] * len(labels), families=families)

    def test_serialized_weights_read_in_fresh_process(self):
        requests = [
            RouteRequest("attribute ticket:330"),
            RouteRequest("chronology ticket:331"),
            RouteRequest("recipe ticket:332"),
            RouteRequest("weather ticket:333"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "router"
            manifest = self.router.save(path)
            loaded = Router.load(path, expected_scope="research")
            self.assertEqual(loaded.route(requests), self.router.route(requests))
            self.assertEqual(loaded.manifest(), manifest)
            self.assertEqual(manifest["parameter_bytes"], self.router.weights.nbytes)
            script = (
                "import json,os,sys; sys.path.insert(0,sys.argv[1]); "
                "from v2.router import Router,RouteRequest; "
                "router=Router.load(sys.argv[2],expected_scope='research'); "
                "queries=[RouteRequest(text) for text in json.loads(sys.argv[3])]; "
                "print(json.dumps({'pid':os.getpid(),'routes':[x.route_id for x in router.route(queries)]}))"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    script,
                    str(Path(__file__).resolve().parents[1]),
                    str(path),
                    json.dumps([item.text for item in requests]),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            fresh = json.loads(completed.stdout)
            self.assertNotEqual(fresh["pid"], os.getpid())
            self.assertEqual(
                fresh["routes"], ["knowledge", "experience", "procedures", None]
            )
            self.assertNotIn("texts", manifest)

    def test_corrupt_incomplete_extra_and_wrong_scope_artifacts_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for scenario in ("missing", "extra", "weights", "manifest", "scope"):
                path = Path(tmp) / scenario
                self.router.save(path)
                if scenario == "missing":
                    (path / "weights.npy").unlink()
                elif scenario == "extra":
                    (path / "samples.json").write_text("[]", encoding="utf-8")
                elif scenario == "weights":
                    blob = bytearray((path / "weights.npy").read_bytes())
                    blob[-1] ^= 1
                    (path / "weights.npy").write_bytes(blob)
                elif scenario == "manifest":
                    manifest = json.loads(
                        (path / "router.json").read_text(encoding="utf-8")
                    )
                    manifest["threshold"] = 0.5
                    (path / "router.json").write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                    Router.load(
                        path,
                        expected_scope="production"
                        if scenario == "scope"
                        else "research",
                    )

    def test_rules_can_reload_without_claiming_a_trained_model(self):
        router = Router(SPECS, seed=8003)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules"
            router.save(path)
            loaded = Router.load(path, expected_scope="research")
            self.assertEqual(
                loaded.route([RouteRequest("fact bank")], "literal")[0].route_id,
                "knowledge",
            )
            with self.assertRaises(ValueError):
                loaded.route([RouteRequest("attribute")])


if __name__ == "__main__":
    unittest.main()
