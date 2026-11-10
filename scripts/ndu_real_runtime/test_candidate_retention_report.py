"""Evaluator fixtures: they verify attribution, never claim real actor benefit."""

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from ndu_real_materials.common import (
    binding,
    digest,
    json_bytes,
    strict_json,
    write_json,
)
from .candidate_retention_report import (
    EVENTS,
    REQUIRED_SOURCES,
    build_report,
    canonical_sha,
    evaluate_episode,
    generate,
    probability,
)


def candidate(text):
    return {"text": text, "bbox": [2, 2, 12, 8], "origin": "pixel_ocr"}


def fixture(mode="bounded", *, initial=None):
    profile = {
        "schema": "ndu.real.candidate-memory-profile.v1",
        "mode": mode,
        "max_entries": 128,
        "max_serialized_bytes": 2_000_000,
    }
    packet = {
        "case_id": "case",
        "source_size": {"width": 20, "height": 20},
        "requirements": {"text": True, "image": False},
        "initial_delivery": {"text": initial, "image": None},
    }
    expected = {
        "original_operation_id": "operation/" + mode,
        "case_id": "case",
        "source_group_id": "source",
        "episode_group": "episode",
        "split": "development",
        "source_sha256": "a" * 64,
        "source_width": 20,
        "source_height": 20,
        "weights_sha256": "b" * 64,
        "parameters_sha256": "c" * 64,
        "control_profile_sha256": "d" * 64,
        "public_case_sha256": hashlib.sha256(json_bytes(packet)).hexdigest(),
        "candidate_memory_profile": profile,
        "candidate_memory_profile_sha256": canonical_sha(profile),
    }
    reference = {
        "case_id": "case",
        "source_group": "source",
        "episode_group": "episode",
        "role": "development",
        "source_image": {"sha256": "a" * 64},
        "expected_text": "12.34",
        "field": "total",
        "target_boxes": [[2, 2, 12, 8]],
        "initial_commitment": {"text": initial, "image": None},
        "weights": {"text": 1.0, "image": 0.0},
    }
    actions = [
        ("PREPARE_ROI", {"bbox": [2, 2, 12, 8]}),
        ("READ_ROI", {}),
        ("WRITE_TEXT", {"text": "RM 12.34" if mode == "bounded" else "99.99"}),
        ("STOP", {}),
    ]
    audits, steps, previous = [], [], None
    for i, (name, arguments) in enumerate(actions):
        raw = [candidate("RM 12.34")] if i < 2 else [candidate("99.99")]
        offered = raw + (
            [candidate("RM 12.34")] if i == 2 and mode == "bounded" else []
        )
        processed = i != 3
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": name,
            "arguments": arguments,
        }
        audit = {
            "schema": "ndu.real.candidate-audit.v1",
            "scope": {
                "original_operation_id": expected["original_operation_id"],
                "case_id": "case",
                "source_image_sha256": "a" * 64,
                "source_width": 20,
                "source_height": 20,
            },
            "step": i,
            "profile": profile,
            "profile_sha256": canonical_sha(profile),
            **{
                k: expected[k]
                for k in (
                    "weights_sha256",
                    "parameters_sha256",
                    "control_profile_sha256",
                    "public_case_sha256",
                )
            },
            "observation": {
                "path": "overview.png",
                "sha256": "e" * 64,
                "bbox": [0, 0, 20, 20],
                "kind": "overview",
            },
            "observation_processed": processed,
            "raw_candidates": raw if processed else [],
            "offered_candidates": offered if processed else [],
            "raw_features_sha256": "f" * 64 if processed else None,
            "offered_features_sha256": "f" * 64 if processed else None,
            "offered_observed_steps": [i] + ([1] if len(offered) == 2 else [])
            if processed
            else [],
            "selected_index": len(offered) - 1 if processed else None,
            "action": action,
            "previous_audit_sha256": previous,
            "memory_receipt": None,
        }
        raw_audit = json_bytes(audit)
        previous = hashlib.sha256(raw_audit).hexdigest()
        audits.append({"value": audit, "sha256": previous, "bytes": len(raw_audit)})
        steps.append(
            {
                "action": action,
                "candidate_audit": {
                    "path": f"audit-{i}.json",
                    "sha256": previous,
                    "bytes": len(raw_audit),
                },
            }
        )
    initial_delivery = {
        "schema": "ndu.real.delivery.v1",
        "case_id": "case",
        "text": initial,
        "image": None,
    }
    final = {**initial_delivery, "text": actions[2][1]["text"]}
    score = {
        "text_quality": 1.0,
        "image_pass": False,
        "committed_output_preserved": True,
    }
    result = {
        **{
            k: expected[k]
            for k in (
                "original_operation_id",
                "case_id",
                "source_group_id",
                "episode_group",
                "split",
                "source_sha256",
                "control_profile_sha256",
                "candidate_memory_profile_sha256",
            )
        },
        "model_sha256": expected["weights_sha256"],
        "terminal_status": "Completed",
        "actions": [name for name, _ in actions],
        "output_text_sha256": canonical_sha(final["text"]),
    }
    return [
        expected,
        reference,
        packet,
        result,
        {"steps": steps},
        audits,
        {"initial": initial_delivery, "final": final},
        {
            "initial": {**score, "text_quality": float(initial is not None)},
            "final": {**score, "text_quality": float(mode == "bounded")},
        },
    ]


