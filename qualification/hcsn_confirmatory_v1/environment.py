"""Bind CPU/backend identity; no task data or model is constructed here."""
import hashlib
import os
from pathlib import Path
import platform

_POOL_LIMITER = None


def execution_identity():
    global _POOL_LIMITER
    import torch
    if torch.get_num_threads() != 1:
        torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    cpu = Path("/proc/cpuinfo")
    fields = ("vendor_id", "cpu family", "model", "model name", "stepping", "microcode",
              "flags", "Features", "CPU architecture")
    capabilities = []
    if cpu.exists():
        for line in cpu.read_text().split("\n\n")[0].splitlines():
            if line.partition(":")[0].strip() in fields:
                capabilities.append(line.strip())
    try:
        from threadpoolctl import threadpool_info, threadpool_limits
        if _POOL_LIMITER is None:
            _POOL_LIMITER = threadpool_limits(limits=1)
        pools = threadpool_info()
    except ImportError:
        pools = {"status": "UNAVAILABLE", "reason": "threadpoolctl not installed"}
    config, parallel = torch.__config__.show(), torch.__config__.parallel_info()
    return {"platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "cpu_capabilities": capabilities,
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "torch_build": config, "torch_parallel": parallel,
            "torch_build_sha256": hashlib.sha256(config.encode()).hexdigest(),
            "threads": torch.get_num_threads(), "interop_threads": torch.get_num_interop_threads(),
            "deterministic": torch.are_deterministic_algorithms_enabled(), "threadpools": pools}

