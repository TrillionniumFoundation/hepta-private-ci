"""Manufactured source-bound collection fixtures; never execution evidence."""

from dataclasses import asdict
import json
from pathlib import Path

from ndu_real_materials import common, evaluator
from .controllers import ControlPlan
from .critic_context import CriticContext
from .macro_actor import codec_sha256, host_context
from .macro_policy import ACTION_SHA256
from .metacontrol_macro_contract import SEQUENCES, digest, observe_branch, sha
from .objective import utility_profile
from .test_macro_pair_fixtures import plan as base_plan
from .test_macro_realization import fixture, save, sync_steps


def read(path):
    return json.loads(path.read_bytes())


def collection(root, *, modern=True):
    plan = base_plan(root)
    output, material = root / "collection", root / "materials"
    output.mkdir()
    (material / "private").mkdir(parents=True)
    (material / "source.bin").write_bytes(b"manufactured registered source")
    (material / "rubric.json").write_bytes(b'{"fixture":true}\n')
    reference = {
        "case_id": "c",
        "source_group": "s",
        "episode_group": "e",
        "role": "train",
        "field": "company",
        "expected_text": "ACME LTD",
        "source_image": common.binding(material / "source.bin", material),
    }
    save(material / "private/reference.json", reference)
    reference_pin = common.binding(material / "private/reference.json", material)
    index = {
        "schema": "ndu.real.reference-index.v2",
        "case_roles": {"c": "train"},
        "cases": {"c": reference_pin},
        "rubric": common.binding(material / "rubric.json", material),
    }
    save(material / "private/reference-index.v2.json", index)
    config = plan["config"]
    config.update(
        material_root=str(material),
        latency_weight=0.01,
        reference_index_sha256=sha(
            (material / "private/reference-index.v2.json").read_bytes()
        ),
        evaluator_sha256=sha(Path(evaluator.__file__).read_bytes()),
        rubric_sha256=index["rubric"]["sha256"],
        scripts_root=str(Path(__file__).resolve().parents[1]),
        repository_root=str(Path(__file__).resolve().parents[2]),
    )
    control = ControlPlan()
    save(
        root / "control.json",
        {
            "control": asdict(control),
            "episode_wall_seconds": 60.0,
            "fixed_schedule": [],
            "seed": 7,
        },
    )
    plan["profile"]["control_plan_sha256"] = sha((root / "control.json").read_bytes())
    pair = plan["pairs"][0]
    pair.update(read_condition="original")
    pair["case"].update(reference=reference_pin, episode_group="e")
    utility, control_sha = digest(utility_profile(control)), digest(asdict(control))
    context = CriticContext(
        encoder_sha256=plan["profile"]["model_sha256"],
        answer_sha256=plan["profile"]["model_sha256"],
        generator_sha256=sha(Path(__file__).with_name("ocr.py").read_bytes()),
        public_state_sha256=codec_sha256(),
        action_sha256=ACTION_SHA256,
        **host_context(config, utility),
    )
    branches = {}
    for i, macro in enumerate(SEQUENCES):
        staging = root / macro
        staging.mkdir()
        data = fixture(staging, macro=macro, selected_index=1 - i, modern=modern)
        directory = output / ("p1-" + macro)
        data["directory"].rename(directory)
        result = data["result"]
        score = result["score_components"]
        score.update(
            reference_sha256=reference_pin["sha256"],
            episode_group="e",
            rubric_sha256=config["rubric_sha256"],
        )
        profile = {
            "utility_profile_sha256": utility,
            "control_profile_sha256": control_sha,
            "memory_mode": "reset",
        }
        result.update(plan["profile"])
        result.update(
            **profile,
            original_operation_id="p1/" + macro,
            episode_group="e",
            split="train",
            utility_profile=utility_profile(control),
            source_sha256=reference["source_image"]["sha256"],
            control_plan_sha256=plan["profile"]["control_plan_sha256"],
            rubric_sha256=config["rubric_sha256"],
        )
        save(directory / f"delivery-{len(SEQUENCES[macro]):02d}/evaluation.json", score)
        save(directory / "result.json", result)
        launch = read(directory / "launch.json")
        ready = json.loads(launch["stdout"].splitlines()[0])
        ready.update(profile)
        launch["stdout"] = (
            json.dumps(ready) + "\n" + "\n".join(launch["stdout"].splitlines()[1:])
        )
        save(directory / "launch.json", launch)
        steps = read(directory / "trajectory.json")["steps"]
        for step in steps:
            step.update(
                profile,
                remaining_seconds=10.0,
                public_metadata=[1.0, 0.0, 0.0, 0.0] + [0.0] * 12,
            )
        sync_steps(directory, steps)
        branch = observe_branch(
            directory, result, SEQUENCES[macro], 0.2 + i, 0.01, config
        )
        branch.update(
            status="completed",
            read_packet_sha256=None,
            artifact_sha256s={
                n: sha((directory / n).read_bytes())
                for n in ("result.json", "launch.json", "trajectory.json")
            },
        )
        branches[macro] = branch
    summary = {
        "schema": "ndu.real.native-macro-pair.v1",
        "pair_id": "p1",
        "split": "train",
        "source_group": "s",
        "read_condition": "original",
        "branches": branches,
        "evidence_kind": "fixture",
        "status": "completed",
        "initial_public_state_matched": True,
        "plan_sha256": digest(plan),
    }
    save(output / "p1.json", summary)
    save(output / "PLAN.json", plan)
    return output, context


def refresh(output, *, update_plan=False):
    summary = read(output / "p1.json")
    for macro in SEQUENCES:
        directory = output / ("p1-" + macro)
        summary["branches"][macro]["artifact_sha256s"] = {
            n: sha((directory / n).read_bytes())
            for n in ("result.json", "launch.json", "trajectory.json")
        }
    if update_plan:
        summary["plan_sha256"] = digest(read(output / "PLAN.json"))
    save(output / "p1.json", summary)