class CandidateRetentionReportTests(unittest.TestCase):
    def test_retained_candidate_at_final_write_has_separate_stage_counts(self):
        row = evaluate_episode(*fixture())
        self.assertEqual(
            [
                row[k]
                for k in (
                    "evidence_status",
                    "anchor_step",
                    "raw_observed",
                    "available",
                    "selected",
                    "candidate_mediated_delivered",
                    "unconditional_success",
                    "failure_stage",
                )
            ],
            ["VERIFIED", 2, True, True, True, True, True, "candidate_success"],
        )
        lost = evaluate_episode(*fixture("current_only"))
        self.assertEqual(
            [
                lost[k]
                for k in ("raw_observed", "available", "selected", "failure_stage")
            ],
            [True, False, False, "candidate_unavailable_at_decision"],
        )

    def test_initial_correct_stop_is_not_candidate_mediated(self):
        data = fixture(initial="12.34")
        audit = data[5][-1]["value"]
        audit.update(step=0, previous_audit_sha256=None)
        raw = json_bytes(audit)
        data[5] = [
            {
                "value": audit,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        ]
        data[4] = {
            "steps": [
                {
                    "action": audit["action"],
                    "candidate_audit": {k: data[5][0][k] for k in ("sha256", "bytes")},
                }
            ]
        }
        data[6]["final"] = data[6]["initial"]
        data[3].update(actions=["STOP"], output_text_sha256=canonical_sha("12.34"))
        row = evaluate_episode(*data)
        self.assertEqual(
            [
                row[k]
                for k in (
                    "no_op_success",
                    "candidate_mediated_delivered",
                    "unconditional_success",
                    "available",
                    "failure_stage",
                )
            ],
            [True, False, True, None, "initial_no_op_success"],
        )

    def test_selection_does_not_make_failed_or_unscored_delivery_correct(self):
        data = fixture()
        data[7]["final"]["text_quality"] = 0.0
        row = evaluate_episode(*data)
        self.assertEqual(
            [
                row[k]
                for k in ("selected", "candidate_mediated_delivered", "failure_stage")
            ],
            [True, False, "delivery_failure"],
        )
        data[7]["final"] = None
        row = evaluate_episode(*data)
        self.assertIsNone(row["unconditional_success"])
        self.assertIsNone(row["candidate_mediated_delivered"])
        data = fixture()
        data[3]["terminal_status"] = "Timeout"
        row = evaluate_episode(*data)
        self.assertTrue(row["final_content_correct"])
        self.assertFalse(row["unconditional_success"])

    def test_identity_and_unobserved_origin_mutations_are_rejected(self):
        for change in (
            lambda d: d[3].update(source_sha256="1" * 64),
            lambda d: d[5][1]["value"].update(weights_sha256="1" * 64),
            lambda d: d[5][1]["value"].update(parameters_sha256="1" * 64),
            lambda d: d[5][1]["value"].update(public_case_sha256="1" * 64),
            lambda d: d[5][2]["value"].update(offered_observed_steps=[2, 7]),
            lambda d: d[5][2]["value"].update(selected_index=True),
            lambda d: d[6]["final"].update(text="unbound"),
        ):
            data = fixture()
            change(data)
            row = evaluate_episode(*data)
            self.assertEqual(row["evidence_status"], "REJECTED")
            self.assertIsNone(row["unconditional_success"])

    def test_missing_evidence_and_zero_condition_keep_planned_denominators(self):
        data = fixture()
        data[5] = []
        row = evaluate_episode(*data)
        self.assertEqual(row["evidence_status"], "UNKNOWN")
        self.assertTrue(row["unconditional_success"])
        self.assertIsNone(row["available"])
        other = fixture("current_only")[0]
        report = build_report([data[0], other], [row])
        self.assertEqual(report["planned_episodes"], 2)
        unknown = report["panels"]["current_only/all_planned"]["p_available"]
        self.assertEqual(
            [unknown[k] for k in ("value", "denominator", "unknown_outcome", "bounds")],
            [None, 1, 1, [0.0, 1.0]],
        )
        self.assertEqual(
            probability(
                [{"available": False, "selected": False}], "selected", given="available"
            )["status"],
            "ZERO_DENOMINATOR",
        )
        with self.assertRaises(ValueError):
            build_report([data[0]], [row, row])

    def test_full_control_plan_cannot_change_while_control_subobject_matches(self):
        data = fixture()
        data[0]["control_plan_sha256"] = "1" * 64
        self.assertEqual(evaluate_episode(*data)["evidence_status"], "REJECTED")
        data[3]["control_plan_sha256"] = "1" * 64
        self.assertEqual(evaluate_episode(*data)["evidence_status"], "VERIFIED")
        data[3]["control_plan_sha256"] = "2" * 64
        self.assertEqual(evaluate_episode(*data)["evidence_status"], "REJECTED")

    def test_bound_generator_rescores_pixels_and_ignores_actor_claimed_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materials = root / "materials"
            materials.mkdir()
            Image.new("RGB", (20, 20), "white").save(materials / "source.png")
            source = binding(materials / "source.png", materials)
            data = [fixture("current_only"), fixture()]
            evidence, expected = [], []
            for pack in data:
                mode = pack[0]["candidate_memory_profile"]["mode"]
                target = root / mode
                target.mkdir()
                pack[0]["source_sha256"] = source["sha256"]
                pack[1]["source_image"] = source
                pack[3].update(source_sha256=source["sha256"], gross_score=1.0)
                previous = None
                for i, audit in enumerate(pack[5]):
                    audit["value"]["scope"]["source_image_sha256"] = source["sha256"]
                    audit["value"]["previous_audit_sha256"] = previous
                    path = target / f"audit-{i}.json"
                    write_json(path, audit["value"])
                    bound = binding(path, root)
                    previous = bound["sha256"]
                    pack[4]["steps"][i]["candidate_audit"] = bound
                item = {
                    "original_operation_id": pack[0]["original_operation_id"],
                    "audits": [
                        binding(target / f"audit-{i}.json", root)
                        for i in range(len(pack[5]))
                    ],
                }
                for key, value in (
                    ("result", pack[3]),
                    ("trajectory", pack[4]),
                    ("public_case", pack[2]),
                    ("initial_delivery", pack[6]["initial"]),
                    ("final_delivery", pack[6]["final"]),
                ):
                    path = target / (key + ".json")
                    write_json(path, value)
                    item[key] = binding(path, root)
                evidence.append(item)
                expected.append(pack[0])
            write_json(materials / "reference.json", data[0][1])
            write_json(materials / "rubric.json", {"version": 1})
            index = {
                "schema": "ndu.real.reference-index.v2",
                "case_roles": {"case": "development"},
                "cases": {"case": binding(materials / "reference.json", materials)},
                "rubric": binding(materials / "rubric.json", materials),
            }
            write_json(materials / "private/reference-index.v2.json", index)
            repository = Path(__file__).resolve().parents[2]
            source_pins = [
                binding(repository / name, repository)
                for name in sorted(REQUIRED_SOURCES)
            ]
            plan = {
                "schema": "ndu.real.candidate-retention-plan.v1",
                "episodes": expected,
                "source_pins": source_pins,
                "evaluator_sha256": binding(
                    repository / "scripts/ndu_real_materials/evaluator.py", repository
                )["sha256"],
                "reference_index_sha256": binding(
                    materials / "private/reference-index.v2.json", materials
                )["sha256"],
                "rubric_sha256": index["rubric"]["sha256"],
            }
            write_json(root / "PLAN.json", plan)
            plan_sha = binding(root / "PLAN.json", root)["sha256"]
            write_json(
                root / "EVIDENCE.json",
                {
                    "schema": "ndu.real.candidate-retention-evidence.v1",
                    "plan_sha256": plan_sha,
                    "episodes": evidence,
                },
            )
            manifest_sha = binding(root / "EVIDENCE.json", root)["sha256"]
            report = generate(root, materials, plan_sha, manifest_sha)
            self.assertEqual(
                [r["unconditional_success"] for r in report["episodes"]], [False, True]
            )
            self.assertTrue(
                all(r["evidence_status"] == "VERIFIED" for r in report["episodes"])
            )
            (root / "bounded/result.json").write_text("{}")
            report = generate(root, materials, plan_sha, manifest_sha)
            self.assertEqual(report["episodes"][1]["evidence_status"], "REJECTED")
            self.assertIsNone(report["episodes"][1]["unconditional_success"])


def campaign(root, damaged_artifact, value):
    """Write byte-bound original artifacts and real pixel-scoring inputs."""
    materials = root / "materials"
    materials.mkdir()
    Image.new("RGB", (20, 20), "white").save(materials / "source.png")
    source = binding(materials / "source.png", materials)
    episodes, evidence, references = [], [], {}
    for case_id in ("damaged", "healthy"):
        for mode in ("current_only", "bounded"):
            pack = fixture(mode)
            expected, reference, packet, result, trajectory, audits, deliveries, _ = (
                pack
            )
            expected.update(
                case_id=case_id,
                original_operation_id=case_id + "/" + mode,
                pair_id=case_id,
                source_group_id=case_id,
                episode_group=case_id,
                source_sha256=source["sha256"],
            )
            packet["case_id"] = case_id
            expected["public_case_sha256"] = digest(json_bytes(packet))
            reference.update(
                case_id=case_id,
                source_group=case_id,
                episode_group=case_id,
                source_image=source,
            )
            result.update(
                **{
                    key: expected[key]
                    for key in (
                        "case_id",
                        "original_operation_id",
                        "source_group_id",
                        "episode_group",
                        "source_sha256",
                    )
                }
            )
            for delivery in deliveries.values():
                delivery["case_id"] = case_id
            target = root / case_id / mode
            target.mkdir(parents=True)
            damaged = case_id == "damaged" and mode == "current_only"
            audit_bindings, previous = [], None
            for i, audit in enumerate(audits):
                body = audit["value"]
                body["scope"].update(
                    original_operation_id=expected["original_operation_id"],
                    case_id=case_id,
                    source_image_sha256=source["sha256"],
                )
                body.update(
                    public_case_sha256=expected["public_case_sha256"],
                    previous_audit_sha256=previous,
                )
                if damaged and damaged_artifact == "audit" and i == 0:
                    body = value
                path = target / f"audit-{i}.json"
                write_json(path, body)
                bound = binding(path, root)
                previous = bound["sha256"]
                trajectory["steps"][i]["candidate_audit"] = bound
                audit_bindings.append(bound)
            item = {
                "original_operation_id": expected["original_operation_id"],
                "audits": audit_bindings,
            }
            for name, body in (
                ("result", result),
                ("trajectory", trajectory),
                ("public_case", packet),
                ("initial_delivery", deliveries["initial"]),
                ("final_delivery", deliveries["final"]),
            ):
                if damaged and damaged_artifact == name:
                    body = value
                path = target / (name + ".json")
                write_json(path, body)
                item[name] = binding(path, root)
            if mode == "current_only":
                path = materials / (case_id + "-reference.json")
                body = (
                    value
                    if case_id == "damaged" and damaged_artifact == "reference"
                    else reference
                )
                write_json(path, body)
                references[case_id] = binding(path, materials)
            episodes.append(expected)
            evidence.append(item)
    write_json(materials / "rubric.json", {"version": 1})
    index = {
        "schema": "ndu.real.reference-index.v2",
        "case_roles": dict.fromkeys(references, "development"),
        "cases": references,
        "rubric": binding(materials / "rubric.json", materials),
    }
    write_json(materials / "private/reference-index.v2.json", index)
    repository = Path(__file__).resolve().parents[2]
    plan = {
        "schema": "ndu.real.candidate-retention-plan.v1",
        "episodes": episodes,
        "source_pins": [
            binding(repository / name, repository) for name in sorted(REQUIRED_SOURCES)
        ],
        "evaluator_sha256": binding(
            repository / "scripts/ndu_real_materials/evaluator.py", repository
        )["sha256"],
        "reference_index_sha256": binding(
            materials / "private/reference-index.v2.json", materials
        )["sha256"],
        "rubric_sha256": index["rubric"]["sha256"],
    }
    write_json(root / "PLAN.json", plan)
    plan_sha = binding(root / "PLAN.json", root)["sha256"]
    write_json(
        root / "EVIDENCE.json",
        {
            "schema": "ndu.real.candidate-retention-evidence.v1",
            "plan_sha256": plan_sha,
            "episodes": evidence,
        },
    )
    return materials, plan_sha, binding(root / "EVIDENCE.json", root)["sha256"]


class CandidateRetentionShapeTests(unittest.TestCase):
    def test_unreadable_audit_preserves_denominator_and_later_scoring(self):
        for failure in ("missing", "symlink"):
            with self.subTest(failure=failure):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    args = campaign(root, "unchanged", None)
                    audit = root / "damaged/current_only/audit-0.json"
                    original = audit.with_name("retained-audit-0.json")
                    audit.rename(original)
                    if failure == "symlink":
                        try:
                            audit.symlink_to(original.name)
                        except (NotImplementedError, OSError) as error:
                            self.skipTest(
                                "symbolic links are unavailable: " + str(error)
                            )
                    report = generate(root, *args)
                    rows = report["episodes"]
                    self.assertEqual(report["planned_episodes"], 4)
                    self.assertEqual(
                        rows[0]["evidence_status"],
                        "UNKNOWN" if failure == "missing" else "REJECTED",
                    )
                    self.assertEqual(
                        {key: rows[0][key] for key in EVENTS}, dict.fromkeys(EVENTS)
                    )
                    self.assertEqual(
                        [row["evidence_status"] for row in rows[1:]],
                        ["VERIFIED", "VERIFIED", "VERIFIED"],
                    )
                    self.assertEqual(
                        [row["unconditional_success"] for row in rows[2:]],
                        [False, True],
                    )

    def test_frozen_source_pin_mismatch_refuses_report_before_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            materials, _, _ = campaign(root, "audit", [])
            plan = strict_json((root / "PLAN.json").read_bytes())
            frozen = next(
                pin
                for pin in plan["source_pins"]
                if pin["path"].endswith("/candidate_retention_report.py")
            )
            frozen["sha256"] = digest(b"previously frozen reader source")
            # This is a separately bound incompatible plan, never a rewrite of
            # historical observations or a release of sealed evaluation data.
            plan_raw = json_bytes(plan)
            (root / "PLAN.json").write_bytes(plan_raw)
            manifest = strict_json((root / "EVIDENCE.json").read_bytes())
            manifest["plan_sha256"] = digest(plan_raw)
            manifest_raw = json_bytes(manifest)
            (root / "EVIDENCE.json").write_bytes(manifest_raw)
            with self.assertRaisesRegex(ValueError, "registered bytes"):
                generate(root, materials, digest(plan_raw), digest(manifest_raw))

    def test_recursive_untrusted_json_shape_substitutions_never_abort(self):
        def paths(value, prefix=()):
            children = (
                value.items()
                if isinstance(value, dict)
                else enumerate(value)
                if isinstance(value, list)
                else []
            )
            for key, child in children:
                path = prefix + (key,)
                yield path
                yield from paths(child, path)

        original = fixture()
        # The PLAN roster is authoritative. Only evidence inputs are replaced.
        for index in range(1, len(original)):
            for path in [()] + list(paths(original[index])):
                for value in ({}, [], None, 0, "malformed", True):
                    with self.subTest(input=index, path=path, value=value):
                        data = deepcopy(original)
                        if not path:
                            data[index] = value
                        else:
                            parent = data[index]
                            for key in path[:-1]:
                                parent = parent[key]
                            parent[path[-1]] = value
                        row = evaluate_episode(*data)
                        self.assertEqual(
                            row["original_operation_id"],
                            original[0]["original_operation_id"],
                        )
                        self.assertIn(
                            row["evidence_status"], {"VERIFIED", "UNKNOWN", "REJECTED"}
                        )

    def test_missing_trajectory_steps_remain_unknown(self):
        data = fixture()
        data[4] = {}
        row = evaluate_episode(*data)
        self.assertEqual(
            {
                key: row[key]
                for key in ("evidence_status", "available", "unconditional_success")
            },
            {
                "evidence_status": "UNKNOWN",
                "available": None,
                "unconditional_success": True,
            },
        )

    def test_malformed_episode_objects_and_nested_fields_are_rejected(self):
        mutations = [
            lambda data: data.__setitem__(1, []),
            lambda data: data.__setitem__(2, []),
            lambda data: data.__setitem__(3, []),
            lambda data: data.__setitem__(4, []),
            lambda data: data.__setitem__(5, {}),
            lambda data: data.__setitem__(6, []),
            lambda data: data.__setitem__(7, []),
            lambda data: data[3].update(terminal_status=[]),
            lambda data: data[1].update(source_image=[]),
            lambda data: data[2].update(requirements=[]),
            lambda data: data[2].update(initial_delivery=[]),
            lambda data: data[4].update(steps={}),
            lambda data: data[4]["steps"].__setitem__(0, []),
            lambda data: data[4]["steps"][0].update(action=[]),
            lambda data: data[4]["steps"][0]["action"].update(arguments=[]),
            lambda data: data[4]["steps"][0].update(candidate_audit=[]),
            lambda data: data[5].__setitem__(0, []),
            lambda data: data[5][0].update(value=[]),
            lambda data: data[5][0]["value"].update(raw_candidates=[None]),
            lambda data: data[5][0]["value"].update(offered_observed_steps={}),
            lambda data: data[6].update(final=[]),
            lambda data: data[7].update(final=[]),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                data = fixture()
                mutate(data)
                row = evaluate_episode(*data)
                self.assertEqual(row["evidence_status"], "REJECTED")
                self.assertEqual(
                    {key: row[key] for key in EVENTS}, dict.fromkeys(EVENTS)
                )

    def test_bound_bad_json_shapes_do_not_block_later_real_scoring(self):
        for artifact in (
            "reference",
            "public_case",
            "result",
            "trajectory",
            "audit",
            "initial_delivery",
            "final_delivery",
        ):
            for value in (None, [], 7, "malformed"):
                with self.subTest(artifact=artifact, value=value):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        args = campaign(root, artifact, deepcopy(value))
                        report = generate(root, *args)
                        rows = report["episodes"]
                        self.assertEqual(report["planned_episodes"], 4)
                        self.assertEqual(rows[0]["evidence_status"], "REJECTED")
                        self.assertEqual(
                            {key: rows[0][key] for key in EVENTS}, dict.fromkeys(EVENTS)
                        )
                        self.assertEqual(
                            [row["evidence_status"] for row in rows[2:]],
                            ["VERIFIED", "VERIFIED"],
                        )
                        self.assertEqual(
                            [row["unconditional_success"] for row in rows[2:]],
                            [False, True],
                        )
                        self.assertEqual(
                            report["panels"]["current_only/all_planned"]["p_available"][
                                "denominator"
                            ],
                            2,
                        )
                        self.assertEqual(
                            {
                                key: report[key]
                                for key in (
                                    "scientific_acceptance",
                                    "confirmatory_use",
                                    "production_adoption",
                                    "full_cost_adjusted",
                                )
                            },
                            {
                                "scientific_acceptance": "HOLD",
                                "confirmatory_use": False,
                                "production_adoption": False,
                                "full_cost_adjusted": False,
                            },
                        )


if __name__ == "__main__":
    unittest.main()
