"""Hardware scout regressions: no untrusted PR code on personal runners."""

import errno
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from strong_rag_cpu_scout import SCHEMA, STANDARD_IMAGES, census, main
from strong_rag_resource_snapshot import capture

SHA = "a" * 40


def cpuinfo(flags):
    return "processor : 0\nmodel name : Test CPU\nflags : " + " ".join(flags) + "\n"


class StandardRunnerScoutTests(unittest.TestCase):
    def test_ineligible_epyc_is_recorded_not_hidden(self):
        row = census(
            cpuinfo(["avx2", "fma"]),
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-24.04",
            source_commit=SHA,
        )
        self.assertEqual(row["schema"], SCHEMA)
        self.assertFalse(row["eligible_cpu_for_unchanged_bf16_reader"])
        self.assertFalse(row["same_hardware_on_next_run_guaranteed"])
        self.assertEqual(row["new_model_calls"], 0)
        self.assertFalse(row["production_accepted"])

    def test_accelerated_cpu_is_candidate_not_model_success(self):
        row = census(
            cpuinfo(["avx2", "avx512_bf16"]),
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-22.04",
            source_commit=SHA,
        )
        self.assertTrue(row["eligible_cpu_for_unchanged_bf16_reader"])
        self.assertFalse(row["eligible_host_reserved"])
        self.assertEqual(row["new_model_calls"], 0)
        self.assertFalse(row["hardware"]["full_inference_latency_qualified"])

    def test_only_documented_standard_hosted_runner_images(self):
        self.assertEqual(len(STANDARD_IMAGES), 3)
        for label in ("self-hosted", "rog", "pocket4", "ubuntu-latest-gpu", "desktop"):
            with self.subTest(label=label), self.assertRaises(ValueError):
                census(
                    cpuinfo(["avx512_bf16"]),
                    machine="x86_64",
                    runner_arch="X64",
                    image=label,
                    source_commit=SHA,
                )

    def test_source_sha_and_mixed_cpu_must_fail_closed(self):
        with self.assertRaises(ValueError):
            census(
                cpuinfo(["avx512_bf16"]),
                machine="x86_64",
                runner_arch="X64",
                image="ubuntu-24.04",
                source_commit="main",
            )
        mixed = (
            cpuinfo(["avx512_bf16"])
            + "processor : 1\nmodel name : Test CPU\nflags : avx2\n"
        )
        row = census(
            mixed,
            machine="x86_64",
            runner_arch="X64",
            image="ubuntu-24.04",
            source_commit=SHA,
        )
        self.assertFalse(row["eligible_cpu_for_unchanged_bf16_reader"])

    def test_cli_writes_once_and_never_overwrites_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "result.json"
            with (
                patch(
                    "strong_rag_cpu_scout.sys.argv",
                    [
                        "scout",
                        "--runner-image",
                        "ubuntu-24.04",
                        "--source-commit",
                        SHA,
                        "--output",
                        str(result_path),
                    ],
                ),
                patch("strong_rag_cpu_scout.sys.platform", "linux"),
                patch("strong_rag_cpu_scout.platform.machine", return_value="x86_64"),
                patch(
                    "strong_rag_cpu_scout.Path.read_text",
                    return_value=cpuinfo(["avx2"]),
                ),
                patch.dict("strong_rag_cpu_scout.os.environ", {"RUNNER_ARCH": "X64"}),
                patch(
                    "strong_rag_cpu_scout.write_snapshot", return_value={}
                ) as resources,
            ):
                self.assertEqual(main(), 0)
                with result_path.open(encoding="utf-8") as stream:
                    report = json.load(stream)
                self.assertEqual(report["source_commit"], SHA)
                with self.assertRaises(FileExistsError):
                    main()
                resources.assert_called_once_with(
                    result_path.with_name("result-resources.json"),
                    source_commit=SHA,
                    runner_image="ubuntu-24.04",
                )


