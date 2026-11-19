"""Stdlib-only controls for the hosted preflight policy."""

import copy
import unittest

from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent.policy import (
    DENSE_ORACLE_SHA256,
    IDENTITY,
    INPUT_BUNDLE_SHA256,
    POLICY,
    RUNTIME,
    RUNTIME_SHA256,
    TARGET,
    PolicyError,
    assess_preflight,
)


def fixture():
    fields = {
        "cpuset.cpus.effective": "0-3",
        "memory.current": str(2 * 1024**3),
        "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0",
        "memory.max": "max",
    }
    preflight = {
        "schema": "hcsn-n256-hosted-preflight-v1",
        "session_id": "future-session",
        "boot_id": "future-boot",
        "self_cgroup": "/future-job",
        "captured_monotonic_ns": 100,
        "runtime_sha256": RUNTIME_SHA256,
        "runtime": RUNTIME,
        "meminfo_kib": {"MemAvailable": 12 * 1024**2, "SwapFree": 2 * 1024**2},
        "memory_pressure": ["some avg10=0.00 avg60=0.00 avg300=0.00 total=0", "full avg10=0.00 avg60=0.00 avg300=0.00 total=0"],
        "ancestor_cgroup_chain": [{"path": "/future-job", "fields": fields}],
    }
    launch = {
        "schema": "hcsn-n256-hosted-launch-v1",
        "identity": IDENTITY,
        "session_id": "future-session",
        "boot_id": "future-boot",
        "self_cgroup": "/future-job",
        "execution_monotonic_ns": 200,
        "dense_oracle_sha256": DENSE_ORACLE_SHA256,
        "input_bundle_sha256": INPUT_BUNDLE_SHA256,
        "target": TARGET,
        "policy": POLICY,
        "thread_environment": {name: "1" for name in (
            "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"
        )},
        "rlimit_as_applied_before_exec": True,
        "numeric_imports_before_child_limit": 0,
    }
    return preflight, launch


class PolicyTest(unittest.TestCase):
    def test_satisfied_fixture_still_grants_no_admission(self):
        result = assess_preflight(*fixture())
        self.assertEqual(result["preflight_contract_satisfied"], True)
        self.assertEqual(result["runtime_admitted"], False)
        self.assertEqual(result["resource_admitted"], False)
        self.assertEqual(result["n256_numerical_execution_allowed"], False)
        self.assertEqual(result["dynamic_steps"], 0)

    def test_runtime_mismatch_rejects(self):
        preflight, launch = fixture()
        preflight["runtime_sha256"] = "0" * 64
        with self.assertRaisesRegex(PolicyError, "runtime sha256"):
            assess_preflight(preflight, launch)

    def test_memory_shortfall_rejects(self):
        preflight, launch = fixture()
        preflight["meminfo_kib"]["MemAvailable"] = POLICY["minimum_mem_available_kib"] - 1
        with self.assertRaisesRegex(PolicyError, "MemAvailable"):
            assess_preflight(preflight, launch)

    def test_finite_cgroup_shortfall_rejects(self):
        preflight, launch = fixture()
        fields = preflight["ancestor_cgroup_chain"][0]["fields"]
        fields["memory.max"] = str(7 * 1024**3)
        with self.assertRaisesRegex(PolicyError, "finite cgroup"):
            assess_preflight(preflight, launch)

    def test_oom_history_rejects(self):
        preflight, launch = fixture()
        fields = preflight["ancestor_cgroup_chain"][0]["fields"]
        fields["memory.events"] = fields["memory.events"].replace("oom_kill 0", "oom_kill 1")
        with self.assertRaisesRegex(PolicyError, "OOM"):
            assess_preflight(preflight, launch)

    def test_stale_or_cross_session_capture_rejects(self):
        preflight, launch = fixture()
        stale = copy.deepcopy(launch)
        stale["execution_monotonic_ns"] = POLICY["maximum_capture_age_ns"] + 101
        with self.assertRaisesRegex(PolicyError, "stale"):
            assess_preflight(preflight, stale)
        launch["session_id"] = "other-session"
        with self.assertRaisesRegex(PolicyError, "same-session"):
            assess_preflight(preflight, launch)

    def test_limit_must_precede_numerical_imports(self):
        preflight, launch = fixture()
        launch["numeric_imports_before_child_limit"] = 1
        with self.assertRaisesRegex(PolicyError, "numerical import"):
            assess_preflight(preflight, launch)


if __name__ == "__main__":
    unittest.main()
