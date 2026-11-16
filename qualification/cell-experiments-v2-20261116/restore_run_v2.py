"""Reconstruct original v2 bytes, verify all models, and optionally probe adapters.

Absolute journal paths remain original provenance. This tool never rewrites an
owner database, resumes an optimizer, trains a model, or grants adoption.
"""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import time
import zipfile

import export_run_v2 as policy

sys.dont_write_bytecode = True

COLD_DRIVER = """import json,sys
from pathlib import Path
from cell_experiments.study_v2_support import cold
print(json.dumps(cold(Path(sys.argv[1]),sys.argv[2]),sort_keys=True))
"""


def check_identity(path, expected):
    actual = policy.identity(path)
    if any(actual[key] != expected[key] for key in ("bytes", "sha256", "git_blob")):
        raise ValueError("file identity differs: " + str(path))
    return actual


def bounded_path(root, name):
    if not isinstance(name, str) or "\\" in name or "\0" in name:
        raise ValueError("invalid archive path")
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or relative.as_posix() != name
        or relative.parts[0] not in ("run", "source", "execution-logs")
    ):
        raise ValueError("archive path is outside original roots")
    return Path(root).joinpath(*relative.parts)


def reconstruct_stream(export_dir, stream, destination):
    with Path(destination).open("xb") as output:
        for index, part in enumerate(stream["parts"]):
            if (
                part["index"] != index
                or Path(part["file"]).name != part["file"]
                or not part["file"].endswith(".zip")
            ):
                raise ValueError("part order or filename differs")
            path = Path(export_dir) / part["file"]
            check_identity(path, part)
            if part["bytes"] >= policy.BINARY_LIMIT:
                raise ValueError("published binary exceeds limit")
            with zipfile.ZipFile(path) as archive:
                if archive.namelist() != ["payload.bin"]:
                    raise ValueError("part is not a one-payload ZIP container")
                info = archive.getinfo("payload.bin")
                if (
                    info.compress_type != zipfile.ZIP_STORED
                    or info.flag_bits & 1
                    or info.file_size != part["payload_bytes"]
                    or not 0 < info.file_size <= policy.PAYLOAD_BYTES
                ):
                    raise ValueError("payload size or format differs")
                payload = archive.read(info)
            if hashlib.sha256(payload).hexdigest() != part["payload_sha256"]:
                raise ValueError("payload digest differs")
            output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    check_identity(destination, stream)
    return Path(destination)


