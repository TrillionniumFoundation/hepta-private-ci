"""Execute the actual closed normal-peer function without Root bootstrap imports."""

import ast
import json
import os
from pathlib import Path
import re
import socket
import struct
import unittest
from unittest.mock import patch

import fixed_encoder_resources


def source_function(name):
    program = Path(__file__).with_name("hepta_fixed_nomic_encoder.py")
    parsed = ast.parse(program.read_text())
    selected = [
        item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name in (name, "process_identity")
    ]
    namespace = {
        "Path": Path,
        "socket": socket,
        "struct": struct,
        "re": re,
        "verify_large_source": lambda *_: None,
        "source_bytes": lambda source, _: json.dumps(source).encode(),
        "decode_json": json.loads,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(program), "exec"), namespace)
    return namespace[name]


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.authorize = source_function("authorize_current")
        _, uids, gids, cgroup = self.authorize.__globals__["process_identity"](os.getpid())
        self.request = {
            "pair_id": "public.one",
            "source_row_sha256": "a" * 64,
            "body_digest": "b" * 64,
            "objective_digest": "c" * 64,
            "model_generation": 1,
            "run_id": "run:goal.one",
            "ndu_digest": "d" * 64,
        }
        body = {"runtime_body_digest": "b" * 64, "agent_id": "actual.agent", "body_generation": 1}
        self.principal = {
            **{key: value for key, value in self.request.items() if key != "ndu_digest"},
            "agent_id": "actual.agent",
            "uid": uids[0],
            "gid": gids[0],
            "cgroup": cgroup,
            "fleet_manifest_digest": "e" * 64,
            "program_source": {},
            "body_sources": [body],
        }

    def call(self, schema, principal, request):
        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(fixed_encoder_resources, "observe", return_value=("actual.root.resource",)) as observe,
        ):
            result = self.authorize(left, {"schema": schema, "principals": [principal]}, request)
            self.assertEqual(result[0], os.getpid())
            self.assertEqual(observe.call_args.args[2], os.getpid())
            self.assertEqual(observe.call_args.args[1]["fleet_manifest_digest"], "e" * 64)
            return result

    def test_explicit_goal_mode_accepts_two_actual_stages_same_model_and_kernel_peer(self):
        principal = {key: value for key, value in self.principal.items() if key not in ("objective_digest", "run_id")}
        principal["goal_scope_mode"] = "ActualCompiledGoalScopeV3"
        first = self.call("hepta.fixed-nomic-encoder.v3", principal, self.request)
        second = self.call(
            "hepta.fixed-nomic-encoder.v3",
            principal,
            {
                **self.request,
                "objective_digest": "f" * 64,
                "run_id": "run:goal.two",
                "ndu_digest": "1" * 64,
            },
        )
        self.assertEqual(first, second)

    def test_original_v2_still_rejects_another_goal_and_cannot_opt_into_v3(self):
        self.call("hepta.fixed-nomic-encoder.v2", self.principal, self.request)
        with self.assertRaises(ValueError):
            self.call(
                "hepta.fixed-nomic-encoder.v2",
                self.principal,
                {**self.request, "objective_digest": "f" * 64},
            )
        with self.assertRaises(ValueError):
            self.call(
                "hepta.fixed-nomic-encoder.v2",
                {**self.principal, "goal_scope_mode": "ActualCompiledGoalScopeV3"},
                self.request,
            )

    def test_wrong_peer_body_model_or_empty_stage_cannot_reach_the_resource_owner(self):
        principal = {key: value for key, value in self.principal.items() if key not in ("objective_digest", "run_id")}
        principal["goal_scope_mode"] = "ActualCompiledGoalScopeV3"
        for field, value in [
            ("body_digest", "2" * 64),
            ("model_generation", 2),
            ("objective_digest", "0" * 64),
            ("ndu_digest", "0" * 64),
            ("run_id", "invalid space"),
            ("purpose", "InstallModel"),
        ]:
            left, right = socket.socketpair(socket.AF_UNIX)
            with (
                left,
                right,
                patch.object(fixed_encoder_resources, "observe") as observe,
                self.assertRaises(ValueError),
            ):
                self.authorize(
                    left,
                    {"schema": "hepta.fixed-nomic-encoder.v3", "principals": [principal]},
                    {**self.request, field: value},
                )
            observe.assert_not_called()
        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(fixed_encoder_resources, "observe") as observe,
            self.assertRaises(ValueError),
        ):
            self.authorize(
                left,
                {
                    "schema": "hepta.fixed-nomic-encoder.v3",
                    "principals": [{**principal, "uid": os.getuid() + 1}],
                },
                self.request,
            )
        observe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
