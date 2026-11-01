"""Q24 plus explicitly charged interval replay at a precision refusal.

The trusted recovery bundle binds the fixture and entire supplied public event
tape. It is not an authenticated owner protocol and offers no anti-rollback.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import struct
import subprocess
import time

from .interval_replay import IntervalMemory, IntervalModel, canonical, signed_payload
from .validate_q24 import SCALE


MAXIMUM_ERROR = SCALE // 100
FIELDS = ("completed", "clock_ticks", "counts", "support", "l1_bound_units")


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name == "posix":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def native_checkpoint(state, model):
    rows, support, bounds = state["counts"], state["support"], state["l1_bound_units"]
    if (len(rows) != model.addresses or len(bounds) != model.addresses
            or len(support) != model.addresses or max(bounds) > MAXIMUM_ERROR):
        raise ValueError("Invalid rebase state dimensions or certificate")
    body = bytearray(b"HQ24CK03" + bytes.fromhex(model.identity))
    body += struct.pack("<IIQQ", model.addresses, model.states, state["completed"], state["clock_ticks"])
    for row, possible, bound in zip(rows, support, bounds):
        if (len(row) != model.states or len(possible) != model.states or sum(row) != SCALE
                or min(row) < 0 or any(count and not bit for count, bit in zip(row, possible))):
            raise ValueError("Invalid Q24 rebase probability")
        body += struct.pack("<I", bound) + struct.pack(f"<{model.states}I", *row)
        for offset in range(0, model.states, 8):
            body.append(sum(int(bit) << index for index, bit in enumerate(possible[offset:offset + 8])))
    body += hashlib.sha256(body).digest()
    return bytes(body)


def run(model_path, operations_path, native, output, stop_after=None, restore=None):
    started = time.process_time()
    # A new namespace also prevents partial/failed attempts from being replaced.
    output.mkdir(parents=True, exist_ok=False)
    source, tape = model_path.read_bytes(), operations_path.read_bytes()
    model = IntervalModel(source)
    tape_hash = hashlib.sha256(tape).hexdigest()
    operations = tape.decode().splitlines()
    if any(not operation.strip() for operation in operations):
        raise ValueError("Empty operation line is outside the hybrid profile")
    stop = len(operations) if stop_after is None else stop_after
    if not 0 <= stop <= len(operations):
        raise ValueError("Invalid tape stop")
    cache = IntervalMemory(model)
    state, current_checkpoint = None, None
    prior = dict(native_calls=0, fallbacks=0, python_cpu_seconds=0., native_cpu_seconds=0., replayed_events=0)
    if restore is not None:
        body = json.loads(restore.read_text())
        checksum = body.pop("sha256", None)
        if checksum != hashlib.sha256(canonical(body).encode()).hexdigest():
            raise ValueError("Hybrid recovery checksum mismatch")
        if (body["schema"] != "hcsn-r16-hybrid-checkpoint-v1" or body["model"] != model.identity
                or body["tape"] != tape_hash or body["maximum_error"] != MAXIMUM_ERROR):
            raise ValueError("Hybrid model/tape/profile mismatch")
        cache = IntervalMemory.restore(model, body["interval_cache"])
        state = body["native_state"]
        if state["completed"] != cache.completed or state["clock_ticks"] != cache.clock_ticks:
            raise ValueError("Hybrid replay cursor mismatch")
        current_checkpoint = native_checkpoint(state, model)
        if current_checkpoint.hex() != body["native_checkpoint_hex"]:
            raise ValueError("Hybrid native checkpoint mismatch")
        prior = body["cumulative_cost"]
    position = cache.completed
    if position > stop:
        raise ValueError("Recovery cursor beyond requested tape")
    start = position
    receipts, fallbacks, trace, enclosures = [], [], [], []
    replay_cpu, replayed_events, native_cpu = 0., 0, 0.

    def audit(frame):
        if cache.completed != frame["completed"] or cache.clock_ticks != frame["clock_ticks"]:
            raise AssertionError("Interval and native event indices diverged")
        if cache.support != frame["support"]:
            raise AssertionError("Interval and native structural support diverged")
        radius = cache.radii(frame["counts"])
        if max(radius) > MAXIMUM_ERROR or max(frame["l1_bound_units"]) > MAXIMUM_ERROR:
            raise ArithmeticError("Fixed 1% precision contract violated")
        enclosures.append(dict(completed=cache.completed, interval_radius_units=radius,
                               native_radius_units=frame["l1_bound_units"]))

    while position < stop:
        index = len(receipts)
        prefix = output / "native_calls" / f"{index:04d}"
        events_file = prefix.with_suffix(".ops")
        checkpoint_file = prefix.with_suffix(".ckpt")
        atomic_bytes(events_file, ("\n".join(operations[position:stop]) + "\n").encode())
        command = [str(native), str(model_path), str(events_file), str(checkpoint_file), str(MAXIMUM_ERROR)]
        if current_checkpoint is not None:
            restore_file = prefix.with_suffix(".restore.ckpt")
            atomic_bytes(restore_file, current_checkpoint)
            command.append(str(restore_file))
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        wall = time.perf_counter()
        process = subprocess.run(command, capture_output=True, text=True)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        native_cpu += cpu
        atomic_bytes(prefix.with_suffix(".stdout.jsonl"), process.stdout.encode())
        atomic_bytes(prefix.with_suffix(".stderr.txt"), process.stderr.encode())
        receipts.append(dict(call=index, start=position, returncode=process.returncode,
                             cpu_seconds=cpu, wall_seconds=time.perf_counter() - wall,
                             stdout_sha256=hashlib.sha256(process.stdout.encode()).hexdigest(),
                             stderr=process.stderr.strip()))
        records = [json.loads(line) for line in process.stdout.splitlines()]
        frames = [record for record in records if record["event"] != "checkpoint"]
        if not frames or frames[0]["completed"] != position:
            raise RuntimeError("Native process failed before the expected cursor: " + process.stderr)
        if state is not None and any(frames[0][field] != state[field] for field in FIELDS):
            raise AssertionError("Native reentry changed state")
        if not trace:
            trace.append(dict(frames[0], execution="initial"))
            audit(trace[0])
        for frame in frames[1:]:
            if frame["completed"] != trace[-1]["completed"] + 1:
                raise AssertionError("Dropped or repeated native event")
            trace.append(dict(frame, execution="native"))
        state = trace[-1]
        position = state["completed"]
        if process.returncode == 0:
            if position != stop:
                raise AssertionError("Native success before requested terminal index")
            current_checkpoint = checkpoint_file.read_bytes()
            break
        if process.returncode != 2 or "precision required:" not in process.stderr:
            raise RuntimeError("Unapproved native failure: " + process.stderr)
        if position >= stop or not process.stderr.startswith(f"operation line {len(frames)}:"):
            raise AssertionError("Precision refusal does not identify the next event")
        replay_start, clock = cache.completed, time.process_time()
        while cache.completed < position:
            cache.apply(operations[cache.completed])
            audit(trace[cache.completed - start])
        # The refused operation is executed exactly once by interval replay.
        cache.apply(operations[position])
        state = dict(cache.quantized(MAXIMUM_ERROR), event=operations[position].split()[0],
                     execution="interval_fallback")
        trace.append(state)
        audit(state)
        replayed_events += cache.completed - replay_start
        replay_cpu += time.process_time() - clock
        position = cache.completed
        current_checkpoint = native_checkpoint(state, model)
        cache_payload = canonical(cache.export()).encode()
        atomic_bytes(prefix.with_suffix(".interval_cache.json"), cache_payload)
        fallbacks.append(dict(refused_event=position, replay_from=replay_start, replay_to=position,
                              replayed_events=position - replay_start,
                              cache_bytes=len(cache_payload), q24_checkpoint_bytes=len(current_checkpoint),
                              q24_radius_units=state["l1_bound_units"],
                              interval_cache_sha256=hashlib.sha256(cache_payload).hexdigest()))
    if state is None:
        raise ValueError("At least one event is required for an initial run")
    if not trace:
        trace = [dict(state, execution="initial")]
        audit(trace[0])
    # Account for the residual public buffer and certify every visited state.
    replay_start, clock = cache.completed, time.process_time()
    while cache.completed < position:
        cache.apply(operations[cache.completed])
        audit(trace[cache.completed - start])
    replayed_events += cache.completed - replay_start
    replay_cpu += time.process_time() - clock
    if len(trace) != stop - start + 1 or len(enclosures) != len(trace):
        raise AssertionError("Incomplete per-event interval audit")
    if current_checkpoint != native_checkpoint(state, model):
        raise AssertionError("Terminal native checkpoint mismatch")
    cumulative = dict(native_calls=prior["native_calls"] + len(receipts),
        fallbacks=prior["fallbacks"] + len(fallbacks),
        python_cpu_seconds=prior["python_cpu_seconds"] + time.process_time() - started,
        native_cpu_seconds=prior["native_cpu_seconds"] + native_cpu,
        replayed_events=prior["replayed_events"] + replayed_events)
    bundle = signed_payload(dict(schema="hcsn-r16-hybrid-checkpoint-v1", model=model.identity,
        tape=tape_hash, maximum_error=MAXIMUM_ERROR, native_state={field: state[field] for field in FIELDS},
        native_checkpoint_hex=current_checkpoint.hex(), interval_cache=cache.export(), cumulative_cost=cumulative))
    atomic_bytes(output / "HYBRID_CHECKPOINT.json", canonical(bundle).encode())
    atomic_bytes(output / "TRACE.jsonl", "".join(canonical(frame) + "\n" for frame in trace).encode())
    atomic_bytes(output / "ENCLOSURES.jsonl", "".join(canonical(row) + "\n" for row in enclosures).encode())
    result = dict(schema="hcsn-r16-hybrid-run-v1", start=start, completed=position,
        requested_stop=stop, events_committed=stop - start, native_calls=receipts, fallbacks=fallbacks,
        replayed_events=replayed_events, replay_cpu_seconds=replay_cpu,
        native_cpu_seconds=native_cpu, python_cpu_seconds=time.process_time() - started,
        maximum_interval_radius_units=max(max(row["interval_radius_units"]) for row in enclosures),
        maximum_native_radius_units=max(max(row["native_radius_units"]) for row in enclosures),
        maximum_error_units=MAXIMUM_ERROR, model=model.identity, tape=tape_hash,
        final_checkpoint_bytes=len(canonical(bundle).encode()),
        retained_full_tape_bytes=len(tape), fixture_bytes=len(source),
        maximum_replay_buffer_events=max((row["replayed_events"] for row in fallbacks), default=0),
        cumulative_checkpoint_cost_is_a_lower_bound=True,
        final_native_checkpoint_sha256=hashlib.sha256(current_checkpoint).hexdigest(),
        source_scope="Exact integer-weight fixture; trusted cache only; no expm/PDE or owner authorization claim")
    result["recorded_artifact_bytes_before_run_receipt"] = sum(
        path.stat().st_size for path in output.rglob("*") if path.is_file())
    atomic_bytes(output / "RUN.json", (json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "ops", "native", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--stop-after", type=int)
    args = parser.parse_args()
    result = run(args.model, args.ops, args.native, args.output, args.stop_after, args.restore)
    print(canonical({key: result[key] for key in ("completed", "events_committed", "maximum_interval_radius_units",
                                                "maximum_native_radius_units", "replay_cpu_seconds")}))