def extract_stream(stream_path, stream, originals, output):
    expected = [item for item in originals if item["archive"] == stream["file"]]
    expected_map = {item["path"]: item for item in expected}
    if len(expected_map) != len(expected) or set(stream["members"]) != set(
        expected_map
    ):
        raise ValueError("stream member inventory differs")
    with zipfile.ZipFile(stream_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected_map):
            raise ValueError("unexpected or duplicate archive member")
        for info in archive.infolist():
            item = expected_map[info.filename]
            if (
                info.file_size != item["bytes"]
                or info.flag_bits & 1
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError("member size/type differs")
            target = bounded_path(output, info.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            count = 0
            with archive.open(info) as source, target.open("xb") as destination:
                for block in iter(lambda: source.read(1048576), b""):
                    count += len(block)
                    if count > item["bytes"]:
                        raise ValueError("member exceeded declared original bytes")
                    destination.write(block)
            check_identity(target, item)


def verify_originals(output, inventory):
    expected = {item["path"] for item in inventory["inventory"]}
    actual = set()
    for prefix in ("run", "source", "execution-logs"):
        for path in policy.files_under(Path(output) / prefix):
            actual.add(
                prefix + "/" + path.relative_to(Path(output) / prefix).as_posix()
            )
    if actual != expected:
        raise ValueError("restored original file set differs")
    for item in inventory["inventory"]:
        check_identity(bounded_path(output, item["path"]), item)
    return len(expected)


def verify_models(output, expected_count, source_digest):
    source = Path(output) / "source"
    package = source / "scripts/cell_experiments"
    observed = {
        p.name: policy.identity(p)["sha256"] for p in sorted(package.glob("*.py"))
    }
    if (
        len(observed) != 44
        or hashlib.sha256(policy.canonical(observed)).hexdigest() != source_digest
    ):
        raise ValueError("restored executable source snapshot differs")
    sys.path.insert(0, str(source / "scripts"))
    coding = importlib.import_module("cell_experiments.coding_sft")
    if not Path(coding.__file__).resolve().is_relative_to(source.resolve()):
        raise ValueError("model verifier was imported from outside restored source")
    run = Path(output) / "run"
    paths = [run / "parent.json", *sorted((run / "models").glob("*/manifest.json"))]
    if len(paths) != expected_count:
        raise ValueError("expected model manifest count differs")
    result = {}
    for path in paths:
        value = json.loads(path.read_bytes())
        result[str(path.relative_to(run))] = coding.verify_model(value, run)
    return result


def probe_adapters(output):
    """Fresh child + restored root + original last B input; no new task sample."""
    output = Path(output)
    results = {}
    environment = {
        **os.environ,
        "PYTHONPATH": str(output / "source/scripts"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
    }
    for name in ("final_answer", "trajectory"):
        request = json.loads(
            (output / "run/cold_checks" / name / "REQUEST.json").read_bytes()
        )
        original = json.loads(
            (output / "run/evaluation/B" / name / "EVALUATION.json").read_bytes()
        )
        warm = original["rows"][-1]["steps"][-1]["output"]
        if (
            hashlib.sha256(policy.canonical(warm)).hexdigest()
            != request["warm_output_digest"]
        ):
            raise ValueError("original warm B output binding differs")
        # The CLI's stage meter would create cold-<name>.json inside restored
        # originals, where that historical receipt already exists. Use the same
        # frozen cold function directly and retain replay logs only below.
        command = [sys.executable, "-c", COLD_DRIVER, str(output / "run"), name]
        before = time.perf_counter()
        directory = output / "RESTORE_PROBES" / name
        directory.mkdir(parents=True, exist_ok=False)
        try:
            process = subprocess.run(
                command,
                cwd=output,
                env=environment,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired as failure:
            policy.write_new(
                directory / "PROCESS.json",
                {
                    "status": "TIMEOUT",
                    "argv": command,
                    "stdout": str(failure.stdout or ""),
                    "stderr": str(failure.stderr or ""),
                    "wall_seconds": time.perf_counter() - before,
                },
            )
            raise ValueError("restored adapter probe timed out") from failure
        policy.write_new(
            directory / "PROCESS.json",
            {
                "returncode": process.returncode,
                "argv": command,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "wall_seconds": time.perf_counter() - before,
            },
        )
        if process.returncode:
            raise ValueError("restored adapter probe failed")
        restored = json.loads(process.stdout)
        compared = (
            "answer",
            "input_tokens",
            "output_tokens",
            "loaded_model_digest",
            "input_sha256",
            "rendered_input_sha256",
            "message_protocol",
        )
        if (
            any(restored["prediction"].get(k) != warm.get(k) for k in compared)
            or restored["pid"] in (os.getpid(), warm["pid"])
            or restored["ppid"] != os.getpid()
            or restored["model_digest"] != request["model_digest"]
            or restored["request_digest"]
            != hashlib.sha256(policy.canonical(request)).hexdigest()
        ):
            raise ValueError(
                "new-directory adapter output differs from original B prediction"
            )
        result = {
            "status": "MATCH",
            "model": name,
            "restored": restored,
            "original_warm_output_sha256": request["warm_output_digest"],
            "input_tokens": restored["prediction"]["input_tokens"],
            "output_tokens": restored["prediction"]["output_tokens"],
            "wall_seconds": time.perf_counter() - before,
            "independent_sample_increment": 0,
            "semantic_tests_reexecuted": False,
            "optimizer_resumed": False,
            "adoption_performed": False,
            "portable_owner_recovery_verified": False,
            "cold_entrypoint": "cell_experiments.study_v2_support.cold",
            "original_stage_resource_receipts_preserved": True,
        }
        policy.write_new(directory / "RESULT.json", result)
        results[name] = result
    return results


def restore(options):
    export_dir, output = (
        Path(options.export_dir).absolute(),
        Path(options.output).absolute(),
    )
    manifest_path = export_dir / "EXPORT.json"
    if policy.identity(manifest_path)["sha256"] != options.expected_export_sha256:
        raise ValueError("external EXPORT.json SHA256 differs")
    manifest = json.loads(manifest_path.read_bytes())
    if (
        manifest.get("schema") != "hepta.repository-study.export.v2"
        or manifest.get("status") != "COMPLETE"
    ):
        raise ValueError("complete supported export required")
    if output == export_dir or output.is_relative_to(export_dir):
        raise ValueError("restore directory must be outside the archive directory")
    output.mkdir(parents=True, exist_ok=False)
    started, wall, cpu = time.time_ns(), time.perf_counter(), time.process_time()
    policy.write_new(
        output / "RESTORE_STARTED.json",
        {
            "started_at_ns": started,
            "export_sha256": options.expected_export_sha256,
            "probe_adapters_requested": options.probe_adapters,
        },
    )
    try:
        check_identity(export_dir / "INVENTORY.json", manifest["inventory"])
        inventory = json.loads((export_dir / "INVENTORY.json").read_bytes())
        if (
            inventory["file_count"] != len(inventory["inventory"])
            or len({item["path"] for item in inventory["inventory"]})
            != len(inventory["inventory"])
            or inventory["source_digest"] != manifest["source_digest"]
        ):
            raise ValueError("original inventory differs")
        for path in (Path(__file__), Path(policy.__file__)):
            check_identity(path, manifest["tools"][path.name])
        streams = output / "_reconstructed_streams"
        streams.mkdir()
        if set(manifest["archives"]) != {
            "receipts.zip",
            "base-metadata.zip",
            "checkpoints.zip",
        }:
            raise ValueError("archive stream set differs")
        for name, stream in manifest["archives"].items():
            if stream["file"] != name:
                raise ValueError("stream filename differs")
            stream_path = reconstruct_stream(export_dir, stream, streams / name)
            extract_stream(stream_path, stream, inventory["inventory"], output)
        external = [
            item
            for item in inventory["inventory"]
            if item["archive"] == "external_base"
        ]
        if (
            len(external) != 1
            or external[0]["path"] != policy.EXTERNAL_PATH
            or external[0]["sha256"] != policy.BASE_SHA256
            or external[0]["bytes"] != policy.BASE_BYTES
        ):
            raise ValueError("external base inventory differs")
        check_identity(options.base_model, external[0])
        target = bounded_path(output, policy.EXTERNAL_PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            Path(options.base_model).open("rb") as source,
            target.open("xb") as destination,
        ):
            shutil.copyfileobj(source, destination, 1048576)
        check_identity(target, external[0])
        count = verify_originals(output, inventory)
        models = verify_models(
            output, options.expected_model_count, manifest["source_digest"]
        )
        probes = probe_adapters(output) if options.probe_adapters else {}
        verify_originals(output, inventory)
        result = {
            "schema": "hepta.repository-study.restore.v2",
            "status": "COMPLETE",
            "started_at_ns": started,
            "completed_at_ns": time.time_ns(),
            "export_sha256": options.expected_export_sha256,
            "verified_original_files": count,
            "expected_original_files": inventory["file_count"],
            "verified_model_manifests": models,
            "model_manifest_count": len(models),
            "source_digest": manifest["source_digest"],
            "source_snapshot_verified": True,
            "new_directory_adapter_probes": probes,
            "inference_calls": len(probes),
            "new_independent_samples": 0,
            "training_updates": 0,
            "optimizer_deserialized": False,
            "optimizer_resumed": False,
            "owner_journal_paths_rewritten": False,
            "portable_owner_recovery_verified": False,
            "adoption_performed": False,
            "wall_seconds": time.perf_counter() - wall,
            "calling_process_cpu_seconds": time.process_time() - cpu,
            "cpu_scope": "restore parent only; optional inference child CPU excluded",
            "energy_joules": None,
        }
        policy.write_new(output / "RESTORE_RESULT.json", result)
        return {
            "status": "COMPLETE",
            "output": str(output),
            "files": count,
            "model_manifests": len(models),
            "adapter_probes": len(probes),
            "restore_receipt_sha256": policy.identity(output / "RESTORE_RESULT.json")[
                "sha256"
            ],
        }
    except Exception as failure:
        policy.write_new(
            output / "RESTORE_FAILED.json",
            {
                "error": type(failure).__name__ + ": " + str(failure),
                "completed_at_ns": time.time_ns(),
                "partial_artifacts_retained": True,
            },
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("export-dir", "output", "base-model", "expected-export-sha256"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--expected-model-count", type=int, default=8)
    parser.add_argument("--probe-adapters", action="store_true")
    print(json.dumps(restore(parser.parse_args()), sort_keys=True))
