"""Negative manifest tests for qualification-only operator feature activation."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("operator_boundary", Path(__file__).with_name("hepta-learning-operator-boundary.py"))
assert spec is not None and spec.loader is not None
boundary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)


class ManifestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.write("hepta-bellman-operator", '[features]\ndefault = []\nunchecked-qualification-inputs = []\n')

    def tearDown(self):
        self.directory.cleanup()

    def write(self, package, contents):
        path = self.root / "codex-rs" / package / "Cargo.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)

    def test_only_named_dev_dependency_is_allowed(self):
        self.write("hepta-shadow-qualification", '[dev-dependencies]\ncodex-hepta-bellman-operator = { path = "../hepta-bellman-operator", features = ["unchecked-qualification-inputs"] }\n')
        self.assertEqual(boundary.manifest_findings(self.root), [])

    def test_normal_dependency_and_renamed_package_are_rejected(self):
        for key in ['codex-hepta-bellman-operator', 'renamed']:
            self.write("product", f'[dependencies]\n{key} = {{ package = "codex-hepta-bellman-operator", features = ["unchecked-qualification-inputs"] }}\n')
            self.assertTrue(boundary.manifest_findings(self.root))

    def test_target_specific_dependency_is_rejected(self):
        self.write("product", '[target.\'cfg(unix)\'.dependencies]\ncodex-hepta-bellman-operator = { features = ["unchecked-qualification-inputs"] }\n')
        self.assertTrue(boundary.manifest_findings(self.root))

    def test_default_and_forwarding_features_are_rejected(self):
        self.write("hepta-bellman-operator", '[features]\ndefault = ["unchecked-qualification-inputs"]\nunchecked-qualification-inputs = []\n')
        self.assertTrue(boundary.manifest_findings(self.root))
        self.write("hepta-bellman-operator", '[features]\ndefault = []\nunchecked-qualification-inputs = []\n')
        self.write("product", '[features]\nproxy = ["operator/unchecked-qualification-inputs"]\n')
        self.assertTrue(boundary.manifest_findings(self.root))


if __name__ == "__main__":
    unittest.main()
