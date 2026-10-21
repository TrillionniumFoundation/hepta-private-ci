"""Preflight the unchanged BF16 Qwen CPU reader on the actual runner.

Do not substitute FP32, quantized weights, a different model or a larger time
budget when the host lacks hardware BF16 instructions. This check qualifies
hardware capability, not measured LLM throughput, task success or deployment.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

SCHEMA = "hepta.memory-strong-rag.bf16-host-gate.v1"
ACCELERATED = frozenset(("avx512_bf16", "amx_bf16"))


def assess(cpuinfo, *, machine, runner_arch=None):
    """Require a shared BF16 ISA on every available Linux CPU.

    Model names or AVX2 alone never attest accelerated BF16 GEMM.
    Empty, truncated, contradictory and heterogeneous CPU records fail closed.
    """
    if not isinstance(cpuinfo, str) or not isinstance(machine, str):
        raise ValueError("CPU information and architecture must be strings")
    if not cpuinfo.strip() or len(cpuinfo.encode()) > 256 * 1024:
        raise ValueError("bounded nonempty Linux CPU information required")
    records = re.split(r"\r?\n[ \t]*\r?\n", cpuinfo.strip())
    records = [record for record in records if record.strip()]
    identities = set()
    model_names = set()
    cpus = []
    complete = True
    for record in records:
        fields = {"processor": [], "model name": [], "flags": []}
        for line in record.splitlines():
            if not line.strip():
                continue
            key, separator, value = line.partition(":")
            if not separator:
                complete = False
            if key.strip() in fields:
                fields[key.strip()].append(value.strip())
        if any(len(values) != 1 or not values[0] for values in fields.values()):
            complete = False
            cpus.append(frozenset())
            continue
        identity = fields["processor"][0]
        if not re.fullmatch(r"[0-9]+", identity) or int(identity) in identities:
            complete = False
        else:
            identities.add(int(identity))
        model_names.add(fields["model name"][0])
        cpus.append(frozenset(fields["flags"][0].lower().split()))
    shared = set.intersection(*(set(cpu) for cpu in cpus)) if cpus else set()
    all_accelerated = (
        complete and bool(cpus) and all(set(cpu) & ACCELERATED for cpu in cpus)
    )
    supported = bool(
        machine == "x86_64"
        and (runner_arch is None or runner_arch == "X64")
        and all_accelerated
        and shared & ACCELERATED
    )
    return {
        "schema": SCHEMA,
        "policy": "x86_64-original-qwen-torch2.5.1-cpu-bfloat16-eager",
        "host_eligible": supported,
        "machine": machine,
        "runner_arch": runner_arch,
        "logical_cpu_records": len(cpus),
        "cpu_models": sorted(model_names)[:8],
        "all_cpus_bf16_accelerated": all_accelerated,
        "shared_acceleration_features": sorted(shared & ACCELERATED),
        "cpuinfo_sha256": hashlib.sha256(cpuinfo.encode()).hexdigest(),
        "rejection_reason": (
            None
            if supported
            else "this actual runner does not prove accelerated x86_64 BF16 CPU kernels"
        ),
        "same_original_model_weights_required": True,
        "full_inference_latency_qualified": False,
        "new_model_calls": 0,
        "independent_semantic_judge": False,
        "production_accepted": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if sys.platform != "linux":
        raise ValueError("Linux /proc/cpuinfo required for pinned CPU research reader")
    original = Path("/proc/cpuinfo").read_text(encoding="utf-8")
    result = assess(
        original, machine=platform.machine(), runner_arch=os.getenv("RUNNER_ARCH")
    )
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, sort_keys=True, indent=2, allow_nan=False)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    print(json.dumps(result, sort_keys=True))
    if not result["host_eligible"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
