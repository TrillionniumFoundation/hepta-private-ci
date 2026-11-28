"""Fixed historical training shards over four independent persistent TCP peers."""

import argparse
import fcntl
import hashlib
import json
import multiprocessing
from multiprocessing.connection import wait
import os
from pathlib import Path
import platform
import threading
import time
import traceback

import numpy as np

from . import pft_online_peer as wire
from .pft_statistics import StatisticsLedger, digest, make_packet


PROTOCOL_COMMIT = "92dc4c51de3d74f545da99165e2a0284286b6668"
BASE_COMMIT = "84f843c6dceb32216e7d83d2ac3063d0d7e9afc4"
INPUTS_SHA256 = "ba2becd642d8a09bd71381e65146b0e25b4ceb2f118b89fafda56faeb09a2d75"
PARENTS = [f"n{n}-s{s}" for n in (8, 32, 64) for s in (17011, 27011, 37011)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


class Meter:
    """Observe unchanged socket operations; failed-send partial bytes are unknown."""

    def __init__(self):
        self.lock = threading.Lock()
        self.values = dict(
            completed_sent_bytes=0,
            received_bytes=0,
            sendall_calls=0,
            failed_sendall_calls=0,
            failed_sendall_attempted_bytes=0,
            recv_calls=0,
            sent_offer_frames=0,
            received_offer_frames=0,
        )

    def add(self, **values):
        with self.lock:
            for key, value in values.items():
                self.values[key] += value

    def snapshot(self):
        with self.lock:
            return dict(self.values)

    def install(self):
        original_send, original_receive = wire._send, wire._receive
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

        def send(stream, value):
            original_send(Socket(stream), value)
            if type(value) is dict and value.get("operation") == "offer":
                meter.add(sent_offer_frames=1)

        def receive(stream):
            value = original_receive(Socket(stream))
            if type(value) is dict and value.get("operation") == "offer":
                meter.add(received_offer_frames=1)
            return value

        wire._send, wire._receive = send, receive


def worker(index, shard, expected_sha, contract, train_sha, output, deadline, control):
    output = Path(output)
    meter, service, error = Meter(), None, None
    meter.install()
    counters = dict(
        rounds=0, completed_rounds=0, reported_offers=0, unknown_delivery=0, refused=0
    )
    started = time.perf_counter()
    try:
        if sha(shard) != expected_sha:
            raise ValueError("child shard bytes differ")
        with np.load(shard, allow_pickle=False) as z:
            x, y = z["x"].astype(np.float64), z["y"].astype(np.float64)
        packet = make_packet(
            contract,
            f"shard-{index}",
            expected_sha,
            [digest([train_sha, index, j]) for j in range(len(x))],
            x,
            y,
        )
        ledger = StatisticsLedger(output / f"peer-{index}.db", contract)
        initial = ledger.append(packet, ledger.state()["head"])
        service = wire.PeerService(ledger.path, contract)
        ready = dict(
            kind="ready",
            index=index,
            pid=os.getpid(),
            address=service.start(),
            shard_sha256=expected_sha,
            packet_sha256=packet["payload_sha256"],
            initial=initial,
        )
        write(output / f"peer-{index}-ready.json", ready)
        control.send(ready)
        neighbor, reported = None, False
        with (output / f"peer-{index}-rounds.jsonl").open("x", buffering=1) as log:
            while time.monotonic() < deadline:
                if control.poll(0.01):
                    message = control.recv()
                    if message == "stop":
                        break
                    neighbor = message
                if neighbor is None:
                    continue
                counters["rounds"] += 1
                event = dict(
                    round=counters["rounds"],
                    started_seconds=time.perf_counter() - started,
                )
                try:
                    count = service.sync(neighbor)
                    counters["completed_rounds"] += 1
                    counters["reported_offers"] += count
                    event.update(status="completed", reported_offers=count)
                except wire.DeliveryUnknown as exc:
                    counters["unknown_delivery"] += 1
                    event.update(
                        status="unknown", error=repr(exc), cause=repr(exc.__cause__)
                    )
                except ValueError as exc:
                    counters["refused"] += 1
                    event.update(status="refused", error=repr(exc))
                event.update(
                    finished_seconds=time.perf_counter() - started,
                    bytes=meter.snapshot(),
                )
                log.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
                if not reported and ledger.state()["revision"] == 4:
                    candidate = ledger.snapshot()["candidate"]
                    write(output / f"peer-{index}-candidate.json", candidate)
                    control.send(
                        dict(kind="candidate", index=index, candidate=candidate)
                    )
                    reported = True
    except Exception:
        error = traceback.format_exc()
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                error = (error or "") + traceback.format_exc()
        final = dict(
            kind="done",
            index=index,
            pid=os.getpid(),
            counters=counters,
            bytes=meter.snapshot(),
            elapsed_seconds=time.perf_counter() - started,
            error=error,
        )
        write(output / f"peer-{index}-final.json", final)
        try:
            control.send(final)
        except (EOFError, OSError):
            pass
        control.close()
    raise SystemExit(1 if error else 0)


def run_case(item, fixture, output, allowance):
    started = time.monotonic()
    deadline = started + allowance
    handles, events, candidates, errors = [], [], {}, []
    output.mkdir()
    result = dict(parent=item["parent"], passed=False, allowance_seconds=allowance)
    try:
        if allowance <= 8:
            raise TimeoutError("insufficient remaining allowance for cleanup")
        paths = []
        for entry in item["files"]:
            path = (fixture / entry["path"]).resolve()
            if (
                not path.is_relative_to(fixture.resolve())
                or path.stat().st_size != entry["size"]
                or sha(path) != entry["sha256"]
            ):
                raise ValueError("frozen input identity differs")
            paths.append(path)
        manifest, expected = (
            json.loads(paths[0].read_text()),
            json.loads(paths[2].read_text()),
        )
        contract = expected["contract"]
        context = multiprocessing.get_context("spawn")
        for i in range(4):
            owner, child = context.Pipe()
            process = context.Process(
                target=worker,
                args=(
                    i,
                    str(paths[i + 3]),
                    item["files"][i + 3]["sha256"],
                    contract,
                    manifest["objective_binding"]["train_sha256"],
                    str(output),
                    deadline - 8,
                    child,
                ),
            )
            process.start()
            child.close()
            handles.append((process, owner))
        ready = {}
        while len(ready) < 4:
            active = wait(
                [v[1] for v in handles],
                timeout=max(0, min(0.2, deadline - 8 - time.monotonic())),
            )
            for pipe in active:
                event = pipe.recv()
                events.append(event)
                if event["kind"] != "ready":
                    raise RuntimeError("peer failed before startup completed")
                ready[event["index"]] = event
            if time.monotonic() >= deadline - 8:
                raise TimeoutError("peer startup deadline expired")
        if len({v["pid"] for v in ready.values()}) != 4:
            raise ValueError("child process identities are not distinct")
        for i, (_, pipe) in enumerate(handles):
            pipe.send(ready[(i + 1) % 4]["address"])
        while len(candidates) < 4:
            for pipe in wait(
                [v[1] for v in handles],
                timeout=max(0, min(0.2, deadline - 8 - time.monotonic())),
            ):
                event = pipe.recv()
                events.append(event)
                if event["kind"] != "candidate":
                    raise RuntimeError("peer stopped before all candidates converged")
                candidates[event["index"]] = event["candidate"]
            if time.monotonic() >= deadline - 8:
                raise TimeoutError("candidate convergence deadline expired")
        with np.load(paths[1], allow_pickle=False) as z:
            historical = z["full"].copy()
        for candidate in candidates.values():
            if (
                candidate != expected
                or candidate["revision"] != 4
                or candidate["count"] != 192
            ):
                raise ValueError("candidate differs from the sealed prior result")
            np.testing.assert_allclose(
                candidate["weight"], historical, rtol=1e-7, atol=1e-7
            )
        result.update(
            head=expected["head"],
            weight_sha256=expected["weight_sha256"],
            max_historical_error=max(
                float(np.max(np.abs(np.asarray(c["weight"]) - historical)))
                for c in candidates.values()
            ),
        )
    except Exception:
        errors.append(traceback.format_exc())
    finally:
        for process, pipe in handles:
            if process.is_alive():
                try:
                    pipe.send("stop")
                except (OSError, EOFError):
                    pass
        children = []
        for i, (process, pipe) in enumerate(handles):
            process.join(max(0, deadline - time.monotonic() - 0.2))
            forced = process.is_alive()
            if forced:
                process.terminate()
                process.join(0.1)
                if process.is_alive():
                    process.kill()
                    process.join(0.1)
            while pipe.poll():
                try:
                    events.append(pipe.recv())
                except (EOFError, OSError):
                    break
            pipe.close()
            final = output / f"peer-{i}-final.json"
            children.append(
                dict(
                    pid=process.pid,
                    exit_code=process.exitcode,
                    forced=forced,
                    observation=json.loads(final.read_text())
                    if final.exists()
                    else None,
                )
            )
        result.update(
            children=children,
            errors=errors,
            events=events,
            elapsed_seconds=time.monotonic() - started,
            optimizer_steps=0,
            final_test_reads=0,
        )
        result["passed"] = (
            not errors
            and len(candidates) == 4
            and all(c["exit_code"] == 0 and not c["forced"] for c in children)
            and result["elapsed_seconds"] <= allowance
        )
        write(output / "RESULT.json", result)
    return result


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
    if sha(inputs) != INPUTS_SHA256:
        raise ValueError("input inventory is not the registered artifact")
    source = {
        name: sha(here / name)
        for name in (
            "pft_cache_network.py",
            "pft_online_peer.py",
            "pft_statistics.py",
            "pft_linear.py",
        )
    }
    identity = digest(source)
    protocol_sha = sha(here / "pft_cache_network/PROTOCOL.md")
    args.output.mkdir(parents=True, exist_ok=False)
    args.budget.parent.mkdir(parents=True, exist_ok=True)
    with args.budget.with_suffix(".lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        budget = (
            json.loads(args.budget.read_text())
            if args.budget.exists()
            else dict(
                schema="pft-cache-network-budget-v1",
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
            for p in PARENTS
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
        write(
            args.output / "SOURCE_FROZEN.json",
            dict(
                protocol_commit=PROTOCOL_COMMIT,
                base_commit=BASE_COMMIT,
                source=source,
                inputs_sha256=INPUTS_SHA256,
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
        rows = []
        document = json.loads(inputs.read_text())
        if [row["parent"] for row in document["parents"]] != PARENTS:
            raise ValueError("registered parent order differs")
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
            result = run_case(
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
        write(args.output / "BUDGET.json", budget)
        summary = dict(
            schema="pft-cache-network-result-v1",
            rows=rows,
            passed=sum(r["passed"] for r in rows),
            expected=9,
            not_run=PARENTS[len(rows) :],
            total_seconds=attempt["elapsed_seconds"],
            cumulative_seconds=total_prior + attempt["elapsed_seconds"],
            scientific_gain=False,
            production_settlement=False,
            real_user_adoption=False,
        )
        write(args.output / "RESULTS.json", summary)
        raise SystemExit(
            0 if summary["passed"] == 9 and summary["cumulative_seconds"] <= 600 else 1
        )


if __name__ == "__main__":
    main()
