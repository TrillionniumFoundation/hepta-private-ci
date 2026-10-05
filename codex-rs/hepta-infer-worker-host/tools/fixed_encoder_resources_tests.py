import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import fixed_encoder_resources
from fixed_encoder_resources import validate_observation


def fixture():
    context = {
        "execution_id": "current-execution",
        "allocation_id": "current-execution",
        "principal_id": "original-agent",
        "host_id": "original-host",
        "host_generation": 2,
        "lease_generation": 1,
        "manifest_digest": "a" * 64,
        "resources": {
            "cpu_millis": 2000,
            "memory_bytes": 4294967296,
            "concurrent_turns": 2,
        },
    }
    grant = {
        **context,
        "authority_epoch": 3,
        "lease_generation": 205,
        "expires_at_ms": 20_000,
        "semantic_digest": context["manifest_digest"],
        "revoked": False,
    }
    value = {
        "observed_at_ms": 10_000,
        "boot_identity": "actual-boot",
        "resource_authority_epoch": 3,
        "observation": {
            "context": context,
            "allocation": grant,
            "process_id": 123,
            "process_start_ticks": 456,
        },
    }
    return (
        {"agent_id": "original-agent", "fleet_manifest_digest": "a" * 64},
        ("456",),
        value,
    )


class ResourceObservationTests(unittest.TestCase):
    def test_current_execution_requires_the_pinned_program_in_the_same_owner_probe(
        self,
    ):
        principal, _, value = fixture()
        principal.pop("fleet_manifest_digest")
        principal["fleet_execution_binding"] = "CurrentRootFleetExecutionV1"
        principal["program_source"] = {
            "path": "/opt/original/worker",
            "sha256": "b" * 64,
        }
        kernel = (
            "456",
            [986] * 4,
            [975] * 4,
            "/hepta-test/agent-original-agent/main-current-execution",
        )
        value["observation"]["context"]["containment"] = kernel[3][1:]
        cfg = {
            "resource_observer": {
                "program": {"path": "/opt/original/fleetctl", "sha256": "c" * 64},
                "local_host_policy": {
                    "path": "/etc/original/host.json",
                    "sha256": "d" * 64,
                },
                "fleet_root": "/var/lib/original/fleet",
            }
        }
        with (
            patch.object(fixed_encoder_resources, "verify_large_source"),
            patch.object(fixed_encoder_resources, "source_bytes"),
            patch.object(fixed_encoder_resources, "protected_path"),
            patch.object(
                fixed_encoder_resources.time, "time_ns", return_value=10_010_000_000
            ),
            patch.object(
                fixed_encoder_resources.subprocess,
                "run",
                return_value=SimpleNamespace(
                    returncode=0, stdout=json.dumps(value).encode()
                ),
            ) as run,
        ):
            fixed_encoder_resources.observe(cfg, principal, 123, kernel)
            self.assertEqual(
                run.call_args.args[0],
                [
                    "/opt/original/fleetctl",
                    "--fleet-root",
                    "/var/lib/original/fleet",
                    "resource-observe",
                    "--local-host-policy",
                    "/etc/original/host.json",
                    "--require-program-sha256",
                    "b" * 64,
                    "original-agent",
                    "123",
                ],
            )
            run.return_value = SimpleNamespace(returncode=1, stdout=b"")
            with self.assertRaises(ValueError):
                fixed_encoder_resources.observe(cfg, principal, 123, kernel)

    def test_current_root_execution_binds_the_live_context_without_a_future_launch_guess(
        self,
    ):
        principal, _, value = fixture()
        principal.pop("fleet_manifest_digest")
        principal["fleet_execution_binding"] = "CurrentRootFleetExecutionV1"
        kernel = (
            "456",
            [986] * 4,
            [975] * 4,
            "/hepta-test/agent-original-agent/main-current-execution",
        )
        value["observation"]["context"]["containment"] = kernel[3][1:]
        first = validate_observation(principal, 123, kernel, value, 10_010)
        changed = copy.deepcopy(value)
        changed["observation"]["context"]["manifest_digest"] = "b" * 64
        changed["observation"]["allocation"]["semantic_digest"] = "b" * 64
        self.assertNotEqual(
            first, validate_observation(principal, 123, kernel, changed, 10_010)
        )
        for key, replacement in [
            ("context.manifest_digest", "0" * 64),
            ("context.containment", "hepta-other/main-foreign"),
            ("context.principal_id", "foreign-agent"),
            ("process_id", 124),
            ("process_start_ticks", 457),
            ("allocation.revoked", True),
            ("allocation.authority_epoch", 4),
        ]:
            with self.subTest(field=key):
                changed = copy.deepcopy(value)
                target = changed["observation"]
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = replacement
                with self.assertRaises(ValueError):
                    validate_observation(principal, 123, kernel, changed, 10_010)

    def test_live_lease_renewal_preserves_operation_fence_without_using_spawn_lease(
        self,
    ):
        principal, kernel, value = fixture()
        first = validate_observation(principal, 123, kernel, value, 10_010)
        value["observation"]["allocation"]["lease_generation"] += 1
        value["observation"]["allocation"]["expires_at_ms"] += 1000
        second = validate_observation(principal, 123, kernel, value, 10_020)
        self.assertEqual(first, second)
        self.assertEqual(value["observation"]["context"]["lease_generation"], 1)

    def test_foreign_peer_stale_expired_revoked_or_wrong_epoch_reject_before_encoding(
        self,
    ):
        principal, kernel, original = fixture()
        edits = [
            ("observed_at_ms", 1),
            ("observed_at_ms", 20_000),
            ("resource_authority_epoch", 4),
            ("resource_authority_epoch", True),
            ("observation.process_id", 124),
            ("observation.process_start_ticks", 457),
            ("observation.allocation.expires_at_ms", 10_010),
            ("observation.allocation.revoked", True),
            ("observation.allocation.principal_id", "foreign-agent"),
            ("observation.allocation.semantic_digest", "b" * 64),
        ]
        for key, replacement in edits:
            with self.subTest(field=key):
                value = copy.deepcopy(original)
                target = value
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = replacement
                with self.assertRaises(ValueError):
                    validate_observation(principal, 123, kernel, value, 10_010)

    def test_epoch_or_resource_change_changes_physical_operation_fence(self):
        principal, kernel, value = fixture()
        first = validate_observation(principal, 123, kernel, value, 10_010)
        value["resource_authority_epoch"] = 4
        value["observation"]["allocation"]["authority_epoch"] = 4
        self.assertNotEqual(
            first, validate_observation(principal, 123, kernel, value, 10_010)
        )


if __name__ == "__main__":
    unittest.main()
