"""Real Git controls for the job-private Clippy compatibility resolver."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".github" / "scripts"))
import run_argument_comment_ui as resolver


class ClippyResolutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / "source"
        subprocess.run(
            ["git", "init", "--initial-branch=master", str(self.work)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        self.commit_toolchain("nightly-2025-09-04")
        parent = self.command("rev-parse", "HEAD")
        parent_tree = self.command("rev-parse", "HEAD^{tree}")
        self.commit_toolchain("nightly-2025-09-18")
        self.pin = resolver.ClippyPin(
            self.command("rev-parse", "HEAD"),
            self.command("rev-parse", "HEAD^{tree}"),
            parent,
            parent_tree,
            "nightly-2025-09-18",
            "nightly-2025-09-04",
        )
        self.mirror = self.root / "mirror.git"
        subprocess.run(
            ["git", "clone", "--bare", self.work.as_uri(), str(self.mirror)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def command(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.work), *args], text=True
        ).strip()

    def commit_toolchain(self, nightly):
        (self.work / "rust-toolchain.toml").write_text(
            f'[toolchain]\nchannel = "{nightly}"\n'
        )
        self.command("add", "rust-toolchain.toml")
        self.command(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-m",
            nightly,
        )

    def test_real_original_url_clone_uses_verified_private_source(self):
        self.assertEqual(
            resolver.verify_mirror(self.mirror, self.pin),
            {"bare": "true", "head_ref": "refs/heads/master", **vars(self.pin)},
        )
        inherited = dict(os.environ)
        unchanged = dict(inherited)
        drivers = self.root / "fresh-drivers"
        drivers.mkdir()
        child = resolver.scoped_environment(inherited, self.mirror, drivers)
        checkout = self.root / "original-url-clone"
        subprocess.run(
            ["git", "clone", resolver.CLIPPY_URL, str(checkout)],
            env=child,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        actual = subprocess.check_output(
            ["git", "-C", str(checkout), "rev-parse", "HEAD", "HEAD^{tree}", "HEAD^"],
            text=True,
        ).splitlines()
        self.assertEqual(
            actual, [self.pin.commit, self.pin.tree, self.pin.first_parent]
        )
        self.assertEqual(inherited, unchanged)
        self.assertEqual(list(drivers.iterdir()), [])

    def test_moved_compatibility_ref_is_rejected(self):
        resolver.git(
            self.mirror, "update-ref", "refs/heads/master", self.pin.first_parent
        )
        with self.assertRaises(resolver.ResolutionError):
            resolver.verify_mirror(self.mirror, self.pin)

    def test_missing_real_first_parent_is_rejected(self):
        shallow = self.root / "shallow.git"
        subprocess.run(
            ["git", "clone", "--bare", "--depth=1", self.work.as_uri(), str(shallow)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self.assertRaises(resolver.ResolutionError):
            resolver.verify_mirror(shallow, self.pin)


if __name__ == "__main__":
    unittest.main()
