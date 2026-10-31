"""Synthetic byte/metadata fixtures exercise fail-closed portable admission."""

from contextlib import contextmanager
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from . import adapter, archives, portable_common as c, portable_gate as gate
from .test_activity import c_paths


class Metadata:
    def check(self, item):
        return c.checked(item)

    def read(self, item):
        return c.read(item)

    def file(self, path):
        return self.read(c.descriptor(path))


def raw_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return c.descriptor(path)


def archive_fixture(root):
    directory = root / "ops/durable/A-17"
    config = c.write(root / "CONFIG.json", {"synthetic_fixture": True})
    binding = {
        "execution_episode": c.SOURCE_EPISODE,
        "sequence": 1,
        "label": "A-17",
        "pipeline_config": config,
        "completed_jobs": ["A-17"],
        "previous_ack": None,
    }
    identity = {
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "run_id": "123",
        "run_attempt": "1",
        "head_sha": "a" * 40,
        "job": "synthetic_fixture",
    }
    payload = b"synthetic immutable bytes\n"
    files = [
        {
            "path": "raw/fixture.bin",
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    ]
    manifest = {
        "schema": "hepta.github-actions-archive-manifest.v1",
        "binding": binding,
        "identity": identity,
        "files": files,
        "file_count": 1,
        "payload_bytes": len(payload),
    }
    manifest_item = c.write(directory / "upload/MANIFEST.json", manifest)
    zip_path = root / "new_download.zip"
    with zipfile.ZipFile(zip_path, "w") as saved:
        saved.write(manifest_item["path"], "MANIFEST.json")
        saved.writestr("payload/raw/fixture.bin", payload)
    downloaded = c.descriptor(zip_path)
    sdk = {
        "root": "/work/transport-sdk",
        "metadata": {"synthetic_fixture": True},
        "entry_sha256": "b" * 64,
    }
    artifact = {
        **{key: downloaded[key] for key in ("bytes", "sha256")},
        "id": 22,
        "name": "hepta-r07-123-1-A-17",
        "sdk": "@actions/artifact@6.2.0",
        "sdk_source": sdk,
        "node": "v24.22.1",
        "requested_retention_days": 90,
    }
    client = {
        "id": 22,
        "expected_sha256": artifact["sha256"],
        "digest_mismatch": False,
        "raw_archive": True,
        "sdk": artifact["sdk"],
        "sdk_source": sdk,
    }
    waits = []
    for operation, result in (("upload", artifact), ("download", client)):
        value = {
            "operation": operation,
            "pid": 123,
            "waited_pid": 123,
            "exit_code": 0,
            "timed_out": False,
            "interruption_type": None,
            "measurement": "os.wait4 direct owned child",
            "wall_seconds": 0.1,
            "user_cpu_seconds": 0.02,
            "system_cpu_seconds": 0.01,
            "peak_rss_bytes": 100,
        }
        waits.append(value)
        c.write(directory / (operation + ".wait4.json"), value)
        c.write(
            directory / (operation + ".result.json"),
            {"ok": True, "operation": operation, "result": result},
        )
    cost = {
        "wait4": waits,
        "wall_seconds": 0.3,
        "cpu_seconds": 0.07,
        "transport_child_cpu_seconds": 0.06,
        "parent_self_cpu_delta_seconds": 0.01,
    }
    ack = {
        "schema": "hepta.github-actions-archive-ack.v1",
        "binding": binding,
        "identity": identity,
        "artifact": artifact,
        "manifest": manifest_item,
        "logical_files": files,
        "items_verified": 1,
        "readback": {
            "raw_archive": {**downloaded, "path": "/original/host/archive.zip"},
            "client": client,
            "all_sha256_and_bytes_match": True,
            "independent_device_inodes": [
                {
                    "path": "raw/fixture.bin",
                    "source_device_inode": [7, 111],
                    "staged_device_inode": [7, 222],
                    "readback_device_inode": [7, 333],
                }
            ],
        },
        "cost": cost,
    }
    ack_item = c.write(directory / "ACK.json", ack)
    row = {
        "ack": ack_item,
        **{
            key: ack[key]
            for key in (
                "binding",
                "artifact",
                "manifest",
                "logical_files",
                "items_verified",
                "cost",
            )
        },
    }
    downloads = {
        "barrier:A-17": {
            "provider": {
                **{key: artifact[key] for key in ("id", "name", "bytes", "sha256")},
                "role": "barrier:A-17",
            },
            "download": downloaded,
        }
    }
    original = SimpleNamespace(
        nonnegative=lambda value: type(value) in (float, int) and value >= 0
    )
    return gate.PortableArchives(downloads, sdk, original), row, ack, identity


class SyntheticStore:
    def __init__(self, root):
        self.root, self.admitted, self.inputs = root, True, self

    def descriptor(self, relative):
        return c.descriptor(self.root / relative)

    def read_json(self, relative):
        return c.read(self.descriptor(relative))

    @contextmanager
    def opened(self, path, sha, size, role):
        c.checked({"path": path, "sha256": sha, "bytes": size})
        with open(path, "rb") as stream:
            yield stream


def c_trace_fixture(root):
    paths, unused = c_paths()
    inventory, artifacts = [], []
    for path in paths:
        checkpoint = raw_write(
            root / "stage_C" / path["checkpoint"]["path"],
            b"synthetic checkpoint fixture",
        )
        path["checkpoint"] = {**checkpoint, "path": path["checkpoint"]["path"]}
        inventory.append(
            {
                key: path[key]
                for key in (
                    "seed",
                    "mode",
                    "policy",
                    "checkpoint",
                    "state_sha256",
                    "overrides",
                    "accepted_overrides",
                    "first_legal_divergence_decision",
                    "first_legal_divergence_clock",
                )
            }
        )
        trace = {
            key: value
            for key, value in path.items()
            if not key.startswith("first_legal_divergence_")
        }
        name = path["checkpoint"]["path"].removesuffix(".pt.gz") + ".trace.json.gz"
        item = raw_write(
            root / "stage_C" / name, gzip.compress(json.dumps(trace).encode(), mtime=0)
        )
        artifacts.extend([path["checkpoint"], {**item, "path": name}])
    c.write(
        root / "stage_C/COMPLETE.json",
        {
            "schema": "hepta.fullstudy.C.complete-seal.1",
            "complete": True,
            "training_complete": True,
            "paths": inventory,
            "artifacts": artifacts,
        },
    )
    return SyntheticStore(root)


def review_fixture(root):
    config = {"python": "/opt/runtime/venv/bin/python", "source_commit": "a" * 40}
    config_item = c.write(
        root / "ops/registrations/initial/PIPELINE_CONFIG.json", config
    )
    primary = c.write(root / "ops/COMPLETE.json", {"synthetic_fixture": True})
    terminal = c.write(root / "ops/TERMINAL_CLOSURE.json", {"synthetic_fixture": True})
    science = {
        key: key
        for key in (
            "status",
            "execution_episode",
            "controller_jobs",
            "completion_seals",
            "original_source_files_verified",
            "pipeline",
            "verified",
            "manifest",
            "finalizer_freeze",
        )
    }
    outputs = {
        name: c.write(root / "postseal" / name, {"synthetic_fixture": True})
        for name in ("UNIFIED_REVIEW.json", "INPUTS.json")
    }
    post = {
        "schema": "hepta.execution07.postseal-review.1",
        "complete": True,
        "execution_episode": c.SOURCE_EPISODE,
        "pipeline_config": config_item,
        "terminal_closure": terminal,
        "original_scientific_analysis_changed": False,
        "new_bootstrap_training_scoring_refitting": False,
        "certificate": False,
        "primary_scientific_gate": science,
        "outputs": outputs,
        "status": "COST_COVERAGE_INCOMPLETE",
        "integrity_issues": ["synthetic retained issue"],
        "historical_integrity": {"status": "unknown"},
    }
    post_item = c.write(root / "postseal/COMPLETE.json", post)
    costs = []
    for name in ("postseal_measurement", "pipeline_measurement/children"):
        costs.append(
            {
                **{
                    kind: c.write(
                        root / name / (kind.upper() + ".json"),
                        {"synthetic_fixture": True},
                    )
                    for kind in ("wait4", "closure")
                },
                "cpu_seconds": 1.0,
                "wall_seconds": 2.0,
                "peak_rss_bytes": 100,
            }
        )
    shared = {
        "complete": True,
        "execution_episode": c.SOURCE_EPISODE,
        "pipeline_config": config_item,
        "primary_completion": primary,
        "terminal_closure": terminal,
        "postseal_completion": post_item,
        "scientific_review_disposition": post["status"],
        "postseal_measurement": {k: costs[0][k] for k in ("wait4", "closure")},
    }
    child_item = c.write(
        root / "pipeline_measurement/CHILD_COMPLETE.json",
        {**shared, "schema": "hepta.execution07.lifecycle-child.1"},
    )
    lifecycle = {
        **shared,
        "schema": "hepta.execution07.lifecycle-completion.1",
        "source_commit": config["source_commit"],
        "engineering_status": "ALL_REGISTERED_STAGES_AND_REVIEW_CLOSED",
        "child_completion": child_item,
        "pipeline_measurement": {k: costs[1][k] for k in ("wait4", "closure")},
        "inclusive_pipeline_cpu_seconds": 1.0,
        "inclusive_pipeline_wall_seconds": 2.0,
        "pipeline_peak_rss_bytes": 100,
    }
    life_item = c.write(root / "pipeline_measurement/COMPLETE.json", lifecycle)
    binding = {
        "pins": {
            "postseal_complete": post_item,
            "lifecycle_complete": life_item,
            "primary_complete": primary,
        }
    }
    return locals()


class PortableTests(unittest.TestCase):
    def test_runner_never_decodes_or_emits_admission_after_full_gate_failure(self):
        with tempfile.TemporaryDirectory() as name:
            output = Path(name)
            binding = {"provider": {"head_sha": "a" * 40}}
            item = c.write(output / "BINDING.json", binding)
            c.write(
                output / "PLAN.json",
                {
                    "binding": item,
                    "execution_episode": c.EPISODE,
                    "deadline_monotonic": 999999999,
                    "oom_baseline": {},
                    "current_replay_identity": {},
                },
            )
            phases = []

            def measured(unused_process, phase, unused_argv, *args, **kwargs):
                phases.append(phase)
                if phase == "runtime":
                    c.write(
                        output / "runtime/RUNTIME.json",
                        {
                            "runtime": {"exact_match": True},
                            "three_original_joint_passes": True,
                        },
                    )
                elif phase == "provider":
                    c.write(output / "provider/REQUEST.json", binding["provider"])
                    c.write(
                        output / "provider/RECEIPT.json", {"synthetic_fixture": True}
                    )
                return {"synthetic_measurement_fixture": True}

            with (
                patch.object(c, "load_binding", return_value=(binding, item)),
                patch.object(adapter, "prepare_imports"),
                patch.object(adapter, "owned", side_effect=measured),
                patch.object(
                    gate,
                    "download_map",
                    return_value={
                        "final_scientific": {"download": {}},
                        "final_operations": {"download": {}},
                    },
                ),
                patch.object(archives, "reconstruct", return_value={}),
                patch.object(
                    gate,
                    "admit",
                    side_effect=ValueError(
                        "Original scientific completion gate refused"
                    ),
                ),
                patch.object(adapter, "decode_and_reduce") as decoder,
            ):
                with self.assertRaisesRegex(
                    ValueError, "Original scientific completion gate refused"
                ):
                    adapter.child(
                        SimpleNamespace(
                            binding=item["path"],
                            expected_binding_sha256=item["sha256"],
                            output=str(output),
                        )
                    )
                decoder.assert_not_called()
            self.assertEqual(phases, ["runtime", "original_public_inputs", "provider"])
            self.assertFalse((output / "ADMISSION.json").exists())
            self.assertFalse((output / "DEPLOYMENT_ACTIVITY.json").exists())

    def test_full_postseal_closure_keeps_negative_and_unknown_scientific_findings(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            f = review_fixture(root)
            original = SimpleNamespace(wait4=Mock(side_effect=f["costs"]))
            with patch.object(c, "RUN", root):
                result = gate.final_review_closure(
                    original,
                    Metadata(),
                    f["binding"],
                    f["config"],
                    f["config_item"],
                    f["terminal"],
                    f["science"],
                )
            self.assertEqual(
                result["original_postseal_disposition"], "COST_COVERAGE_INCOMPLETE"
            )
            self.assertEqual(result["historical_integrity"], {"status": "unknown"})
            self.assertEqual(
                result["original_integrity_issues"], f["post"]["integrity_issues"]
            )
            self.assertEqual(original.wait4.call_count, 2)
            self.assertTrue(
                all(call.kwargs["argv"] for call in original.wait4.call_args_list)
            )

    def test_final_seals_original_gate_measurements_and_outputs_cannot_be_substituted(
        self,
    ):
        for reason in (
            "incomplete",
            "scientific_gate",
            "wait4",
            "timing",
            "output",
            "source",
        ):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                f = review_fixture(root)
                if reason in ("incomplete", "scientific_gate"):
                    post = deepcopy(f["post"])
                    if reason == "incomplete":
                        post["complete"] = False
                    else:
                        post["primary_scientific_gate"]["completion_seals"] = "changed"
                    Path(f["post_item"]["path"]).write_text(json.dumps(post))
                    f["binding"]["pins"]["postseal_complete"] = c.descriptor(
                        Path(f["post_item"]["path"])
                    )
                elif reason == "output":
                    Path(f["outputs"]["UNIFIED_REVIEW.json"]["path"]).write_text("{}")
                else:
                    lifecycle = deepcopy(f["lifecycle"])
                    if reason == "wait4":
                        lifecycle["postseal_measurement"]["wait4"] = f["costs"][1][
                            "wait4"
                        ]
                    elif reason == "source":
                        lifecycle["source_commit"] = "b" * 40
                    else:
                        lifecycle["inclusive_pipeline_cpu_seconds"] = 0.0
                    Path(f["life_item"]["path"]).write_text(json.dumps(lifecycle))
                    f["binding"]["pins"]["lifecycle_complete"] = c.descriptor(
                        Path(f["life_item"]["path"])
                    )
                with patch.object(c, "RUN", root), self.assertRaises(ValueError):
                    gate.final_review_closure(
                        SimpleNamespace(wait4=Mock(side_effect=f["costs"])),
                        Metadata(),
                        f["binding"],
                        f["config"],
                        f["config_item"],
                        f["terminal"],
                        f["science"],
                    )

    def test_original_checkout_precedes_duplicate_addon_packages_in_actual_child(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            for tree in ("addon", "source"):
                raw_write(
                    root / tree / "operational/parameter_field_recovery07/process.py",
                    ("marker = '" + tree + "'\n").encode(),
                )
            code = (
                "from pathlib import Path\nimport sys\n"
                "from supplements.parameter_field_deployment_activity_20261031 import adapter\n"
                f"adapter.c.SOURCE = Path({str(root / 'source')!r})\n"
                "adapter.c.original_source = lambda binding: None\n"
                f"sys.path[:0] = [{str(root / 'addon')!r}, {str(root / 'source')!r}]\n"
                "module = adapter.prepare_imports({})\n"
                'assert module.marker == "source"\n'
                "assert sys.path[0] == str(adapter.c.SOURCE)\n"
            )
            subprocess.run(
                [sys.executable, "-B", "-c", code], check=True, capture_output=True
            )

    def test_actual_new_zip_accepts_historical_inode_proof_without_claiming_reproduced_inodes(
        self,
    ):
        with tempfile.TemporaryDirectory() as name:
            verifier, row, ack, identity = archive_fixture(Path(name))
            result = verifier.verify_ack(Metadata(), row, row["binding"], identity)
            self.assertEqual(result, ack)
            evidence = verifier.verified[0]
            self.assertTrue(evidence["original_inode_tuples_are_historical_only"])
            self.assertNotEqual(evidence["current_zip_device_inode"], [7, 333])

    def test_same_historical_inode_and_missing_wait4_are_not_relaxed(self):
        for reason in ("same_inode", "wait4", "sdk", "producer", "zip_drift"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as name:
                verifier, row, ack, identity = archive_fixture(Path(name))
                if reason == "same_inode":
                    ack["readback"]["independent_device_inodes"][0][
                        "readback_device_inode"
                    ] = [7, 111]
                elif reason == "wait4":
                    Path(row["ack"]["path"]).with_name("download.wait4.json").unlink()
                elif reason == "sdk":
                    verifier.sdk = {**verifier.sdk, "entry_sha256": "c" * 64}
                elif reason == "producer":
                    identity = {**identity, "head_sha": "d" * 40}
                else:
                    with open(
                        verifier.downloads["barrier:A-17"]["download"]["path"], "ab"
                    ) as stream:
                        stream.write(b"changed")
                Path(row["ack"]["path"]).write_text(json.dumps(ack))
                row["ack"] = c.descriptor(Path(row["ack"]["path"]))
                with self.assertRaises((ValueError, OSError)):
                    verifier.verify_ack(Metadata(), row, row["binding"], identity)

    def test_zip_population_traversal_links_and_bounds_fail_closed(self):
        for reason in ("duplicate", "escape", "link", "bound", "hidden"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as name:
                path = Path(name) / "invalid.zip"
                with zipfile.ZipFile(path, "w") as saved:
                    if reason == "duplicate":
                        saved.writestr("raw/a", b"a")
                        saved.writestr("raw/a", b"b")
                    elif reason == "escape":
                        saved.writestr("../outside", b"a")
                    elif reason == "link":
                        info = zipfile.ZipInfo("raw/link")
                        info.external_attr = (stat.S_IFLNK | 0o777) << 16
                        saved.writestr(info, b"/outside")
                    else:
                        saved.writestr(
                            "raw/.env" if reason == "hidden" else "raw/a", b"abc"
                        )
                with self.assertRaises(ValueError):
                    archives.Archive(c.descriptor(path), maximum_bytes=2)
                self.assertFalse((Path(name).parent / "outside").exists())

    def test_five_raw_lock_names_allowed_but_nested_or_cas_lookalike_rejected(self):
        for prefix in ("raw/", "payload/raw/", "execution07/raw/"):
            for name in archives.LOCKS:
                self.assertEqual(str(archives.logical(prefix + name)), prefix + name)
        for value in (
            "raw/nested/.ops-slot-0.lock",
            "raw_cas/.ops-slot-0.lock",
            "raw/.git/config",
        ):
            with self.assertRaises(ValueError):
                archives.logical(value)

    def test_isolated_operational_adaptation_preserves_original_globals_and_code(self):
        namespace = {"verify_ack": lambda *args: "original"}
        exec("def operational_gate(value):\n    return verify_ack(value)\n", namespace)
        original = SimpleNamespace(operational_gate=namespace["operational_gate"])
        function, before = original.operational_gate, dict(namespace)
        self.assertEqual(
            gate.adapted_operational_gate(original, lambda value: value + 1, 4), 5
        )
        self.assertIs(original.operational_gate, function)
        self.assertEqual(namespace, before)
        self.assertEqual(original.operational_gate(4), "original")

    def test_gate_failure_propagates_without_decoder_or_original_global_mutation(self):
        namespace = {"verify_ack": lambda *args: "original"}
        exec("def operational_gate(value):\n    return verify_ack(value)\n", namespace)
        original = SimpleNamespace(operational_gate=namespace["operational_gate"])
        decoder = Mock(side_effect=AssertionError("payload read"))

        def reject(unused):
            raise ValueError("synthetic archive gate failure")

        with self.assertRaises(ValueError):
            gate.adapted_operational_gate(original, reject, 4)
            decoder()
        decoder.assert_not_called()
        self.assertEqual(original.operational_gate(4), "original")
        store = SimpleNamespace(admitted=False, read_json=decoder)
        with self.assertRaises(ValueError):
            adapter.decode_and_reduce(
                {"receipt": {"complete": True}, "store": store, "inputs": None}
            )
        decoder.assert_not_called()

    def test_c_join_uses_completion_divergence_and_rejects_conflicting_shared_fields(
        self,
    ):
        with tempfile.TemporaryDirectory() as name:
            store = c_trace_fixture(Path(name))
            rows = adapter.joined_c_paths(store)
            self.assertEqual(len(rows), 32)
            self.assertTrue(all("first_legal_divergence_clock" in row for row in rows))
            complete_path = store.root / "stage_C/COMPLETE.json"
            complete = c.read(c.descriptor(complete_path))
            complete["paths"][0]["overrides"] = 99
            complete_path.write_text(json.dumps(complete))
            with self.assertRaisesRegex(
                ValueError, "trace and completion inventory conflict"
            ):
                adapter.joined_c_paths(store)

    def test_c_join_refuses_missing_or_duplicate_inventory_and_changed_literal_trace(
        self,
    ):
        for reason in ("missing", "duplicate", "changed_trace"):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as name:
                store = c_trace_fixture(Path(name))
                complete_path = store.root / "stage_C/COMPLETE.json"
                complete = c.read(c.descriptor(complete_path))
                if reason == "missing":
                    complete["paths"].pop()
                elif reason == "duplicate":
                    complete["paths"][1] = deepcopy(complete["paths"][0])
                else:
                    item = next(
                        row
                        for row in complete["artifacts"]
                        if row["path"].endswith(".trace.json.gz")
                    )
                    (store.root / "stage_C" / item["path"]).write_bytes(b"changed")
                complete_path.write_text(json.dumps(complete))
                with self.assertRaises(ValueError):
                    adapter.joined_c_paths(store)


if __name__ == "__main__":
    unittest.main()
