from pathlib import Path
import tempfile
import unittest
from cargo_config_boundary import check_cargo_configuration_sources

class CargoConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def add(self, data, sub='codex-rs', basename='config.toml'):
        folder = self.root / sub / '.cargo'
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / basename
        target.write_text(data, encoding='utf-8')
        return target

    def test_approved_existing_windows_rustflags(self):
        self.add('''[target.'cfg(all(windows, target_env = "msvc"))']\nrustflags = ["-C", "link-arg=/STACK:8388608"]\n''')
        self.assertEqual(check_cargo_configuration_sources(self.root), [])

    def test_source_replacement_rejected(self):
        self.add('''[source.crates-io]\nreplace-with = "shadow"\n[source.shadow]\ndirectory = "/unsafe"\n''')
        self.assertIn('[source]', str(check_cargo_configuration_sources(self.root)))

    def test_registry_default_rejected(self):
        self.add('''[registry]\ndefault = "malicious"\n''')
        self.assertIn('[registry]', str(check_cargo_configuration_sources(self.root)))

    def test_other_registries_rejected(self):
        self.add('''[registries.shadow]\nindex = "https://example.invalid/index"\n''')
        self.assertIn('[registries]', str(check_cargo_configuration_sources(self.root)))

    def test_root_and_member_configs_rejected(self):
        self.add('[source.crates-io]\nreplace-with = "shadow"\n', sub='')
        self.add('[source.crates-io]\nreplace-with = "shadow"\n', sub='codex-rs/hepta-types', basename='config')
        self.assertEqual(len(check_cargo_configuration_sources(self.root)), 2)

    def test_redirected_cargo_home_rejected(self):
        self.add('''[env]\nCARGO_HOME = "/tmp/fake-registry"\n''')
        self.assertIn('CARGO_HOME', str(check_cargo_configuration_sources(self.root)))

    def test_tool_wrapper_rejected(self):
        self.add('''[build]\nrustc-wrapper = "./tool"\n''')
        self.assertIn('rustc-wrapper', str(check_cargo_configuration_sources(self.root)))

    def test_target_runner_rejected(self):
        self.add('''[target.x86_64-unknown-linux-gnu]\nrunner = "/tmp/shadow"\n''')
        self.assertIn('runner', str(check_cargo_configuration_sources(self.root)))

    def test_target_linker_rejected(self):
        self.add('''[target.aarch64-unknown-linux-gnu]\nlinker = "/tmp/shadow"\n''')
        self.assertIn('linker', str(check_cargo_configuration_sources(self.root)))

    def test_invalid_toml_refused(self):
        self.add('[source\n')
        self.assertIn('unreadable Cargo configuration', str(check_cargo_configuration_sources(self.root)))

    def test_symlink_file_refused(self):
        outside = self.root / 'outside'
        outside.write_text('''[source.crates-io]\nreplace-with = "shadow"\n''')
        folder = self.root / 'codex-rs' / '.cargo'
        folder.mkdir(parents=True)
        (folder / 'config.toml').symlink_to(outside)
        self.assertIn('symbolic link', str(check_cargo_configuration_sources(self.root)))

    def test_symlink_dir_refused(self):
        outside = self.root / 'outside'
        outside.mkdir()
        inside = self.root / 'codex-rs' / 'hepta-types'
        inside.mkdir(parents=True)
        (inside / '.cargo').symlink_to(outside, target_is_directory=True)
        self.assertIn('symbolic link', str(check_cargo_configuration_sources(self.root)))

    def test_malformed_target_refused(self):
        self.add('[target]\nx = "non-table"\n')
        self.assertIn('malformed target', str(check_cargo_configuration_sources(self.root)))

if __name__ == '__main__':
    unittest.main()
