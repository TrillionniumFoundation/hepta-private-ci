"""Explicit execution policy and bounded, public-API CUDA evidence helpers."""

import math
import subprocess


def execution_policy(config):
    steps = config.get("population_checkpoint_steps", 0)
    if type(steps) is not int or steps not in (0, 1):
        raise ValueError("population_checkpoint_steps must be 0 (original) or 1 (fixed candidate)")
    fraction = config.get("cuda_memory_fraction")
    if fraction is not None:
        if (type(fraction) not in (int, float) or not math.isfinite(fraction)
                or not 0 < fraction <= 1):
            raise ValueError("cuda_memory_fraction must be finite and in (0, 1]")
        if not str(config.get("device", "cpu")).startswith("cuda"):
            raise ValueError("cuda_memory_fraction requires a CUDA device; no CPU fallback")
    return dict(population_checkpoint_steps=steps, cuda_memory_fraction=fraction)


def implementation_record(encoder):
    steps = getattr(encoder, "segment_steps", 0)
    return dict(encoder_class=type(encoder).__name__, population_checkpoint_steps=steps,
                use_reentrant=False if steps else None,
                preserve_rng_state=True if steps else None,
                gradient_horizon="full sequence",
                training_cost_includes_recomputation=bool(steps))


def configure_cuda(torch, device, fraction):
    """Bind stable device facts and an explicit allocator policy before any fit.

    Missing optional metadata stays missing. Failure to select the requested
    device or apply its requested cap prevents training; no uncapped retry.
    """
    result = dict(uuid=None, name=None, driver_version=None, compute_capability=None,
                  total_memory_bytes=None, requested_memory_fraction=fraction,
                  memory_fraction_set=False, memory_fraction_readback=None,
                  allocator_limit_bytes=None, setup_error=None, metadata_missing_reasons={},
                  memory_limit_scope="PyTorch process allocator; not a GPU reservation or external-allocation limit")
    if device.type != "cuda":
        result["metadata_missing_reasons"]["cuda"] = "CPU execution has no CUDA device"
        return result
    if not torch.cuda.is_available():
        result["setup_error"] = "CUDA requested but unavailable; no CPU fallback"
        result["metadata_missing_reasons"]["cuda"] = result["setup_error"]
        return result
    try:
        torch.cuda.set_device(device)
        props = torch.cuda.get_device_properties(device)
        result.update(name=props.name, total_memory_bytes=props.total_memory,
                      compute_capability=[props.major, props.minor])
        uuid = getattr(props, "uuid", None)
        result["uuid"] = (str(uuid).strip() or None) if uuid is not None else None
        if fraction is not None:
            torch.cuda.set_per_process_memory_fraction(float(fraction), device)
            result["memory_fraction_set"] = True
    except Exception as exc:
        result["setup_error"] = f"CUDA execution setup failed: {type(exc).__name__}: {exc}"
        return result
    try:
        actual = float(torch.cuda.memory.get_per_process_memory_fraction(device))
        if not math.isfinite(actual) or not 0 <= actual <= 1:
            raise ValueError("invalid allocator-fraction readback")
        result["memory_fraction_readback"] = actual
        result["allocator_limit_bytes"] = int(result["total_memory_bytes"]*actual)
        if fraction is not None and not math.isclose(actual, fraction, rel_tol=0, abs_tol=1e-12):
            result["setup_error"] = "CUDA allocator-fraction readback differs from requested policy"
    except Exception as exc:
        result["metadata_missing_reasons"]["memory_fraction_readback"] = f"{type(exc).__name__}: {exc}"
    if result["uuid"] is None:
        result["metadata_missing_reasons"]["uuid"] = "CUDA properties did not expose a UUID"
        result["metadata_missing_reasons"]["driver_version"] = "No UUID; ordinal-based GPU mapping refused"
    else:
        try:
            query = subprocess.run(
                ["nvidia-smi", "-i", result["uuid"], "--query-gpu=uuid,driver_version",
                 "--format=csv,noheader,nounits"],
                check=True, capture_output=True, text=True, timeout=15)
            lines = [line.strip() for line in query.stdout.splitlines() if line.strip()]
            fields = lines[0].split(",") if len(lines) == 1 else []
            if (len(fields) != 2 or fields[0].strip() != result["uuid"]
                    or fields[1].strip().lower() in {"", "n/a", "[n/a]", "not supported", "[not supported]"}):
                raise ValueError("nvidia-smi did not return the requested UUID and driver")
            result["driver_version"] = fields[1].strip()
        except Exception as exc:
            result["metadata_missing_reasons"]["driver_version"] = f"{type(exc).__name__}: {exc}"
    return result


def close_energy_interval(meter, torch, device, *, started):
    """Try to finish CUDA work before the terminal physical-counter reading."""
    synchronized, sync_error = None, None
    if device.type == "cuda":
        try:
            torch.cuda.synchronize(device)
            synchronized = True
        except Exception as exc:
            synchronized, sync_error = False, f"{type(exc).__name__}: {exc}"
    try:
        energy = meter.stop()
    except Exception as exc:
        energy = dict(joules_by_physical_counter=None,
                      missing_reason=f"terminal energy read failed: {type(exc).__name__}: {exc}")
    energy.setdefault("scope", "training wall interval; device/package, not process attribution")
    complete = started and synchronized is not False
    energy.update(terminal_cuda_synchronized=synchronized, terminal_cuda_sync_error=sync_error,
                  interval_complete=complete,
                  interval_completion=("synchronized" if complete and synchronized else
                                       "synchronous_cpu" if complete else "incomplete_or_not_started"))
    return energy


def training_memory_peak(torch, device, *, reset_completed):
    result = dict(peak_gpu_allocated_bytes=None, peak_gpu_reserved_bytes=None,
                  peak_gpu_missing_reason=None,
                  peak_gpu_measurement_status="unavailable",
                  peak_gpu_scope="PyTorch allocator since reset after model/datasets; training and validation interval")
    if device.type != "cuda":
        result["peak_gpu_missing_reason"] = "CPU execution has no GPU allocation"
        result["peak_gpu_measurement_status"] = "not_applicable_cpu"
    elif not reset_completed:
        result["peak_gpu_missing_reason"] = "Training peak reset did not complete; prior allocator peaks are not reused"
    else:
        try:
            allocated, reserved = torch.cuda.max_memory_allocated(device), torch.cuda.max_memory_reserved(device)
            if any(type(value) is not int or value < 0 for value in (allocated, reserved)):
                raise ValueError("invalid allocator peak readback")
            result.update(peak_gpu_allocated_bytes=allocated, peak_gpu_reserved_bytes=reserved,
                          peak_gpu_measurement_status="measured")
        except Exception as exc:
            result["peak_gpu_missing_reason"] = f"Training peak read failed: {type(exc).__name__}: {exc}"
    return result
