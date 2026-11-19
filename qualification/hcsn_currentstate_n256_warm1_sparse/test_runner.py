"""Resource denial and read-only comparison controls; zero N256 dynamics."""

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire
from qualification.hcsn_currentstate_n256_warm1_sparse import runner
from qualification.hcsn_currentstate_n256_warm1_sparse.compare import ORACLE_PATH, compare


class AdmissionControls(unittest.TestCase):
    def test_original_thresholds_with_recorded_resources(self):
        path = runner.ROOT / "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/PREFLIGHT.json"
        original = json.loads(path.read_text())
        now = original["captured_monotonic_ns"] + 1
        runner.assess(original, now)
        for name, value in (("MemAvailable", 0), ("SwapFree", 0)):
            changed = copy.deepcopy(original)
            changed["meminfo_kib"][name] = value
            with self.assertRaisesRegex(ValueError, name):
                runner.assess(changed, now)
        changed = copy.deepcopy(original)
        changed["ancestor_cgroup_chain"] = [{"fields": {"memory.max": "100", "memory.current": "99",
                                                        "memory.events": "oom 0\noom_kill 0", "cpuset.cpus.effective": "0-3"}}]
        with self.assertRaisesRegex(ValueError, "headroom"):
            runner.assess(changed, now)
        changed["ancestor_cgroup_chain"][0]["fields"]["memory.max"] = "max"
        changed["ancestor_cgroup_chain"][0]["fields"]["memory.events"] = "oom 1\noom_kill 0"
        with self.assertRaisesRegex(ValueError, "OOM"):
            runner.assess(changed, now)
        with self.assertRaisesRegex(ValueError, "stale"):
            runner.assess(original, now + 30_000_000_000)

    def test_child_limit_checked_before_numerical_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admission.json"
            path.write_text(json.dumps({"identity": runner.KEY, "scope": runner.SCOPE,
                                        "freeze_sha256": runner.sha(runner.FREEZE)}))
            with patch.object(runner.resource, "getrlimit", return_value=(-1, -1)):
                with self.assertRaisesRegex(ValueError, "RLIMIT_AS"):
                    runner.verify_child(path)

    def test_changed_source_rejected(self):
        with patch.object(runner, "sha", return_value="0" * 64):
            with self.assertRaisesRegex(ValueError, "source mismatch"):
                runner.check_freeze()


class ArchivedComparisonControls(unittest.TestCase):
    def test_every_coordinate_and_packet_output_detected(self):
        raw = (runner.ROOT / ORACLE_PATH).read_bytes()
        exact = compare(raw, raw)
        self.assertEqual(exact["compared_coordinates"], 69728)
        self.assertEqual(exact["bitwise_mismatches"], 0)
        envelope = wire.decode(raw, 8 * 1024**2)
        packet = envelope.packets[0]
        mutated = bytearray(packet.output.payload)
        mutated[0] ^= 1
        changed = replace(packet, output=replace(packet.output, payload=bytes(mutated)))
        payload = wire.encode(replace(envelope, packets=(changed,) + envelope.packets[1:]))
        unequal = compare(payload, raw)
        self.assertEqual(unequal["bitwise_mismatches"], 1)
        self.assertFalse(unequal["original_bitwise_requirement_satisfied"])
        self.assertEqual(unequal["families"]["packet/output"]["bitwise_mismatches"], 1)
        self.assertFalse(unequal["original_firststep_contract_admitted"])


if __name__ == "__main__":
    unittest.main()
