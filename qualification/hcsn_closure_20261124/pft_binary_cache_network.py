"""POSIX research adapter: original fixed train shards over explicit binary TCP."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from . import pft_cache_network as legacy
from . import pft_online_peer as wire
from .pft_binary_peer import BinaryMessages
from .pft_statistics import digest


PROTOCOL_COMMIT = "93a854807b5883b9bac987498977f81277d9081a"
BASE_COMMIT = "db152bb76d77ecdc6cc6d10747574471ef183b8e"
ORIGINAL_WORKER = legacy.worker


class FrameMeter(legacy.Meter):
    """Meter actual socket operations at the shared encoded-frame boundary."""

    def install(self):
        original_send, original_receive = wire._send_frame, wire._receive_frame
        meter = self

        class Socket:
            def __init__(self, stream):
                self.stream = stream

            def __getattr__(self, name):
                return getattr(self.stream, name)

            def sendall(self, data):
                meter.add(sendall_calls=1)
                try:
                    self.stream.sendall(data)
                except Exception:
                    meter.add(
                        failed_sendall_calls=1, failed_sendall_attempted_bytes=len(data)
                    )
                    raise
                meter.add(completed_sent_bytes=len(data))

            def recv(self, length):
                data = self.stream.recv(length)
                meter.add(received_bytes=len(data), recv_calls=1)
                return data

        def send(stream, raw):
            original_send(Socket(stream), raw)
            if raw[:5] == b"HPM1\x01":
                meter.add(sent_offer_frames=1)

        def receive(stream):
            raw = original_receive(Socket(stream))
            if raw[:5] == b"HPM1\x01":
                meter.add(received_offer_frames=1)
            return raw

        wire._send_frame, wire._receive_frame = send, receive


def binary_worker(*args):
    service_class = wire.PeerService

    def service(path, contract):
        return service_class(path, contract, codec=BinaryMessages(contract))

    legacy.Meter = FrameMeter
    wire.PeerService = service
    ORIGINAL_WORKER(*args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("fixture-root", "output", "budget"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--correction-note", default="")
    args = parser.parse_args()
    started = time.monotonic()
    here = Path(__file__).parent
    if any(
        os.environ.get(k) != "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
    ):
        raise ValueError("registered execution requires one BLAS thread")
    inputs = here / "pft_cache_network/INPUTS.json"
    if legacy.sha(inputs) != legacy.INPUTS_SHA256:
        raise ValueError("input inventory is not the registered artifact")
    document = json.loads(inputs.read_text())
    if [row["parent"] for row in document["parents"]] != legacy.PARENTS:
        raise ValueError("registered parent order differs")
    dependencies = here / "pft_binary_cache_network/DEPENDENCIES.json"
    dependency_document = json.loads(dependencies.read_text())
    if dependency_document["base_commit"] != BASE_COMMIT:
        raise ValueError("dependency base differs")
    source = {}
    for item in dependency_document["dependencies"]:
        path = here.parents[1] / item["path"]
        actual = legacy.sha(path)
        if actual != item["sha256"]:
            raise ValueError("published dependency bytes differ")
        source[item["path"]] = actual
    source["qualification/hcsn_closure_20261124/pft_binary_cache_network.py"] = (
        legacy.sha(__file__)
    )
    source["dependency_manifest"] = legacy.sha(dependencies)
    identity = digest(source)
    protocol_sha = legacy.sha(here / "pft_binary_cache_network/PROTOCOL.md")
    args.output.mkdir(parents=True, exist_ok=False)
    args.budget.parent.mkdir(parents=True, exist_ok=True)
    with args.budget.with_suffix(".lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = (
            json.loads(args.budget.read_text())
            if args.budget.exists()
            else dict(
                schema="pft-binary-cache-network-budget-v1",
                protocol_sha256=protocol_sha,
                attempts=[],
            )
        )
        if budget["protocol_sha256"] != protocol_sha:
            raise ValueError("cannot reset the registered budget with another protocol")
        prior = budget["attempts"]
        if prior and (
            not args.correction_note.strip()
            or any(a["source_identity"] == identity for a in prior)
        ):
            raise ValueError(
                "another attempt requires a source correction and a new identity"
            )
        charged = lambda case: case.get("elapsed_seconds", case["reserved_seconds"])
        total_prior = sum(
            a.get("elapsed_seconds", sum(charged(c) for c in a["cases"])) for a in prior
        )
        parent_spent = {
            p: sum(charged(c) for a in prior for c in a["cases"] if c["parent"] == p)
            for p in legacy.PARENTS
        }
        attempt = dict(
            source_identity=identity,
            source=source,
            correction_note=args.correction_note,
            output=str(args.output.resolve()),
            started_unix=time.time(),
            cases=[],
        )
        prior.append(attempt)

        def save_budget():
            temporary = args.budget.with_suffix(".pending")
            temporary.write_text(
                json.dumps(budget, sort_keys=True, indent=2, allow_nan=False) + "\n"
            )
            os.replace(temporary, args.budget)

        save_budget()
        legacy.write(
            args.output / "SOURCE_FROZEN.json",
            dict(
                protocol_commit=PROTOCOL_COMMIT,
                base_commit=BASE_COMMIT,
                source=source,
                inputs_sha256=legacy.INPUTS_SHA256,
                pid=os.getpid(),
                numeric_rtol=1e-7,
                numeric_atol=1e-7,
                python=platform.python_version(),
                numpy=np.__version__,
                platform=platform.platform(),
                threads={
                    k: os.environ.get(k)
                    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
                },
            ),
        )
        legacy.worker = binary_worker
        rows = []
        for item in document["parents"]:
            allowance = min(
                60 - parent_spent[item["parent"]],
                600 - total_prior - (time.monotonic() - started),
            )
            case = dict(
                parent=item["parent"],
                reserved_seconds=max(0, allowance),
                started_unix=time.time(),
            )
            attempt["cases"].append(case)
            save_budget()
            case_started = time.monotonic()
            result = legacy.run_case(
                item, args.fixture_root, args.output / item["parent"], allowance
            )
            result["charged_seconds"] = time.monotonic() - case_started
            result["passed"] = (
                result["passed"] and result["charged_seconds"] <= allowance
            )
            rows.append(result)
            case.update(
                elapsed_seconds=result["charged_seconds"], passed=result["passed"]
            )
            save_budget()
            print(
                json.dumps(
                    dict(
                        parent=item["parent"],
                        passed=result["passed"],
                        elapsed_seconds=result["elapsed_seconds"],
                    )
                ),
                flush=True,
            )
            if not result["passed"]:
                break
        attempt["elapsed_seconds"] = time.monotonic() - started
        save_budget()
        legacy.write(args.output / "BUDGET.json", budget)
        summary = dict(
            schema="pft-binary-cache-network-result-v1",
            rows=rows,
            passed=sum(r["passed"] for r in rows),
            expected=9,
            not_run=legacy.PARENTS[len(rows) :],
            total_seconds=attempt["elapsed_seconds"],
            cumulative_seconds=total_prior + attempt["elapsed_seconds"],
            scientific_gain=False,
            training_speedup_established=False,
            production_settlement=False,
            real_user_adoption=False,
        )
        legacy.write(args.output / "RESULTS.json", summary)
        raise SystemExit(
            0 if summary["passed"] == 9 and summary["cumulative_seconds"] <= 600 else 1
        )


if __name__ == "__main__":
    main()
