import copy
import unittest

from fixed_encoder_resources import validate_observation


def fixture():
    context = {
        "execution_id": "current-execution", "allocation_id": "current-execution",
        "principal_id": "original-agent", "host_id": "original-host", "host_generation": 2,
        "lease_generation": 1, "manifest_digest": "a" * 64,
        "resources": {"cpu_millis": 2000, "memory_bytes": 4294967296, "concurrent_turns": 2},
    }
    grant = {**context, "authority_epoch": 3, "lease_generation": 205, "expires_at_ms": 20_000,
             "semantic_digest": context["manifest_digest"], "revoked": False}
    value = {"observed_at_ms": 10_000, "boot_identity": "actual-boot", "resource_authority_epoch": 3,
             "observation": {"context": context, "allocation": grant,
                             "process_id": 123, "process_start_ticks": 456}}
    return {"agent_id": "original-agent", "fleet_manifest_digest": "a" * 64}, ("456",), value


class ResourceObservationTests(unittest.TestCase):
    def test_live_lease_renewal_preserves_operation_fence_without_using_spawn_lease(self):
        principal, kernel, value = fixture()
        first = validate_observation(principal, 123, kernel, value, 10_010)
        value["observation"]["allocation"]["lease_generation"] += 1
        value["observation"]["allocation"]["expires_at_ms"] += 1000
        second = validate_observation(principal, 123, kernel, value, 10_020)
        self.assertEqual(first, second)
        self.assertEqual(value["observation"]["context"]["lease_generation"], 1)

    def test_foreign_peer_stale_expired_revoked_or_wrong_epoch_reject_before_encoding(self):
        principal, kernel, original = fixture()
        edits = [
            ("observed_at_ms", 1), ("observed_at_ms", 20_000),
            ("resource_authority_epoch", 4), ("resource_authority_epoch", True),
            ("observation.process_id", 124), ("observation.process_start_ticks", 457),
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
        self.assertNotEqual(first, validate_observation(principal, 123, kernel, value, 10_010))


if __name__ == "__main__":
    unittest.main()
