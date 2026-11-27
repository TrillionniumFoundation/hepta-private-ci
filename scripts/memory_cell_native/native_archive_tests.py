"""Synthetic byte-snapshot controls; no model, network, or historical replay."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_backend
import native_ci
import native_trial

sys.path.insert(0, str(Path(__file__).resolve().parent / "current"))
import native_process_restore


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, sort_keys=True).encode()


def tar_bytes(members):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return result.getvalue()


class ArchiveSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.assertNotIn("torch", sys.modules)

    def tar_fixture(self):
        evidence = b"synthetic evidence"
        commit_id = "1" * 40
        commit = json_bytes({"sha": commit_id, "commit": {"tree": {"sha": "2" * 40}}})
        dataset = json_bytes(
            {
                "cases": [
                    {
                        "id": "fixture",
                        "fixed_commit": commit_id,
                        "commit_evidence_sha256": digest(commit),
                        "symptom": "synthetic symptom",
                        "repair_id": "synthetic repair",
                        "failed_run_id": 1,
                        "success_run_id": 2,
                        "source_digest": digest(evidence),
                    }
                ],
                "source_inventory": {digest(evidence): len(evidence)},
                "manifest_sha256": digest(b"synthetic manifest"),
            }
        )
        members = {
            "producer/dataset.json": dataset,
            "producer/evidence/" + digest(evidence): evidence,
            "inputs/ci-incidents/commit-" + commit_id + ".json": commit,
            "inputs/ci-incidents/marker.txt": b"original",
        }
        raw = tar_bytes(members)
        path = self.root / "inputs.tar.gz"
        path.write_bytes(raw)
        args = SimpleNamespace(
            archive=str(path),
            archive_bytes=len(raw),
            archive_sha256=digest(raw),
            dataset_sha256=digest(dataset),
            case_id="fixture",
            out=str(self.root / "prepared"),
        )
        return args, members, raw

    def zip_fixture(self):
        base = self.root / "base"
        base.mkdir()
        (base / "sentinel.bin").write_bytes(b"synthetic base")
        inventory = native_backend.file_set(base, base.iterdir())
        base_identity = native_backend.sha(native_backend.canonical(inventory))
        document = b'{"value":"synthetic"}'
        adapter = b"synthetic adapter, not a model"
        training_receipt = {"updates": 96}
        lineage = json_bytes(
            {
                "training": training_receipt,
                "adapter_sha256": digest(adapter),
                "roots": [digest(document)],
                "base_identity": base_identity,
            }
        )
        members = {
            "current/model_config.json": json_bytes(
                {
                    "pins": {
                        "manifest_sha256": digest(lineage),
                        "base_identity": base_identity,
                    }
                }
            ),
            "current/report.json": json_bytes(
                {
                    "source_head": native_process_restore.HEAD,
                    "engineering_pass": True,
                    "training_updates_reused": 96,
                    "training_updates_added": 0,
                }
            ),
            "run/source-before.json": json_bytes({"head": native_process_restore.HEAD}),
            "run/trial/protocol.json": b"{}",
            "run/trial/training.json": json_bytes(
                {"receipt": training_receipt, "manifest_sha256": digest(lineage)}
            ),
            "run/trial/source_document.json": document,
            "run/trial/checkpoint/adapter_model.safetensors": adapter,
            "run/trial/checkpoint/adapter_config.json": b"{}",
            "run/trial/checkpoint/lineage.json": lineage,
            "run/trial/checkpoint/README.md": b"original",
        }

        def pack(values):
            output = io.BytesIO()
            with zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_STORED
            ) as archive:
                for name, data in values.items():
                    archive.writestr(name, data)
                for index in range(5758 - len(values)):
                    archive.writestr(f"unused/{index}", b"")
            return output.getvalue()

        raw = pack(members)
        path = self.root / "inputs.zip"
        path.write_bytes(raw)
        args = SimpleNamespace(
            archive=path,
            out=self.root / "restored",
            repo=self.root,
            base=base,
            acquire_base=False,
            download_to=None,
        )
        return args, members, raw, pack

    def test_tar_path_replacement_keeps_captured_members_and_identity(self):
        args, members, raw = self.tar_fixture()
        replacement = tar_bytes(
            {**members, "inputs/ci-incidents/marker.txt": b"replaced"}
        )
        original_open = tarfile.open

        def replace_then_parse(*arguments, **keywords):
            Path(args.archive).write_bytes(replacement)
            return original_open(*arguments, **keywords)

        with (
            mock.patch.object(
                native_trial.tarfile, "open", side_effect=replace_then_parse
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            native_trial.prepare(args)
        output = Path(args.out)
        self.assertEqual(
            (output / "imported/inputs/ci-incidents/marker.txt").read_bytes(),
            b"original",
        )
        self.assertEqual(
            json.loads((output / "source_mapping.json").read_text())["archive_sha256"],
            digest(raw),
        )
        self.assertEqual(Path(args.archive).read_bytes(), replacement)

    def test_tar_cli_requires_both_archive_pins_before_preparation(self):
        args, _, _ = self.tar_fixture()
        original = [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(Path(native_trial.__file__)),
            "prepare",
            "--archive",
            args.archive,
            "--dataset-sha256",
            args.dataset_sha256,
            "--case-id",
            args.case_id,
            "--out",
            args.out,
        ]
        for omitted in ("both", "bytes", "sha256"):
            with self.subTest(omitted=omitted):
                command = original.copy()
                if omitted == "sha256":
                    command += ["--archive-bytes", str(args.archive_bytes)]
                if omitted == "bytes":
                    command += ["--archive-sha256", args.archive_sha256]
                result = subprocess.run(
                    command, capture_output=True, text=True, timeout=10
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("the following arguments are required:", result.stderr)
                if omitted != "sha256":
                    self.assertIn("--archive-bytes", result.stderr)
                if omitted != "bytes":
                    self.assertIn("--archive-sha256", result.stderr)
                self.assertFalse(Path(args.out).exists())

    def test_tar_wrong_archive_pin_is_rejected_before_parsing(self):
        args, _, _ = self.tar_fixture()
        args.archive_sha256 = "0" * 64
        with mock.patch.object(native_trial.tarfile, "open") as parser:
            with self.assertRaisesRegex(ValueError, "archive bytes differ"):
                native_trial.prepare(args)
        parser.assert_not_called()

    def test_tar_compressed_size_is_rejected_before_parsing(self):
        args, _, raw = self.tar_fixture()
        Path(args.archive).write_bytes(raw + b"x")
        with mock.patch.object(native_trial.tarfile, "open") as parser:
            with self.assertRaisesRegex(ValueError, "archive bytes differ"):
                native_trial.prepare(args)
        parser.assert_not_called()

    def test_tar_oversized_dataset_is_rejected_before_member_read(self):
        args, members, _ = self.tar_fixture()
        data = b" " * (4 * 1024 * 1024 + 1)
        raw = tar_bytes({**members, "producer/dataset.json": data})
        Path(args.archive).write_bytes(raw)
        args.archive_bytes = len(raw)
        args.archive_sha256 = digest(raw)
        args.dataset_sha256 = digest(data)
        with mock.patch.object(tarfile.TarFile, "extractfile") as extract:
            with self.assertRaisesRegex(ValueError, "bounded regular evidence member"):
                native_trial.prepare(args)
        extract.assert_not_called()

    def test_zip_path_replacement_keeps_captured_members_and_identity(self):
        args, members, raw, pack = self.zip_fixture()
        replacement = pack({**members, "run/trial/checkpoint/README.md": b"replaced"})
        original_zip = zipfile.ZipFile

        def replace_then_parse(*arguments, **keywords):
            args.archive.write_bytes(replacement)
            return original_zip(*arguments, **keywords)

        with (
            mock.patch.object(native_process_restore, "ZIP_BYTES", len(raw)),
            mock.patch.object(native_process_restore, "ZIP_SHA", digest(raw)),
            mock.patch.object(
                native_process_restore.zipfile,
                "ZipFile",
                side_effect=replace_then_parse,
            ),
            mock.patch.object(native_process_restore, "api") as api,
            mock.patch.object(native_process_restore, "acquire") as acquire,
        ):
            native_process_restore.restore(args)
        self.assertEqual(
            (args.out / "run/trial/checkpoint/README.md").read_bytes(), b"original"
        )
        restoration = json.loads((args.out / "restoration.json").read_text())
        self.assertEqual(restoration["archive_sha256"], digest(raw))
        self.assertFalse(restoration["production_qualified"])
        self.assertEqual(args.archive.read_bytes(), replacement)
        api.assert_not_called()
        acquire.assert_not_called()

    def test_zip_wrong_archive_pin_is_rejected_before_parsing(self):
        args, _, raw, _ = self.zip_fixture()
        with (
            mock.patch.object(native_process_restore, "ZIP_BYTES", len(raw)),
            mock.patch.object(native_process_restore, "ZIP_SHA", "0" * 64),
            mock.patch.object(native_process_restore.zipfile, "ZipFile") as parser,
        ):
            with self.assertRaisesRegex(ValueError, "ZIP bytes differ"):
                native_process_restore.restore(args)
        parser.assert_not_called()

    def test_zip_compressed_size_is_rejected_before_parsing(self):
        args, _, raw, _ = self.zip_fixture()
        args.archive.write_bytes(raw + b"x")
        with (
            mock.patch.object(native_process_restore, "ZIP_BYTES", len(raw)),
            mock.patch.object(native_process_restore, "ZIP_SHA", digest(raw)),
            mock.patch.object(native_process_restore.zipfile, "ZipFile") as parser,
        ):
            with self.assertRaisesRegex(ValueError, "ZIP bytes differ"):
                native_process_restore.restore(args)
        parser.assert_not_called()

    def test_prepare_command_receives_the_actual_manifest_pins(self):
        args, _, _ = self.tar_fixture()
        manifest = {
            "archive_bytes": args.archive_bytes,
            "archive_sha256": args.archive_sha256,
            "dataset_sha256": args.dataset_sha256,
            "case_id": args.case_id,
        }
        binary = self.root / "unused-binary"
        binary.write_bytes(b"never executed")
        invocation = SimpleNamespace(
            repo=str(self.root),
            binary=str(binary),
            out=str(self.root / "run"),
            expected_head="synthetic-head",
            model_out=str(self.root / "unused-model"),
        )
        commands = []

        class StopBeforeTraining(Exception):
            pass

        def command(output, name, arguments, **keywords):
            commands.append((name, arguments))
            if name == "prepare-source":
                raise StopBeforeTraining("synthetic caller boundary")

        with (
            mock.patch.object(
                native_ci, "identity", return_value={"head": invocation.expected_head}
            ),
            mock.patch.object(
                native_ci,
                "validate_inputs",
                return_value=(manifest, Path(args.archive)),
            ),
            mock.patch.object(
                native_ci, "acquire", return_value=Path(invocation.model_out)
            ),
            mock.patch.object(native_ci, "model_environment", return_value={}),
            mock.patch.object(native_ci, "command", side_effect=command),
        ):
            with self.assertRaises(StopBeforeTraining):
                native_ci.execute(invocation)
        self.assertEqual(
            [name for name, _ in commands], ["source-archive", "prepare-source"]
        )
        argv = commands[-1][1]
        self.assertIn("--archive-bytes", argv)
        self.assertIn("--archive-sha256", argv)
        self.assertEqual(
            argv[argv.index("--archive-bytes") + 1], manifest["archive_bytes"]
        )
        self.assertEqual(
            argv[argv.index("--archive-sha256") + 1], manifest["archive_sha256"]
        )


if __name__ == "__main__":
    unittest.main()
