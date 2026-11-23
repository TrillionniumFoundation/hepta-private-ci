"""Replay the shipped synthetic two-phase fixture in a fresh Linux network namespace."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from cell_experiments import coding_sft, data, paired_freeze


def network_readout():
    devices = Path("/proc/net/dev").read_text().splitlines()[2:]
    return {
        "network_namespace": os.readlink("/proc/self/ns/net"),
        "interfaces": [line.split(":", 1)[0].strip() for line in devices],
        "interface_counters": devices,
        "ipv4_routes": Path("/proc/net/route").read_text().splitlines(),
    }


def run(output, outer_namespace, fixture):
    before = network_readout()
    if before["network_namespace"] == outer_namespace or before["interfaces"] != ["lo"]:
        raise RuntimeError("expected a new network namespace with only loopback")
    reference = json.loads((fixture / "request.json").read_bytes())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with TemporaryDirectory(dir=output) as temporary:
        work = Path(temporary)
        spec = {
            key: reference[key]
            for key in ("parent", "candidate", "retention", "timeout_seconds")
        }
        coding_sft.write_new(work / "spec.json", spec)
        frozen = paired_freeze.freeze(
            work / "spec.json", fixture, output / "FROZEN.json"
        )
        coding_sft.write_new(work / "future.json", reference["future"])
        request = output / "request.json"
        bound = paired_freeze.assemble(
            output / "FROZEN.json", frozen, work / "future.json", request
        )
        if request.read_bytes() != (fixture / "request.json").read_bytes():
            raise ValueError("assembled request differs from the published fixture")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "cell_experiments.paired_cold",
                str(request),
                bound,
                str(fixture),
                str(output / "evaluation"),
            ],
            check=True,
        )
    result = json.loads((output / "evaluation" / "RESULT.json").read_bytes())
    original = json.loads((fixture / "evaluation" / "RESULT.json").read_bytes())
    if result["counts"] != original["counts"]:
        raise ValueError("paired results differ from the original fixture")
    after = network_readout()
    if after != before:
        raise ValueError(
            "network namespace, routes, interfaces or traffic counters changed"
        )
    coding_sft.write_new(
        output / "READBACK.json",
        {
            "scope": "Retrospective reproduction of an authored fixture",
            "outer_network_namespace": outer_namespace,
            "network_before": before,
            "network_after": after,
            "freeze_sha256": frozen,
            "request_sha256": bound,
            "result_sha256": data.digest(result),
            "published_fixture_request_byte_equal": True,
            "real_users": 0,
            "authenticated_future_arrivals": 0,
            "settlements": 0,
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parent / "fixture",
        help="Directory with frozen engineering materials, request and original paired result",
    )
    parser.add_argument("--inside", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside:
        run(args.output, args.inside, args.fixture)
        return
    env = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    subprocess.run(
        [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            "--",
            sys.executable,
            __file__,
            str(args.output.resolve()),
            "--fixture",
            str(args.fixture.resolve()),
            "--inside",
            os.readlink("/proc/self/ns/net"),
        ],
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
