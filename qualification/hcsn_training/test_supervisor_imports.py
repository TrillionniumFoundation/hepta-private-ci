"""Fresh isolated interpreters exercise the supervisor's source-only bundle."""

import importlib.machinery
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "linux", "supervisor startup requires Linux")
class SupervisorImportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="hcsn-source-imports-")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name).resolve()

    def checkout(self, name):
        source = self.directory/name/"qualification"/"hcsn_training"
        source.mkdir(parents=True)
        (source/"__init__.py").write_text("")
        sibling = source.parent/"hcsn"
        sibling.mkdir()
        (sibling/"__init__.py").write_text("")
        for module in ("supervisor.py", "supervisor_store.py"):
            shutil.copyfile(Path(__file__).with_name(module), source/module)
        return source

    def initialize(self, source):
        store = source.parents[1]/"private-store"
        return subprocess.run(
            [sys.executable, "-I", "-B", str(source/"supervisor.py"), "--root", str(store), "--initialize"],
            cwd=source.parents[1], capture_output=True, timeout=5)

    def assert_refused(self, source, reason, marker):
        result = self.initialize(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(reason.encode(), result.stderr)
        self.assertFalse(marker.exists(), "unapproved module executed before refusal")
        self.assertFalse((source.parents[1]/"private-store").exists())

    def test_root_namespace_and_source_initializer_are_supported(self):
        for mode in ("namespace", "initializer"):
            with self.subTest(mode=mode):
                source = self.checkout(mode)
                marker = source.parents[1]/"initializer-marker"
                if mode == "initializer":
                    (source.parent/"__init__.py").write_text(
                        f"from pathlib import Path\nPath({str(marker)!r}).write_text('source')\n")
                result = self.initialize(source)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
                self.assertTrue((source.parents[1]/"private-store"/"store.json").is_file())
                self.assertEqual(marker.exists(), mode == "initializer")

    def test_sourceless_bytecode_is_refused_before_execution(self):
        source = self.checkout("sourceless")
        module, marker = source/"supervisor_store.py", source.parents[1]/"bytecode-marker"
        module.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('bytecode')\n")
        py_compile.compile(str(module), cfile=str(module.with_suffix(".pyc")), doraise=True)
        module.unlink()
        self.assert_refused(source, "repository modules require Python source", marker)

    def test_source_roots_cannot_be_shadowed_by_sibling_modules(self):
        for name in ("qualification", "hcsn_training", "hcsn"):
            with self.subTest(name=name):
                source = self.checkout("root-shadow-"+name)
                marker = source.parents[1]/"root-shadow-marker"
                parent = source.parents[1] if name == "qualification" else source.parent
                if name != "qualification":
                    (parent/name/"__init__.py").unlink()
                (parent/(name+".py")).write_text(
                    f"from pathlib import Path\nPath({str(marker)!r}).write_text('shadowed')\n")
                if name == "hcsn":
                    module = source/"supervisor_store.py"
                    module.write_bytes(b"import qualification.hcsn\n"+module.read_bytes())
                self.assert_refused(source, "repository source roots must be packages", marker)

    def test_extension_loader_cannot_shadow_approved_source(self):
        source = self.checkout("extension")
        extension = source/("supervisor_store"+importlib.machinery.EXTENSION_SUFFIXES[0])
        extension.write_bytes(b"not a native extension")
        # The policy must reject the loader itself, before a native loader can
        # attempt dlopen; a generic invalid-extension failure would not suffice.
        self.assert_refused(source, "repository modules require Python source", source.parents[1]/"marker")

    def test_out_of_bundle_source_is_refused_before_execution(self):
        source = self.checkout("unbundled")
        marker = source.parents[1]/"unbundled-marker"
        (source.parent/"unbundled.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('unbundled')\n")
        module = source/"supervisor_store.py"
        module.write_bytes(b"import qualification.unbundled\n"+module.read_bytes())
        self.assert_refused(source, "import outside repository source bundle", marker)

    def test_foreign_package_search_location_is_refused(self):
        source = self.checkout("foreign-namespace")
        foreign, marker = source.parent/"unbundled", source.parents[1]/"namespace-marker"
        foreign.mkdir()
        (foreign/"supervisor_store.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('foreign')\n")
        (source/"supervisor_store.py").unlink()
        (source/"__init__.py").write_text(f"__path__.append({str(foreign)!r})\n")
        self.assert_refused(source, "repository namespace path changed", marker)

    def test_source_symlink_inside_the_bundle_is_refused(self):
        source = self.checkout("source-alias")
        module, marker = source/"supervisor_store.py", source.parents[1]/"alias-marker"
        alias = source.parent/"hcsn"/"other_source.py"
        alias.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('aliased')\n")
        module.unlink()
        module.symlink_to(alias)
        self.assert_refused(source, "repository source path redirected", marker)

    def test_checkout_root_does_not_shadow_installed_runtime_modules(self):
        source = self.checkout("runtime-shadow")
        marker = source.parents[1]/"runtime-shadow-marker"
        (source.parents[1]/"statistics.py").write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).write_text('shadowed')\n")
        module = source/"supervisor_store.py"
        module.write_bytes(b"import statistics\n"+module.read_bytes())
        result = self.initialize(source)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertFalse(marker.exists())
        self.assertTrue((source.parents[1]/"private-store"/"store.json").is_file())


if __name__ == "__main__":
    unittest.main()
