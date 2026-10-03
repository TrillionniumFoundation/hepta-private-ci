"""Execute the actual closed normal-peer function without Root bootstrap imports."""

import ast
import http.client
import json
import os
from pathlib import Path
import re
import socket
import struct
import sys
import time
import unittest
from unittest.mock import patch

import fixed_encoder_resources


def source_function(name):
    program = Path(__file__).with_name("hepta_fixed_nomic_encoder.py")
    parsed = ast.parse(program.read_text())
    selected = [
        item
        for item in parsed.body
        if isinstance(item, ast.FunctionDef) and item.name in (name, "process_identity")
    ]
    namespace = {
        "Path": Path,
        "socket": socket,
        "struct": struct,
        "re": re,
        "json": json,
        "http": http,
        "time": time,
        "now_ms": lambda: time.time_ns() // 1_000_000,
        "backend_identity": lambda _: ("test-only-physical-identity",),
        "verify_large_source": lambda *_: None,
        "source_bytes": lambda source, _: json.dumps(source).encode(),
        "decode_json": json.loads,
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(program), "exec"),
        namespace,
    )
    return namespace[name]


class GoalTests(unittest.TestCase):
    def test_v3_reports_physical_manifest_separately_from_cpu_alias_and_keeps_v2_wire(
        self,
    ):
        numpy_site = Path(
            "/opt/hepta-private-ci/encoders/fixed-nomic-20261001-v4/python-site"
        )
        if not numpy_site.is_dir():
            self.skipTest(
                "this Linux physical transform fixture needs the installed immutable NumPy snapshot"
            )
        sys.path.insert(0, str(numpy_site))
        import numpy

        self.assertEqual(numpy.__version__, "1.26.4")
        self.assertEqual(
            Path(numpy.__file__).resolve(), numpy_site / "numpy/__init__.py"
        )
        vectors = [
            [(value - offset) / 768 for value in range(768)] for offset in (7, 19)
        ]
        payload = json.dumps({"embeddings": vectors}).encode()
        calls = []

        class Connection:
            def __init__(self, host, port, timeout):
                calls.append((host, port, timeout))

            def request(self, method, path, body, headers):
                calls.append((method, path, json.loads(body), headers))

            def getresponse(self):
                return self

            @property
            def status(self):
                return 200

            def read(self, _maximum):
                return payload

            def close(self):
                pass

        cfg = {
            "schema": "hepta.fixed-nomic-encoder.v3",
            "expires_at_ms": time.time_ns() // 1_000_000 + 30_000,
            "timeout_ms": 2000,
            "preprocessor_source": {"sha256": "1" * 64},
            "gguf_source": {"sha256": "2" * 64},
            "model_sources": [
                {"path": "/opt/physical/manifests/nomic", "sha256": "3" * 64}
            ],
        }
        preprocessor = {
            "claim_prefix": "search_query: ",
            "document_prefix": "search_document: ",
            "model": "nomic-embed-text:latest",
            "tokenizer_sha256": "4" * 64,
        }
        pair = {
            "claim_text": "Public claim",
            "title": "Public title",
            "abstract_sentences": ["Public text"],
            "pair_id": "public.fixture",
            "source_row_sha256": "5" * 64,
        }
        encode = source_function("encode")
        with patch.object(http.client, "HTTPConnection", Connection):
            v3 = encode(cfg, preprocessor, numpy, pair, "6" * 64)
            v2 = encode(
                {**cfg, "schema": "hepta.fixed-nomic-encoder.v2"},
                preprocessor,
                numpy,
                pair,
                "7" * 64,
            )
        self.assertEqual(v3["encoder_manifest_sha256"], "3" * 64)
        self.assertEqual(v3["weights_sha256"], "2" * 64)
        self.assertEqual(v3["tokenizer_sha256"], "4" * 64)
        self.assertNotIn("encoder_manifest_sha256", v2)
        self.assertEqual(v3["features_q24"], v2["features_q24"])
        self.assertEqual(len(v3["features_q24"]), 512)
        self.assertTrue(any(v3["features_q24"]))
        self.assertTrue(all(type(value) is int for value in v3["features_q24"]))
        self.assertEqual(calls[0][:2], ("127.0.0.1", 11435))
        self.assertEqual(calls[1][:2], ("POST", "/api/embed"))

    def setUp(self):
        self.authorize = source_function("authorize_current")
        _, uids, gids, cgroup = self.authorize.__globals__["process_identity"](
            os.getpid()
        )
        self.request = {
            "pair_id": "public.one",
            "source_row_sha256": "a" * 64,
            "body_digest": "b" * 64,
            "objective_digest": "c" * 64,
            "model_generation": 1,
            "run_id": "run:goal.one",
            "ndu_digest": "d" * 64,
        }
        body = {
            "runtime_body_digest": "b" * 64,
            "agent_id": "actual.agent",
            "body_generation": 1,
        }
        self.principal = {
            **{
                key: value for key, value in self.request.items() if key != "ndu_digest"
            },
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
            patch.object(
                fixed_encoder_resources,
                "observe",
                return_value=("actual.root.resource",),
            ) as observe,
        ):
            result = self.authorize(
                left, {"schema": schema, "principals": [principal]}, request
            )
            self.assertEqual(result[0], os.getpid())
            self.assertEqual(observe.call_args.args[2], os.getpid())
            self.assertEqual(
                observe.call_args.args[1]["fleet_manifest_digest"], "e" * 64
            )
            return result

    def test_explicit_goal_mode_accepts_two_actual_stages_same_model_and_kernel_peer(
        self,
    ):
        principal = {
            key: value
            for key, value in self.principal.items()
            if key not in ("objective_digest", "run_id")
        }
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

    def test_current_execution_uses_actual_peer_and_program_pinned_owner_route(self):
        principal = {
            key: value
            for key, value in self.principal.items()
            if key
            not in ("objective_digest", "run_id", "cgroup", "fleet_manifest_digest")
        }
        principal["goal_scope_mode"] = "ActualCompiledGoalScopeV3"
        principal["fleet_execution_binding"] = "CurrentRootFleetExecutionV1"
        left, right = socket.socketpair(socket.AF_UNIX)
        with (
            left,
            right,
            patch.object(
                fixed_encoder_resources, "observe", return_value=("current",)
            ) as observe,
        ):
            result = self.authorize(
                left,
                {"schema": "hepta.fixed-nomic-encoder.v3", "principals": [principal]},
                self.request,
            )
        self.assertEqual(result[0], os.getpid())
        self.assertEqual(observe.call_args.args[1], principal)
        self.assertEqual(observe.call_args.args[2], os.getpid())
        for field, value in [
            ("fleet_manifest_digest", "e" * 64),
            ("cgroup", "/old/execution"),
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
                    {
                        "schema": "hepta.fixed-nomic-encoder.v3",
                        "principals": [{**principal, field: value}],
                    },
                    self.request,
                )
            observe.assert_not_called()

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
        principal = {
            key: value
            for key, value in self.principal.items()
            if key not in ("objective_digest", "run_id")
        }
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
                    {
                        "schema": "hepta.fixed-nomic-encoder.v3",
                        "principals": [principal],
                    },
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
