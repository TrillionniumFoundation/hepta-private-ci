"""Synthetic observer controls only: no real source, model or memory benefit."""

import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path

from .episodic_causal_contract import (
    BASELINES,
    CHANNELS,
    COSTS,
    LAYERS,
    PUBLIC_SELECTOR,
    AuthenticatedObservation,
    admit_protocol,
    assess_episode,
)
from .episodic_memory import canonical_bytes, digest


class CausalContractTests(unittest.TestCase):
    def setUp(self):
        self.artifacts = {}
        selector_source = self.pin(
            Path(__file__).with_name("candidate_selector.py").read_bytes()
        )
        task = canonical_bytes({"query": "shipping address", "key": "address"})
        retrieval = {
            "query_sha256": hashlib.sha256(task).hexdigest(),
            "source_ids": ["s"],
            "limit": 8,
            "max_context_bytes": 4096,
            "replay_seed": 0,
            "selector_sha256": PUBLIC_SELECTOR,
            "selector_mode": "public_rule",
            "selector_source_sha256": selector_source["sha256"],
            "selector_checkpoint_sha256": "9" * 64,
        }
        self.plan = {
            "schema": "hepta.mem9.causal-plan.v1",
            "selector_sha256": PUBLIC_SELECTOR,
            "selector_mode": "public_rule",
            "selector_source": selector_source,
            "actor_sha256": "1" * 64,
            "launcher_sha256": "2" * 64,
            "model_sha256": "a" * 64,
            "analysis_sha256": "b" * 64,
            "evaluator_sha256": "c" * 64,
            "context_bytes": 4096,
            "baselines": dict.fromkeys(BASELINES, "PLANNED"),
            "ablations": dict.fromkeys(LAYERS, "PLANNED"),
            "sources": {
                "s": self.observe(
                    "source_admission",
                    {
                        "source_id": "s",
                        "exposure_status": "UNSEEN",
                        "exposure_manifest_sha256": "d" * 64,
                        "checked_at": "2026-11-11T00:00:00Z",
                    },
                )
            },
            "cases": [
                {
                    "case_id": "p",
                    "source_id": "s",
                    "task_a_sha256": "e" * 64,
                    "task_c_sha256": hashlib.sha256(task).hexdigest(),
                    "retrieval": retrieval,
                }
            ],
        }
        self.plan_sha = digest(self.plan)
        self.plan["registration"] = self.observe(
            "registration",
            {"protocol_sha256": self.plan_sha, "registered_at": "2026-11-11T01:00:00Z"},
        )
        readers = {
            arm: {
                "process_identity": "process-" + arm,
                "session_id": "session-" + arm,
                "started_at": "2026-11-11T04:00:00Z",
            }
            for arm in ("on", "off")
        }
        raw = self.pin(b"synthetic retained observation")
        launches = {}
        self.launches = {}
        for index, arm in enumerate(readers):
            bootstrap = {
                "bootstrap": "hepta.mem9.namespace.v1",
                "pid": 1,
                "namespaces": {
                    key: key + ":" + arm
                    for key in ("mnt", "pid", "net", "ipc", "uts", "user")
                },
                "home_empty": True,
                "cache_empty": True,
                "workspace_empty": True,
            }
            process = {
                "host_boot_id": "boot",
                "launcher_pid": index + 100,
                "launch_monotonic_ns": index + 1000,
            }
            readers[arm]["process_identity"] = digest(process)
            launch = {
                "schema": "hepta.mem9.isolated-launch.v1",
                "status": "EXECUTED",
                "returncode": 0,
                "input_transport": "sealed-memfd-ro-bind-data",
                "mode": arm,
                "session_id": readers[arm]["session_id"],
                "actor_sha256": self.plan["actor_sha256"],
                "launcher_sha256": self.plan["launcher_sha256"],
                "process_identity": process,
                "started_at_unix_ns": int(
                    datetime.fromisoformat("2026-11-11T04:00:00+00:00").timestamp()
                )
                * 10**9,
                "ended_at_unix_ns": 1794369601000000000,
                "started_monotonic_ns": index + 1000,
                "ended_monotonic_ns": index + 2000,
                "source_unchanged": True,
                "capture_truncated": False,
                "task": self.pin(task),
                "task_sha256": hashlib.sha256(task).hexdigest(),
                "request_sha256": hashlib.sha256(task).hexdigest(),
                "context_sha256": hashlib.sha256(
                    b"memory" if arm == "on" else b""
                ).hexdigest(),
                "context_bytes": 6 if arm == "on" else 0,
                "bootstrap": bootstrap,
                "stdout": self.pin(
                    canonical_bytes(bootstrap) + b"\n" + self.artifacts[raw["sha256"]]
                ),
                "actor_output": raw,
                "stderr": self.pin(b""),
                "host_namespaces": dict.fromkeys(bootstrap["namespaces"], "host"),
                "private_roots": {
                    "home": "/home/actor",
                    "cache": "/cache",
                    "workspace": "/work",
                },
            }
            self.launches[arm] = launch
            launches[arm] = self.pin(canonical_bytes(launch))
        self.payloads = {
            "timeline": {
                "case": self.plan["cases"][0],
                "writer": {
                    "process_identity": "process-a",
                    "session_id": "session-a",
                    "started_at": "2026-11-11T02:00:00Z",
                    "exited_at": "2026-11-11T03:00:00Z",
                },
                "readers": readers,
            },
            "isolation": {
                "readers": readers,
                "channels": sorted(CHANNELS),
                "launches": launches,
            },
            "memory": {
                "source_id": "s",
                "config_by_arm": {"on": retrieval.copy(), "off": retrieval.copy()},
                "frontier_sha256": "8" * 64,
                "context_sha256": hashlib.sha256(b"memory").hexdigest(),
                "context_bytes": 6,
                "context": self.pin(b"memory"),
                "owner_read": raw,
                "final_use": raw,
            },
            "provider": {
                "execution_kind": "REAL_MODEL",
                "settlement": "COMPLETE",
                "model_sha256": self.plan["model_sha256"],
                "physical_requests": 2,
                "requests": [
                    {
                        "request_id": arm,
                        "launch_sha256": launches[arm]["sha256"],
                        "arm": arm,
                        "session_id": readers[arm]["session_id"],
                        "terminal": "COMPLETED",
                        "request": raw,
                        "result": raw,
                    }
                    for arm in readers
                ],
            },
            "costs": {
                "measurements": [
                    {
                        "arm": arm,
                        "phase": phase,
                        "value": 0,
                        "unit": "fixture units",
                        "raw": raw,
                    }
                    for arm in readers
                    for phase in COSTS
                ]
            },
        }
        for payload in self.payloads.values():
            payload["protocol_sha256"] = self.plan_sha
            payload["case_id"] = "p"
        for kind in ("memory", "costs"):
            self.payloads[kind]["sessions"] = {
                arm: reader["session_id"] for arm, reader in readers.items()
            }

    def pin(self, raw):
        identity = hashlib.sha256(raw).hexdigest()
        self.artifacts[identity] = raw
        return {"sha256": identity, "bytes": len(raw)}

    def observe(self, kind, payload):
        return self.pin(
            canonical_bytes(
                {
                    "schema": "hepta.mem9.observation.v1",
                    "kind": kind,
                    "payload": payload,
                }
            )
        )

    def verifier(self, kind, raw):
        # Deliberately fake authentication port; results are contract controls.
        return AuthenticatedObservation(
            kind, hashlib.sha256(raw).hexdigest(), "fixture-only"
        )

    def assess(self):
        episode = {
            "case_id": "p",
            "protocol_sha256": self.plan_sha,
            "observations": {
                kind: self.observe(kind, payload)
                for kind, payload in self.payloads.items()
            },
        }
        return assess_episode(
            self.plan, episode, self.artifacts.__getitem__, self.verifier
        )

    def test_complete_fixture_is_scoring_input_never_benefit_or_adoption(self):
        result = self.assess()
        self.assertEqual(
            result,
            {
                "status": "ELIGIBLE_FOR_SCORING",
                "blockers": [],
                "protocol_sha256": self.plan_sha,
                "scientific_acceptance": "HOLD",
                "production_adoption": False,
                "benefit_established": False,
            },
        )

    def test_digest_without_trusted_observer_does_not_admit(self):
        result = admit_protocol(self.plan, self.artifacts.__getitem__)
        self.assertEqual(result["blockers"], ["AUTHENTICATED_OBSERVER_UNAVAILABLE"])

    def test_authenticated_fixture_admits_only_protocol(self):
        result = admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)
        self.assertEqual(result["status"], "ADMITTED_FOR_EXECUTION")
        self.assertEqual(result["scientific_acceptance"], "HOLD")
        self.assertIs(result["production_adoption"], False)
        self.assertIs(result["benefit_established"], False)

    def test_registration_does_not_cover_changed_plan(self):
        self.plan["context_bytes"] += 1
        self.assertEqual(
            admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                "blockers"
            ],
            ["PROTOCOL_BINDING_MISMATCH"],
        )

    def test_unknown_source_and_boolean_budgets_fail_closed(self):
        for mutate in (
            lambda: self.plan.update(context_bytes=True),
            lambda: self.plan.update(selector_sha256="0" * 64),
            lambda: self.plan.update(selector_mode="frozen_neural"),
        ):
            self.setUp()
            mutate()
            self.assertEqual(
                admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                    "status"
                ],
                "HOLD",
            )
        self.setUp()
        source = {
            "source_id": "s",
            "exposure_status": "UNKNOWN",
            "exposure_manifest_sha256": "d" * 64,
            "checked_at": "2026-11-11T00:00:00Z",
        }
        self.plan["sources"]["s"] = self.observe("source_admission", source)
        self.plan["registration"] = self.observe(
            "registration",
            {
                "protocol_sha256": digest(
                    {k: v for k, v in self.plan.items() if k != "registration"}
                ),
                "registered_at": "2026-11-11T01:00:00Z",
            },
        )
        self.assertEqual(
            admit_protocol(self.plan, self.artifacts.__getitem__, self.verifier)[
                "blockers"
            ],
            ["SOURCE_EXPOSURE_NOT_VERIFIED_UNSEEN"],
        )

    def test_unknown_synthetic_or_unsettled_model_is_not_counted(self):
        for field, value in (
            ("execution_kind", "SYNTHETIC"),
            ("settlement", "UNKNOWN"),
            ("physical_requests", True),
            ("physical_requests", 3),
        ):
            self.setUp()
            self.payloads["provider"][field] = value
            self.assertEqual(self.assess()["status"], "HOLD")

    def test_request_replay_and_unknown_terminal_rejected(self):
        for field, value in (
            ("request_id", "on"),
            ("terminal", "UNKNOWN"),
            ("session_id", "session-a"),
        ):
            self.setUp()
            self.payloads["provider"]["requests"][1][field] = value
            self.assertEqual(self.assess()["status"], "HOLD")

    def test_early_reader_and_shared_history_rejected(self):
        for field, value in (
            ("started_at", "2026-11-11T02:30:00Z"),
            ("session_id", "session-a"),
            ("process_identity", "process-a"),
        ):
            self.setUp()
            self.payloads["timeline"]["readers"]["off"][field] = value
            self.assertEqual(self.assess()["status"], "HOLD")

    def test_raw_evidence_tampering_rejected(self):
        pin = self.payloads["provider"]["requests"][0]["request"]
        self.artifacts[pin["sha256"]] = b"x" * pin["bytes"]
        self.assertEqual(self.assess()["blockers"], ["EVIDENCE_HASH_MISMATCH"])

    def test_raw_bootstrap_and_memory_off_reject_contradictions(self):
        for field, value in (
            ("context_bytes", 6),
            ("bootstrap", {"isolated": True}),
            ("capture_truncated", True),
            ("status", "SETUP_FAILED"),
            ("returncode", None),
            ("context_bytes", False),
            ("ended_monotonic_ns", 0),
            ("input_transport", "mutable-directory"),
        ):
            self.setUp()
            self.launches["off"][field] = value
            self.payloads["isolation"]["launches"]["off"] = self.pin(
                canonical_bytes(self.launches["off"])
            )
            self.assertEqual(self.assess()["status"], "HOLD")

    def test_actual_retrieval_changes_and_failed_actor_are_separate(self):
        for field, value in (
            ("query_sha256", "7" * 64),
            ("source_ids", []),
            ("limit", 1),
            ("replay_seed", 2),
            ("max_context_bytes", 5),
        ):
            self.setUp()
            self.payloads["memory"]["config_by_arm"]["off"][field] = value
            self.assertEqual(self.assess()["blockers"], ["MEMORY_CONFIG_MISMATCH"])
        self.setUp()
        self.launches["off"]["status"] = "ACTOR_FAILED"
        self.launches["off"]["returncode"] = 1
        self.payloads["isolation"]["launches"]["off"] = self.pin(
            canonical_bytes(self.launches["off"])
        )
        self.payloads["provider"]["requests"][1]["launch_sha256"] = self.payloads[
            "isolation"
        ]["launches"]["off"]["sha256"]
        self.assertEqual(self.assess()["status"], "ELIGIBLE_FOR_SCORING")

    def test_provider_bytes_must_come_from_the_bound_actor(self):
        self.payloads["provider"]["requests"][0]["request"] = self.pin(
            b"host-added history"
        )
        self.assertEqual(self.assess()["blockers"], ["REQUEST_NOT_ACTOR_OUTPUT"])
        self.setUp()
        self.payloads["provider"]["requests"][0]["launch_sha256"] = "0" * 64
        self.assertEqual(self.assess()["blockers"], ["REQUEST_LAUNCH_MISMATCH"])

    def test_unframed_bootstrap_and_unbound_context_fail_closed(self):
        self.launches["off"]["stdout"] = self.pin(
            canonical_bytes(self.launches["off"]["bootstrap"])
        )
        self.payloads["isolation"]["launches"]["off"] = self.pin(
            canonical_bytes(self.launches["off"])
        )
        self.assertEqual(self.assess()["blockers"], ["ACTOR_OUTPUT_NOT_BOUND"])
        self.setUp()
        empty = hashlib.sha256(b"").hexdigest()
        self.payloads["memory"]["context_sha256"] = empty
        self.launches["on"]["context_sha256"] = empty
        self.payloads["isolation"]["launches"]["on"] = self.pin(
            canonical_bytes(self.launches["on"])
        )
        self.assertEqual(self.assess()["blockers"], ["MEMORY_CONTEXT_NOT_BOUND"])
        self.setUp()
        self.launches["off"]["bootstrap"]["pid"] = True
        self.launches["off"]["stdout"] = self.pin(
            canonical_bytes(self.launches["off"]["bootstrap"]) + b"\n"
        )
        self.payloads["isolation"]["launches"]["off"] = self.pin(
            canonical_bytes(self.launches["off"])
        )
        self.assertEqual(self.assess()["status"], "HOLD")

    def test_cost_observation_cannot_move_between_cases_or_sessions(self):
        for mutate in (
            lambda: self.payloads["costs"].update(case_id="another-case"),
            lambda: self.payloads["costs"]["sessions"].update(off="another-session"),
        ):
            self.setUp()
            mutate()
            self.assertEqual(self.assess()["status"], "HOLD")

    def test_unknown_bool_and_negative_costs_rejected(self):
        for value in (None, True, -1):
            self.setUp()
            self.payloads["costs"]["measurements"][0]["value"] = value
            self.assertEqual(self.assess()["blockers"], ["COST_UNKNOWN_OR_INVALID"])

    def test_malformed_and_nan_protocol_returns_hold(self):
        for plan in (None, [], {"schema": True}, json.loads('{"context_bytes":NaN}')):
            self.assertEqual(
                admit_protocol(plan, self.artifacts.__getitem__, self.verifier)[
                    "status"
                ],
                "HOLD",
            )


if __name__ == "__main__":
    unittest.main()
