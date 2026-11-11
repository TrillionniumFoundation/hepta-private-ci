"""Manufactured native macro host; never scientific execution evidence."""

import json
from pathlib import Path
from .metacontrol_macro_contract import digest, sha


class FixtureHost:
    fail_read = wrong_initial = wrong_evaluator = False

    def __init__(self, config, case, profile, output, *, training, exploration):
        self.config, self.case, self.profile = config, case, profile
        self.output = Path(output)
        self.output.mkdir()
        self.public = self.output / "public"
        self.public.mkdir()
        self.observation = {
            "kind": "overview",
            "path": "overview.png",
            "sha256": "a" * 64,
            "bbox": [0, 0, 2, 2],
        }
        self.steps, self.actions, self.budget_stop = [], exploration, False

    def public_step(self):
        self.last_public = {"remaining_seconds": 60.0}
        return json.dumps(self.last_public).encode()

    def run(self):
        raw = self.public_step()
        if self.fail_read and "READ_ROI" in self.actions:
            (self.output / "result.json").write_text('{"terminal_status":"Failed"}')
            raise RuntimeError("Manufactured failed read")
        for action in self.actions:
            self.steps.append(
                {
                    "schema": "ndu.real.actor-observation.v1",
                    "case_id": self.case["id"],
                    "step": len(self.steps),
                    "action": {
                        "schema": "ndu.real.actor-action.v1",
                        "action": action,
                        "arguments": (
                            {"text": "fixture"} if action == "WRITE_TEXT" else {}
                        ),
                    },
                    "candidate_features": [[1.0]],
                    "candidate_metadata": [{"text": "fixture"}],
                    "public_features": [1.0],
                    "public_metadata": [
                        1.0
                        if not self.wrong_initial or action != "PREPARE_ROI"
                        else 2.0
                    ],
                    "remaining_seconds": json.loads(raw)["remaining_seconds"],
                    "memory_sha256": "b" * 64,
                    "weights_sha256": self.profile["model_sha256"],
                    "legal_actions": ["STOP", "WRITE_TEXT", "PREPARE_ROI"],
                    "parameters_unchanged": True,
                }
            )
            if action == "READ_ROI":
                self.observation = {
                    **self.observation,
                    "kind": "roi",
                    "path": "roi.png",
                }
            raw = self.public_step()
        (self.output / "trajectory.json").write_text(json.dumps({"steps": self.steps}))
        events = [
            {
                "schema": "ndu.real.actor-ready.v1",
                "case_id": self.case["id"],
                "weights_sha256": self.profile["model_sha256"],
            },
            *self.steps,
        ]
        wire = [json.dumps(e) for e in events]
        launch = {
            "schema": "ndu.real.actor-isolation.v1",
            "exit_code": 0,
            "enforced_before_actor_exec": True,
            "launcher_source_sha256": self.config["isolator_sha256"],
            "stdout": "\n".join(wire),
            "host_exchanges": [{"event_sha256": sha(s.encode())} for s in wire],
        }
        launch.update(getattr(self, "launch_changes", {}))
        (self.output / "launch.json").write_text(json.dumps(launch))
        d = self.output / f"delivery-{len(self.steps):02d}"
        d.mkdir()
        delivered = json.dumps({"case_id": self.case["id"], "text": "fixture"}).encode()
        (d / "delivery.json").write_bytes(delivered)
        evaluator = (
            "0" * 64 if self.wrong_evaluator else self.config["evaluator_sha256"]
        )
        score = {
            "case_id": self.case["id"],
            "quality": 0.5,
            "delivery_sha256": sha(delivered),
            "evaluator_source_sha256": evaluator,
            "rubric_sha256": self.config["rubric_sha256"],
        }
        (d / "evaluation.json").write_text(json.dumps(score))
        result = {
            "original_operation_id": self.profile["original_operation_id"],
            "terminal_status": "Completed",
            "actions": self.actions,
            "case_id": self.case["id"],
            "source_group_id": self.case["source_id"],
            "model_sha256": self.profile["model_sha256"],
            "score_components": score,
            "gross_score": 0.5,
            "rubric_sha256": self.config["rubric_sha256"],
            "output_text_sha256": digest("fixture"),
        }
        (self.output / "result.json").write_text(json.dumps(result))
        return result


def plan(root):
    pins = []
    for name, raw in [
        ("source.py", b"pass\n"),
        ("weights", b"fixture"),
        ("control.json", b'{"control":{"memory_mode":"reset"}}'),
    ]:
        p = root / name
        p.write_bytes(raw)
        pins.append({"path": str(p), "sha256": sha(raw)})
    return {
        "schema": "ndu.real.native-macro-pair-plan.v1",
        "source_splits": {"train": ["s"], "calibration": [], "future": []},
        "excluded_sources": [],
        "source_pins": [pins[0]],
        "config": {
            "episode_wall_seconds": 60.0,
            "isolator_sha256": "9" * 64,
            "evaluator_sha256": "e" * 64,
            "rubric_sha256": "f" * 64,
        },
        "profile": {
            "core": "ordinary",
            "memory_mode": "reset",
            "weights": pins[1]["path"],
            "model_sha256": pins[1]["sha256"],
            "control_plan": pins[2]["path"],
            "control_plan_sha256": pins[2]["sha256"],
        },
        "pairs": [
            {
                "pair_id": "p1",
                "split": "train",
                "case": {"source_id": "s", "role": "train", "id": "c"},
                "read_condition": "repeat",
                "seed": 2,
            }
        ],
        "action_budget_seconds": 10.0,
        "latency_tariff": 0.01,
    }