class ResourceSnapshotTests(unittest.TestCase):
    def fixture(self, root, *, process="/parent/child", mount_root="/"):
        proc = root / "proc"
        (proc / "self").mkdir(parents=True)
        (proc / "meminfo").write_text(
            "MemTotal:       16777216 kB\nMemAvailable:   15728640 kB\n"
        )
        (proc / "self/cgroup").write_text("0::" + process + "\n")
        (proc / "self/mountinfo").write_text(
            f"29 23 0:26 {mount_root} /sys/fs/cgroup rw - cgroup2 cgroup rw\n"
        )
        mount = root / "sys/fs/cgroup"
        child = mount / "parent/child"
        child.mkdir(parents=True)
        for directory in (mount, mount / "parent", child):
            (directory / "cgroup.controllers").write_text("cpu memory\n")
            (directory / "cgroup.subtree_control").write_text("memory\n")
        for directory, limit in ((mount / "parent", 6), (child, 12)):
            (directory / "cgroup.type").write_text("domain\n")
            (directory / "memory.max").write_text(str(limit * 1024**3) + "\n")
            (directory / "memory.current").write_text("1048576\n")
        return proc, mount, child

    def snapshot(self, root, proc):
        return capture(
            source_commit=SHA, runner_image="ubuntu-22.04", proc=proc, system=root
        )

    def test_actual_root_absence_and_smaller_ancestor_are_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, _ = self.fixture(root)
            row = self.snapshot(root, proc)
            self.assertEqual(
                row["observed_complete_hierarchy_memory_ceiling_bytes"], 6 * 1024**3
            )
            self.assertTrue(row["global_root_interface_signature_observed"])
            self.assertFalse(row["hidden_ancestor_limits_not_attested"])
            self.assertEqual(row["errors"], [])
            self.assertFalse(row["eligible_host_reserved"])
            self.assertFalse(row["full_inference_latency_qualified"])
            self.assertEqual(row["new_model_calls"], 0)

    def test_global_root_process_has_no_memory_max_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, _ = self.fixture(root, process="/")
            row = self.snapshot(root, proc)
            self.assertEqual(
                row["observed_complete_hierarchy_memory_ceiling_bytes"], 16 * 1024**3
            )
            self.assertEqual(
                row["visible_cgroup_limits"][0]["limit_state"],
                "global_root_has_no_memory_max",
            )

    def test_namespace_slash_and_unlimited_visible_limit_do_not_hide_ancestry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, mount, _ = self.fixture(root, process="/")
            (mount / "cgroup.type").write_text("domain\n")
            (mount / "memory.current").write_text("1048576\n")
            for limit, bound in (
                (str(12 * 1024**3), 12 * 1024**3),
                ("max", 16 * 1024**3),
            ):
                with self.subTest(limit=limit):
                    (mount / "memory.max").write_text(limit + "\n")
                    row = self.snapshot(root, proc)
                    self.assertEqual(
                        row["observed_visible_capacity_upper_bound_bytes"], bound
                    )
                    self.assertIsNone(
                        row["observed_complete_hierarchy_memory_ceiling_bytes"]
                    )
                    self.assertTrue(row["hidden_ancestor_limits_not_attested"])
                    self.assertFalse(row["global_root_interface_signature_observed"])

    def test_bind_mounted_subtree_cannot_attest_external_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, mount, _ = self.fixture(root, process="/parent", mount_root="/parent")
            (mount / "cgroup.type").write_text("domain\n")
            (mount / "memory.max").write_text(str(12 * 1024**3) + "\n")
            (mount / "memory.current").write_text("1048576\n")
            row = self.snapshot(root, proc)
            self.assertEqual(
                row["observed_visible_capacity_upper_bound_bytes"], 12 * 1024**3
            )
            self.assertIsNone(row["observed_complete_hierarchy_memory_ceiling_bytes"])
            self.assertTrue(row["hidden_ancestor_limits_not_attested"])

    def test_zero_limit_and_missing_child_limit_are_not_unlimited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, child = self.fixture(root)
            (child / "memory.max").write_text("0\n")
            zero = self.snapshot(root, proc)
            self.assertEqual(
                zero["observed_complete_hierarchy_memory_ceiling_bytes"], 0
            )
            (child / "memory.max").unlink()
            missing = self.snapshot(root, proc)
            self.assertIsNone(
                missing["observed_complete_hierarchy_memory_ceiling_bytes"]
            )
            self.assertFalse(missing["visible_cgroup_hierarchy_resolved"])
            self.assertTrue(missing["errors"])

    def test_disabled_controller_requires_visible_parent_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, mount, child = self.fixture(root)
            (child / "memory.max").unlink()
            (child / "memory.current").unlink()
            unknown = self.snapshot(root, proc)
            self.assertIsNone(
                unknown["observed_complete_hierarchy_memory_ceiling_bytes"]
            )
            (mount / "parent/cgroup.subtree_control").write_text("\n")
            inherited = self.snapshot(root, proc)
            self.assertEqual(
                inherited["observed_complete_hierarchy_memory_ceiling_bytes"],
                6 * 1024**3,
            )
            self.assertEqual(
                inherited["visible_cgroup_limits"][0]["limit_state"],
                "memory_controller_disabled_by_visible_parent",
            )

    def test_permission_error_is_not_the_global_root_missing_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, mount, _ = self.fixture(root)
            original = Path.open

            def guarded(path, *args, **kwargs):
                if path == mount / "cgroup.type":
                    raise PermissionError(errno.EACCES, "denied", str(path))
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", guarded):
                row = self.snapshot(root, proc)
            self.assertFalse(row["global_root_interface_signature_observed"])
            self.assertIsNone(row["observed_complete_hierarchy_memory_ceiling_bytes"])
            self.assertEqual(
                row["read_failures"][str(mount / "cgroup.type")]["errno"], errno.EACCES
            )

    def test_missing_type_with_existing_limit_is_not_a_global_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, mount, _ = self.fixture(root, process="/")
            (mount / "memory.max").write_text(str(12 * 1024**3) + "\n")
            row = self.snapshot(root, proc)
            self.assertFalse(row["global_root_interface_signature_observed"])
            self.assertIsNone(row["observed_complete_hierarchy_memory_ceiling_bytes"])

    def test_membership_drift_invalidates_complete_hierarchy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, _ = self.fixture(root)
            original, reads = Path.open, 0

            def changing(path, *args, **kwargs):
                nonlocal reads
                if path == proc / "self/cgroup":
                    reads += 1
                    if reads == 2:
                        return io.BytesIO(b"0::/changed\n")
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", changing):
                row = self.snapshot(root, proc)
            self.assertFalse(row["membership_and_mount_view_stable"])
            self.assertIsNone(row["observed_complete_hierarchy_memory_ceiling_bytes"])
            self.assertTrue(row["hidden_ancestor_limits_not_attested"])

    def test_overmounted_interface_and_legacy_cgroup_stay_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, _ = self.fixture(root)
            mountinfo = proc / "self/mountinfo"
            original = mountinfo.read_text()
            mountinfo.write_text(
                original
                + "30 29 0:27 / /sys/fs/cgroup/cgroup.type rw - tmpfs tmpfs rw\n"
            )
            overlay = self.snapshot(root, proc)
            self.assertIsNone(
                overlay["observed_complete_hierarchy_memory_ceiling_bytes"]
            )
            self.assertFalse(overlay["global_root_interface_signature_observed"])
            mountinfo.write_text(original)
            (proc / "self/cgroup").write_text("5:memory:/parent/child\n")
            legacy = self.snapshot(root, proc)
            self.assertIsNone(
                legacy["observed_complete_hierarchy_memory_ceiling_bytes"]
            )

    def test_malformed_limit_and_symlink_interface_are_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc, _, child = self.fixture(root)
            (child / "memory.max").write_text("maximum\n")
            invalid = self.snapshot(root, proc)
            self.assertIsNone(
                invalid["observed_complete_hierarchy_memory_ceiling_bytes"]
            )
            (child / "memory.max").unlink()
            (root / "fake-max").write_text(str(64 * 1024**3) + "\n")
            (child / "memory.max").symlink_to(root / "fake-max")
            linked = self.snapshot(root, proc)
            self.assertIsNone(
                linked["observed_complete_hierarchy_memory_ceiling_bytes"]
            )


if __name__ == "__main__":
    unittest.main()
