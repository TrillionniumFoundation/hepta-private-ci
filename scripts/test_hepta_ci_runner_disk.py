import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("disk", Path(__file__).with_name("hepta_ci_runner_disk.py"))
disk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(disk)


class NativeDiskTests(unittest.TestCase):
    def test_hosted_only_fails_closed(self):
        base = {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux", "RUNNER_ENVIRONMENT": "github-hosted"}
        disk.require_hosted_linux(base)
        for key, changed in (("GITHUB_ACTIONS", "false"), ("RUNNER_OS", "Windows"), ("RUNNER_ENVIRONMENT", "self-hosted")):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                disk.require_hosted_linux({**base, key: changed})

    def test_allowlist_is_not_an_untrusted_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = root / "work"
            workspace.mkdir()
            fake = root / "sdk"
            fake.mkdir()
            self.assertFalse(disk.eligible(fake, allowlist=(), workspace=workspace))
            self.assertTrue(disk.eligible(fake, allowlist=(fake,), workspace=workspace))
            self.assertFalse(disk.eligible(workspace, allowlist=(workspace,), workspace=workspace))
            self.assertFalse(disk.eligible(root, allowlist=(root,), workspace=workspace))

    def test_no_follow_symlinks_or_delete_mounts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "work"
            work.mkdir()
            link = root / "sdk_link"
            link.symlink_to(work, target_is_directory=True)
            self.assertFalse(disk.eligible(link, allowlist=(link,), workspace=work))
            target = root / "sdk"
            target.mkdir()
            with patch.object(Path, "is_mount", return_value=True):
                self.assertFalse(disk.eligible(target, allowlist=(target,), workspace=work))

    def test_dry_run_never_invokes_sudo(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(disk.subprocess, "run") as run:
            root = Path(temp)
            work = root / "work"
            work.mkdir()
            sdk = root / "sdk"
            sdk.mkdir()
            outcome = disk.apply_reclaim(work, minimum_bytes=80 * disk.GIB, apply=False, allowlist=(sdk,))
            self.assertEqual(outcome["sdk_paths_reclaimed_or_planned"], [str(sdk)])
            self.assertFalse(outcome["sufficient"])
            self.assertTrue(sdk.is_dir())
            run.assert_not_called()

    def test_clean_capacity_skip_does_not_delete(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(disk.subprocess, "run") as run:
            root = Path(temp)
            work = root / "work"
            work.mkdir()
            sdk = root / "sdk"
            sdk.mkdir()
            outcome = disk.apply_reclaim(work, minimum_bytes=0, apply=True, allowlist=(sdk,))
            self.assertEqual(outcome["sdk_paths_reclaimed_or_planned"], [])
            run.assert_not_called()

    def test_attempts_only_allowlisted_delete_with_noninteractive_sudo(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(disk.subprocess, "run") as run:
            root = Path(temp)
            work = root / "work"
            work.mkdir()
            sdk = root / "optional"
            sdk.mkdir()
            disk.apply_reclaim(work, minimum_bytes=80 * disk.GIB, apply=True, allowlist=(sdk,))
            run.assert_called_once_with(["sudo", "rm", "-rf", "--", str(sdk)], check=True)


if __name__ == "__main__":
    unittest.main()
