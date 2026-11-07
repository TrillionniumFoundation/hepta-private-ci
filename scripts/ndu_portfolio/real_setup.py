"""Meter common model initialization before the bounded text-controller pilot.

All compared episodes start with the same resident VLM. Initialization remains
inside the phase and worker deadlines, with its actual cost retained once.
No deployment-frequency amortization or production cost conclusion is invented.
"""

from pathlib import Path
import json
import time

from .real_execution import _sha, _write


def warm_backend(plan, args):
    from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.local_models import (
        LocalModels,
    )

    profile = plan["profile"]
    start = time.process_time(), time.perf_counter()
    receipt = {
        "status": "started",
        "source_sha": plan["source_sha"],
        "claim_status": "HOLD",
        "cache_policy": "common_resident_vlm_before_all_compared_episodes",
        "charged_once_in_inclusive_phase_meter": True,
        "charged_to_first_policy_episode": False,
        "deployment_amortization_frequency": None,
        "unknown_costs": ["energy", "accelerator_charge", "final_receipt_write"],
    }
    try:
        if set(plan["allowed_actions"]) - {"perceive", "text", "stop"}:
            raise ValueError(
                "This common-residency contract covers the text pilot only"
            )
        backend = LocalModels(
            Path(args.models) / "vlm",
            Path(args.models) / "sd",
            threads=profile["threads"],
            device=profile["device"],
            dtype=profile["dtype"],
        )
        backend._placement()
        if profile["device"].startswith("cuda"):
            if (
                not args.device_smoke
                or not args.device_smoke_sha256
                or _sha(args.device_smoke) != args.device_smoke_sha256
            ):
                raise ValueError(
                    "CUDA pilot needs a separately pinned actual device smoke"
                )
            smoke = json.loads(Path(args.device_smoke).read_text())
            actual = backend.identity()
            if (
                smoke["status"] != "completed"
                or smoke["gpu_execution_verified"] is not True
                or smoke["source_sha"] != plan["source_sha"]
                or any(
                    smoke["backend"][key] != actual[key]
                    for key in ("device", "dtype", "reviewed_model_pins", "versions")
                )
            ):
                raise ValueError(
                    "Actual device smoke does not qualify this exact runtime profile"
                )
            receipt["device_smoke_sha256"] = args.device_smoke_sha256
        # Loading verifies complete fixed weights. It does not generate training data.
        backend._activate("vlm")
        backend.synchronize()
        receipt.update(status="completed", backend=backend.identity())
        return backend
    except (Exception, KeyboardInterrupt) as error:
        receipt.update(
            status="failed", error={"type": type(error).__name__, "message": str(error)}
        )
        raise
    finally:
        receipt.update(
            cpu_seconds=time.process_time() - start[0],
            wall_seconds=time.perf_counter() - start[1],
        )
        receipt["engineering_cost"] = (
            receipt["cpu_seconds"] * profile["cpu_tariff"]
            + receipt["wall_seconds"] * profile["wall_tariff"]
        )
        _write(Path(args.output) / "SHARED_SETUP.json", receipt)
