"""Stdlib-only source controls; these tests never invoke the launcher."""

import ast
import copy
import unittest

from qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted import launcher
from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent import policy


class LauncherSourceTest(unittest.TestCase):
    def test_parent_has_no_numerical_import(self):
        tree = ast.parse(launcher.Path(launcher.__file__).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        self.assertFalse({name.split(".")[0] for name in imports} & {"numpy", "scipy", "torch"})

    def test_child_limit_precedes_exec(self):
        source = launcher.Path(launcher.__file__).read_text()
        self.assertIn("preexec_fn=_child_limit", source)
        self.assertIn("resource.setrlimit(resource.RLIMIT_AS", source)
        self.assertEqual(policy.POLICY["child_rlimit_as_bytes"], 4 * 1024**3)
        self.assertEqual(policy.POLICY["child_timeout_seconds"], 600)

    def test_event_parser_preserves_cgroup_levels(self):
        chain = [{"path": "/one", "fields": {"memory.events": "oom 0\noom_kill 2"}}]
        self.assertEqual(launcher._events(chain), {"/one": {"oom": 0, "oom_kill": 2}})

    def test_preflight_policy_rejects_history(self):
        from qualification.hcsn_currentstate_n256_firststep_hosted_admission_intent.test_policy import fixture

        preflight, launch = fixture()
        bad = copy.deepcopy(preflight)
        bad["ancestor_cgroup_chain"][0]["fields"]["memory.events"] = "oom 1\noom_kill 0"
        with self.assertRaises(policy.PolicyError):
            policy.assess_preflight(bad, launch)


if __name__ == "__main__":
    unittest.main()
