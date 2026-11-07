"""One bounded Kaggle batch; transport completion never means experiment success.

The caller materializes a <=2 MiB source bundle and the original metadata subset
under /tmp. This worker verifies them, transfers only the nine pinned JPEGs,
retains failed commands, and exports a <=64 MiB content-addressed evidence pack.
No pretrained weights, venv, or model cache are exported. Colab is not supported
by this 1800-second provider profile. There are no automatic retries.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import sys
import time

from .cloud_evidence import (
    Commands,
    LIMIT,
    artifact_manifest,
    pack_evidence,
    sha,
    verify_source,
    write,
)


NATIVE = (
    "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit."
)


PILOT = "ndu_portfolio.pilot_cli"


STAGES = {
    "driver": 10,
    "venv": 15,
    "torch_setup": 160,
    "model_dependencies": 90,
    "cuda_check": 20,
    "transfer_images": 90,
    "plan": 15,
    "models": 420,
    "device_smoke": 90,
    "collect": 210,
    "score_collect": 20,
    "fit": 150,
    "evaluate": 420,
    "score_evaluate": 20,
}


def gpu_check(output, dtype):
    result = {"requested_dtype": dtype, "verified": False}
    try:
        import torch

        result.update(
            torch=torch.__version__,
            torch_cuda=torch.version.cuda,
            is_available=torch.cuda.is_available(),
            device_count=torch.cuda.device_count(),
        )
        if (
            not result["is_available"]
            or not result["device_count"]
            or "+cpu" in result["torch"]
        ):
            raise RuntimeError("Actual CUDA is absent; model acquisition is forbidden")
        result.update(
            device_name=torch.cuda.get_device_name(0),
            capability=list(torch.cuda.get_device_capability(0)),
        )
        if dtype == "bfloat16" and not torch.cuda.is_bf16_supported(
            including_emulation=False
        ):
            raise RuntimeError("Native bfloat16 is unsupported")
        value = torch.ones((4, 4), device="cuda:0", dtype=getattr(torch, dtype))
        result["actual_sum"] = float((value @ value).sum().item())
        torch.cuda.synchronize(0)
        result["verified"] = result["actual_sum"] == 64.0
        if not result["verified"]:
            raise RuntimeError(
                "Actual CUDA arithmetic did not match the smoke contract"
            )
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        write(output, result)


def transfer_images(
    pool, output, *, prior_transfer_receipt, prior_transfer_receipt_sha256
):
    from ndu_semantic_state.acquire_vizwiz import (
        CAP,
        DownloadBudget,
        IMAGES,
        RangeArchive,
    )
    from ndu_semantic_state.materials import check_file
    from .pilot_data import CASE_IDS, HISTORY_SHA, MANIFEST_SHA, load_pool
    import zipfile

    pool, output = Path(pool), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = time.process_time(), time.perf_counter()
    report = {
        "status": "started",
        "kind": "exact_metadata_subset_and_nine_image_transfer",
        "full_annotation_archive_present": False,
        "original_metadata_regenerated": False,
        "scientific_acceptance": False,
        "images": [],
    }
    download = DownloadBudget(output)
    try:
        if (
            sha(pool / "CANDIDATES.json") != MANIFEST_SHA
            or sha(pool / "HISTORY.json") != HISTORY_SHA
        ):
            raise ValueError("Original candidate/history pins changed")
        manifest = json.loads((pool / "CANDIDATES.json").read_text())
        cases = manifest["cases"]
        if tuple(c["id"] for c in cases) != CASE_IDS:
            raise ValueError("Nine-case source roster changed")
        prior = json.loads(
            check_file(pool, manifest["acquisition_receipt"], limit=8 * 1024**2)
        )
        if (
            prior["cumulative_body_bytes_read"] != 11064483
            or prior["cumulative_body_byte_cap"] != CAP
        ):
            raise ValueError("Prior shared acquisition budget differs")
        carry_path = Path(prior_transfer_receipt)
        if carry_path.is_symlink() or carry_path.stat().st_size > 131072:
            raise ValueError("Invalid cumulative transfer receipt file")
        carry_bytes = carry_path.read_bytes()
        if hashlib.sha256(carry_bytes).hexdigest() != prior_transfer_receipt_sha256:
            raise ValueError("Cumulative transfer receipt hash differs")
        carry = json.loads(carry_bytes)
        counts = tuple(
            carry.get(k)
            for k in (
                "prior_body_bytes",
                "new_body_bytes",
                "cumulative_body_bytes",
                "shared_cap_bytes",
            )
        )
        if (
            any(type(value) is not int for value in counts)
            or counts[0] < prior["cumulative_body_bytes_read"]
            or counts[1] < 0
            or counts[0] + counts[1] != counts[2]
            or not 17669796 <= counts[2] <= CAP
            or counts[3] != CAP
            or carry.get("kind") != report["kind"]
            or carry.get("status") not in ("completed", "failed")
        ):
            raise ValueError("Cumulative shared material budget differs")
        admission = carry.get("admission", carry.get("source_pins", {}))
        if (
            admission.get("manifest_sha256") != MANIFEST_SHA
            or admission.get("history_sha256") != HISTORY_SHA
        ):
            raise ValueError("Cumulative receipt source identity differs")
        ids = [row["id"] for row in carry.get("images", [])]
        if len(set(ids)) != len(ids) or set(ids) - set(CASE_IDS):
            raise ValueError("Cumulative receipt image roster differs")
        if carry["status"] == "completed" and tuple(ids) != CASE_IDS:
            raise ValueError("Completed cumulative receipt image roster differs")
        # The floor is the already-spent, published CPU transfer, not a new allowance.
        # The dispatcher must serialize consumers and pin the latest receipt.
        download.bytes_read = carry["cumulative_body_bytes"]
        (output / "PRIOR_TRANSFER.json").write_bytes(carry_bytes)
        report.update(
            prior_body_bytes=download.bytes_read,
            shared_cap_bytes=CAP,
            prior_transfer_receipt_sha256=prior_transfer_receipt_sha256,
            source_pins={
                "manifest_sha256": MANIFEST_SHA,
                "history_sha256": HISTORY_SHA,
            },
            budget_scope="serialized_material_body_bytes_including_prior_attempts",
        )
        with zipfile.ZipFile(RangeArchive(download, IMAGES)) as archive:
            files = [info for info in archive.infolist() if not info.is_dir()]
            members = {PurePosixPath(info.filename).name: info for info in files}
            if len(members) != len(files):
                raise ValueError("Ambiguous ZIP image member names")
            for case in cases:
                target = pool / case["image"]["path"]
                if (
                    not target.resolve().is_relative_to(pool.resolve())
                    or target.is_symlink()
                ):
                    raise ValueError("Image path escapes original pool")
                if target.exists():
                    check_file(pool, case["image"], limit=32 * 1024**2)
                    report["images"].append(
                        {"id": case["id"], "status": "verified_existing"}
                    )
                    continue
                member = members[case["id"].split(":", 1)[1]]
                if member.file_size != case["image"]["bytes"]:
                    raise ValueError("Official ZIP image size changed")
                data = archive.read(member)
                if hashlib.sha256(data).hexdigest() != case["image"]["sha256"]:
                    raise ValueError("Official image differs from original source pin")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                report["images"].append(
                    {"id": case["id"], "status": "transferred", "bytes": len(data)}
                )
        _, report["admission"] = load_pool(pool)
        report["status"] = "completed"
    finally:
        report.update(
            cumulative_body_bytes=download.bytes_read,
            new_body_bytes=download.bytes_read - report.get("prior_body_bytes", 0),
            cpu_seconds=time.process_time() - start[0],
            wall_seconds=time.perf_counter() - start[1],
        )
        if report["status"] == "started":
            report["status"] = "failed"
        write(output / "TRANSFER.json", report)


def run(args):
    start = time.process_time(), time.perf_counter()
    deadline = start[1] + args.budget_seconds
    output, work, source, pool = map(
        Path, (args.output, args.workspace, args.source_root, args.pool)
    )
    output.mkdir(parents=True, exist_ok=False)
    evidence = work / "evidence"
    models = work / "models"
    report = {
        "request_id": args.request_id,
        "source_sha": args.source_sha,
        "experiment_status": "Failed",
        "scientific_acceptance": False,
        "native_owner_verified": False,
        "transport_success_is_not_experiment_success": True,
        "provider": "kaggle-batch",
        "provider_cap_seconds": 1800,
        "worker_budget_seconds": args.budget_seconds,
        "actual_device": {"verified": False, "status": "cuda_preflight_not_completed"},
        "artifact_complete": False,
        "stages": [
            {"name": k, "wall_cap_seconds": v, "status": "not_started"}
            for k, v in STAGES.items()
        ],
        "unknown_costs": [
            "energy",
            "GPU_charge",
            "source_bootstrap_and_transfer_before_worker",
            "final_export_write",
        ],
    }
    previous = {
        s: signal.getsignal(s) for s in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)
    }

    def expired(_signal, _frame):
        raise TimeoutError("Total worker wall deadline reached")

    def cancelled(signum, _frame):
        report["cancellation_signal"] = signum
        raise KeyboardInterrupt("Cloud worker cancellation")

    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, args.budget_seconds)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        work.mkdir(parents=True, exist_ok=False)
        evidence.mkdir()
        if (
            not 60 <= args.budget_seconds <= 1740
            or not work.resolve().is_relative_to(Path("/tmp"))
            or not source.resolve().is_relative_to(Path("/tmp"))
        ):
            raise ValueError(
                "This profile requires /tmp work/source and a 60..1740s budget; Colab is excluded"
            )
        verify_source(
            source, args.source_manifest, args.source_manifest_sha256, args.source_sha
        )
        profile = json.loads(Path(args.profile).read_text())
        if profile["device"] != "cuda:0" or profile["dtype"] not in (
            "float16",
            "bfloat16",
            "float32",
        ):
            raise ValueError("Declare an actual CUDA engineering profile")
        shutil.copyfile(args.source_manifest, evidence / "SOURCE_MANIFEST.json")
        shutil.copyfile(args.profile, evidence / "PROFILE.json")
        os.environ.update(
            PYTHONPATH=str(source / "scripts") + os.pathsep + str(source),
            PYTHONDONTWRITEBYTECODE="1",
            HF_HOME=str(work / "hf-cache"),
            PIP_NO_INPUT="1",
        )
        commands = Commands(evidence, report, deadline)
        commands.execute(
            "driver",
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,driver_version,memory.total",
                "--format=csv,noheader",
            ],
        )
        commands.execute("venv", [sys.executable, "-m", "venv", str(work / "venv")])
        python = str(work / "venv/bin/python")
        commands.execute(
            "torch_setup",
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--index-url",
                "https://download.pytorch.org/whl/cu126",
                "torch==2.8.0",
                "torchvision==0.23.0",
            ],
        )
        commands.execute(
            "model_dependencies",
            [
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "numpy==2.3.5",
                "Pillow==13.0.0",
                "transformers==4.57.3",
                "diffusers==0.35.2",
                "accelerate==1.12.0",
                "safetensors==0.7.0",
                "num2words==0.5.14",
            ],
        )
        worker = [python, "-m", "ndu_portfolio.cloud_pilot"]
        commands.execute(
            "cuda_check",
            worker
            + [
                "gpu-check",
                "--output",
                str(evidence / "CUDA.json"),
                "--dtype",
                profile["dtype"],
            ],
        )
        commands.execute(
            "transfer_images",
            worker
            + [
                "transfer-images",
                "--pool",
                str(pool),
                "--output",
                str(evidence / "transfer"),
                "--prior-transfer-receipt",
                args.prior_transfer_receipt,
                "--prior-transfer-receipt-sha256",
                args.prior_transfer_receipt_sha256,
            ],
        )
        plan = evidence / "PLAN.json"
        cli = [python, "-m", PILOT]
        commands.execute(
            "plan",
            cli
            + [
                "plan",
                "--pool",
                str(pool),
                "--profile",
                args.profile,
                "--source-sha",
                args.source_sha,
                "--output",
                str(plan),
            ],
        )
        commands.execute(
            "models", [python, "-m", NATIVE + "acquire_models", "--root", str(models)]
        )
        smoke = evidence / "smoke"
        commands.execute(
            "device_smoke",
            [
                python,
                "-m",
                NATIVE + "device_smoke",
                "--models",
                str(models),
                "--image",
                str(pool / "data/VizWiz_train_00000000/input.jpg"),
                "--output",
                str(smoke),
                "--source-sha",
                args.source_sha,
                "--device",
                "cuda:0",
                "--dtype",
                profile["dtype"],
            ],
        )
        common = ["--pool", str(pool), "--plan", str(plan), "--plan-sha256", sha(plan)]
        device = [
            "--models",
            str(models),
            "--device-smoke",
            str(smoke / "DEVICE_SMOKE.json"),
            "--device-smoke-sha256",
            sha(smoke / "DEVICE_SMOKE.json"),
        ]
        for name, stage, prior in (
            ("collect", "collect", None),
            ("score_collect", "score", "collect"),
            ("fit", "fit", "score_collect"),
            ("evaluate", "evaluate", "fit"),
            ("score_evaluate", "score", "evaluate"),
        ):
            command = cli + [stage] + common + ["--output", str(evidence / name)]
            if stage in ("collect", "evaluate"):
                command += device
            if prior:
                path = evidence / prior / "PHASE.json"
                command += ["--input", str(path), "--input-sha256", sha(path)]
            if stage == "score":
                command += ["--input-phase", prior]
            commands.execute(name, command)
        report["experiment_status"] = "CompletedEngineeringPilot"
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            for path in models.rglob("*.json*"):
                if path.name in (
                    "MANIFEST.json",
                    "ACQUISITION.json",
                    "ACQUISITION_ATTEMPTS.jsonl",
                ):
                    target = evidence / "model-records" / path.relative_to(models)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            if (evidence / "CUDA.json").exists():
                report["actual_device"] = json.loads(
                    (evidence / "CUDA.json").read_text()
                )
            report.update(
                launcher_cpu_seconds=time.process_time() - start[0],
                elapsed_wall_seconds=time.perf_counter() - start[1],
            )
            write(evidence / "CAMPAIGN.json", report)
            report["evidence_pack"] = pack_evidence(
                {"execution": evidence, "materials_subset": pool},
                output / "evidence.tar.gz",
                deadline,
            )
            report["artifact_complete"] = True
        except BaseException as error:
            report.update(
                experiment_status="Failed",
                artifact_complete=False,
                packaging_error={"type": type(error).__name__, "message": str(error)},
            )
            pack = output / "evidence.tar.gz"
            if pack.exists() and pack.stat().st_size > LIMIT - 1024**2:
                pack.unlink()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            report.update(
                launcher_cpu_seconds=time.process_time() - start[0],
                elapsed_wall_seconds=time.perf_counter() - start[1],
            )
            write(output / "BOOTSTRAP_RESULT.json", report)
            artifact_manifest(output, args.request_id)
    return 0  # Kaggle artifact transport requires COMPLETE; inspect experiment_status.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run")
    for field in (
        "source-root",
        "source-sha",
        "source-manifest",
        "source-manifest-sha256",
        "pool",
        "profile",
        "workspace",
        "output",
        "request-id",
        "prior-transfer-receipt",
        "prior-transfer-receipt-sha256",
    ):
        execute.add_argument("--" + field, required=True)
    execute.add_argument("--budget-seconds", type=float, default=1740)
    probe = sub.add_parser("gpu-check")
    probe.add_argument("--output", required=True)
    probe.add_argument(
        "--dtype", choices=("float16", "bfloat16", "float32"), required=True
    )
    transfer = sub.add_parser("transfer-images")
    transfer.add_argument("--pool", required=True)
    transfer.add_argument("--output", required=True)
    transfer.add_argument("--prior-transfer-receipt", required=True)
    transfer.add_argument("--prior-transfer-receipt-sha256", required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "gpu-check":
        gpu_check(args.output, args.dtype)
    else:
        transfer_images(
            args.pool,
            args.output,
            prior_transfer_receipt=args.prior_transfer_receipt,
            prior_transfer_receipt_sha256=args.prior_transfer_receipt_sha256,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
