#!/usr/bin/env python3
"""Qualify the existing Joint proposal ABI with a pinned trained descendant.

This is a kernel/transport experiment. It neither adopts a model nor substitutes
for the Agentd/durable-control lifecycle qualification. Outputs are unpublished.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import struct
import subprocess
import time


MODALITIES = ("image", "audio", "video", "text")
TOTAL_UNITS = (16, 1024, 4, 2)
SOURCE_FILES = ["src/bin/hepta-joint-propose.rs"] + [
    "src/joint_generation/" + name + ".rs"
    for name in ("bridge_state", "codec", "decoder", "math", "model", "proposal", "protocol", "state")
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pinned(path, expected):
    data = path.read_bytes()
    require(len(data) == expected["bytes"] and sha(data) == expected["sha256"],
            "Asset identity mismatch: " + str(path))
    return data


class Reader:
    def __init__(self, data):
        self.data, self.position = data, 0

    def take(self, size):
        require(0 <= size <= len(self.data) - self.position, "Truncated response")
        value = self.data[self.position:self.position + size]
        self.position += size
        return value

    def uint(self, size=4):
        return int.from_bytes(self.take(size), "little")

    def blob(self, maximum):
        size = self.uint()
        require(size <= maximum, "Response blob exceeds bound")
        return self.take(size)

    def finished(self):
        require(self.position == len(self.data), "Trailing response bytes")


def response(data, request_digest):
    require(len(data) >= 145, "Short response")
    require(data[-64:] == sha(data[:-64]).encode(), "Response checksum mismatch")
    reader = Reader(data[:-64])
    require(reader.take(8) == b"HJRESV01", "Unexpected response ABI")
    require(reader.take(32) == request_digest, "Different original request digest")
    stopped = reader.uint(1)
    require(stopped in (0, 1), "Invalid stopped tag")
    phases = [reader.uint(8) for _ in range(4)]
    state, delta = reader.blob(65536), reader.blob(65536)
    reader.finished()
    return state, delta, bool(stopped), phases


def prefixes(data):
    reader, cursors, outputs = Reader(data), [0] * 4, [bytearray() for _ in range(4)]
    while reader.position < len(data):
        require(reader.take(4) == b"HGC1", "Unexpected prefix frame")
        modality, start, units = reader.uint(1), reader.uint(), reader.uint()
        payload = reader.blob(65536)
        require(modality < 4 and start == cursors[modality] and units > 0,
                "Noncontiguous prefix")
        require(start + units <= TOTAL_UNITS[modality], "Prefix range overflow")
        if modality != 3:
            require(len(payload) == units * (48, 2, 768)[modality], "Prefix payload size")
        else:
            payload.decode("utf-8", errors="strict")
        outputs[modality].extend(payload)
        cursors[modality] += units
    return cursors, [bytes(item) for item in outputs]


def command(name, *args):
    if name == "init":
        return b"\x00" + struct.pack("<QB", *args)
    if name == "advance":
        return b"\x01" + bytes(args)
    if name == "auto":
        return b"\x02" + struct.pack("<I", *args)
    if name == "commit":
        return b"\x03" + struct.pack("<BI", *args)
    raise ValueError("Unknown command")


class Experiment:
    def __init__(self, args, manifest):
        self.args, self.manifest = args, manifest
        self.weights = pinned(args.weights, manifest["weights"])
        self.public = pinned(args.public, manifest["public"])
        pinned(args.checkpoint, manifest["checkpoint"])
        self.binary_hash = sha(args.executable.read_bytes())
        self.steps, self.checks = [], []

    def request(self, state, prefix, action, weights=None, public=None):
        blobs = (self.weights if weights is None else weights,
                 self.public if public is None else public, state, prefix)
        require(all(len(item) <= limit for item, limit in zip(
            blobs, (8388608, 1048576, 65536, 262144))), "Request exceeds ABI bounds")
        payload = b"".join(struct.pack("<I", len(item)) + item for item in blobs) + action
        digest = hashlib.sha256(b"qualification-joint-replay-v1\0" + payload).digest()
        return b"HJREQV01" + digest + payload, digest

    def call(self, label, state, prefix, action, reject=None, weights=None, public=None):
        request, digest = self.request(state, prefix, action, weights, public)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
        child = subprocess.Popen([str(self.args.executable)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        timed_out = False
        try:
            stdout, stderr = child.communicate(request, timeout=30)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            stdout, stderr = child.communicate()
        elapsed = time.perf_counter_ns() - started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {"index": len(self.steps), "label": label, "exit_code": child.returncode,
                  "timed_out": timed_out, "request_sha256": sha(request),
                  "request_digest": digest.hex(), "command_hex": action.hex(),
                  "predecessor_state_sha256": sha(state), "predecessor_prefix_sha256": sha(prefix),
                  "wall_ns": elapsed, "harness_cpu_ns": time.process_time_ns() - parent_cpu,
                  "child_cpu_seconds": (after.ru_utime + after.ru_stime) -
                                       (before.ru_utime + before.ru_stime),
                  "ipc_bytes": len(request) + len(stdout) + len(stderr),
                  "response_sha256": sha(stdout), "stderr_sha256": sha(stderr)}
        self.steps.append(record)
        stem = self.args.output / f"{record['index']:03}-{label}"
        stem.with_suffix(".response").write_bytes(stdout)
        stem.with_suffix(".stderr").write_bytes(stderr)
        write_json(self.args.output / "steps.json", self.steps)
        require(not timed_out, "Proposal exceeded 30-second qualification deadline")
        if reject is not None:
            require(child.returncode == 2 and not stdout and reject.encode() in stderr,
                    "Expected rejection not observed: " + label)
            return None
        require(child.returncode == 0 and not stderr, "Proposal failed: " + label)
        successor, delta, stopped, phases = response(stdout, digest)
        require(sum(phases) * 1000 <= elapsed, "Child intervals exceed enclosing wall")
        record.update({"state_sha256": sha(successor), "delta_sha256": sha(delta),
                       "stopped": stopped, "child_disjoint_wall_micros": phases,
                       "parent_and_unallocated_wall_ns": elapsed - sum(phases) * 1000})
        stem.with_suffix(".state").write_bytes(successor)
        stem.with_suffix(".prefix").write_bytes(prefix + delta)
        # All continuations use bytes read from a completed predecessor on disk.
        return (stem.with_suffix(".state").read_bytes(),
                stem.with_suffix(".prefix").read_bytes(), stopped)

    def check(self, name, condition):
        self.checks.append({"name": name, "passed": bool(condition)})
        require(condition, "Qualification check failed: " + name)

    def run(self):
        finals = {}
        for sampler in (0, 1):
            schedule = [("init", 17, sampler), ("advance", 0), ("commit", 1, 16),
                        ("advance", 1), ("advance", 2), ("advance", 3),
                        ("advance", 4), ("advance", 5), ("advance", 6)]
            reference = []
            for replay in (0, 1):
                state, prefix = b"", b""
                for index, selected in enumerate(schedule):
                    prior = prefix
                    state, prefix, stopped = self.call(
                        f"s{sampler}-r{replay}-step{index}", state, prefix, command(*selected))
                    prefixes(prefix)
                    self.check(f"s{sampler}-r{replay}-append-only-{index}", prefix.startswith(prior))
                    outcome = (state, prefix, stopped)
                    if replay:
                        self.check(f"s{sampler}-exact-replay-{index}", outcome == reference[index])
                    else:
                        reference.append(outcome)
                cursors, outputs = prefixes(prefix)
                self.check(f"s{sampler}-r{replay}-complete", stopped and tuple(cursors) == TOTAL_UNITS)
            finals[sampler] = outputs
            for modality, output in zip(MODALITIES, outputs):
                (self.args.output / f"s{sampler}-{modality}.raw").write_bytes(output)
            self.call(f"s{sampler}-stopped-rejection", state, prefix, command("advance", 0),
                      reject="stopped state cannot continue")
            initial_state, initial_prefix, _ = reference[0]
            partial_state, partial_prefix, _ = reference[2]
            changed_prefix = partial_prefix[:-1] + bytes([partial_prefix[-1] ^ 1])
            self.call(f"s{sampler}-prefix-tamper", partial_state, changed_prefix,
                      command("advance", 1), reject="state/prefix/asset binding")
            for label, changed in (("weights", self.weights), ("public", self.public)):
                changed = changed[:-1] + bytes([changed[-1] ^ 1])
                self.call(f"s{sampler}-{label}-tamper", initial_state, initial_prefix,
                          command("advance", 0), reject="packet checksum mismatch", **{label: changed})
            auto_a = self.call(f"s{sampler}-auto-a", initial_state, initial_prefix, command("auto", 1000000))
            auto_b = self.call(f"s{sampler}-auto-b", initial_state, initial_prefix, command("auto", 1000000))
            self.check(f"s{sampler}-trained-actor-replay", auto_a == auto_b)
        self.check("sampler-changes-generated-media", finals[0][:3] != finals[1][:3])
        self.check("executable-unchanged", sha(self.args.executable.read_bytes()) == self.binary_hash)
        self.check("weights-unchanged", pinned(self.args.weights, self.manifest["weights"]) == self.weights)
        self.check("public-unchanged", pinned(self.args.public, self.manifest["public"]) == self.public)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "weights", "public", "checkpoint", "manifest", "build-receipt", "source-root", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.executable = args.executable.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    setup_started, setup_cpu = time.perf_counter(), time.process_time()
    setup_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    (args.output / "ASSET_IDENTITY.json").write_bytes(manifest_bytes)
    provenance_output = args.output / "asset-provenance"
    provenance_output.mkdir()
    for name, expected in manifest["asset_provenance"].items():
        require(Path(name).name == name, "Provenance filename must be a basename")
        data = pinned(args.manifest.parent / "trained_asset_provenance" / name, expected)
        (provenance_output / name).write_bytes(data)
    source_root = args.source_root / "codex-rs/hepta-infer-worker-host"
    sources = {name: sha((source_root / name).read_bytes()) for name in SOURCE_FILES}
    head = subprocess.check_output(["git", "-C", str(args.source_root), "rev-parse", "HEAD"], text=True).strip()
    for name in SOURCE_FILES:
        committed = subprocess.check_output(["git", "-C", str(args.source_root), "show",
                      head + ":codex-rs/hepta-infer-worker-host/" + name])
        require(sha(committed) == sources[name], "Uncommitted executable source: " + name)
    build_bytes = args.build_receipt.read_bytes()
    build = json.loads(build_bytes)
    require(build["exit_code"] == 0 and build["source_unchanged"] is True and
            build["source_sha"] == head and build["source_files"] == sources and
            build["executable_sha256"] == sha(args.executable.read_bytes()),
            "Executable build receipt does not match source and binary")
    for path, expected in build["linked_library_sha256"].items():
        require(sha(Path(path).read_bytes()) == expected, "Linked native library changed")
    (args.output / "BUILD.json").write_bytes(build_bytes)
    setup_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    setup_cost = {"wall_seconds": time.perf_counter() - setup_started,
                  "harness_cpu_seconds": time.process_time() - setup_cpu,
                  "child_cpu_seconds": setup_after.ru_utime + setup_after.ru_stime -
                                       setup_usage.ru_utime - setup_usage.ru_stime}
    started, cpu = time.perf_counter(), time.process_time()
    experiment = None
    result = {"schema": "hepta.trained-joint-proposal-qualification.v1", "status": "running",
              "source_sha": head, "source_files": sources, "manifest_sha256": sha(manifest_bytes),
              "build_receipt_sha256": sha(build_bytes), "setup_cost": setup_cost,
              "qualification_source_sha256": {name: sha((Path(__file__).parent / name).read_bytes())
                                             for name in ("build_replay_helper.py", "trained_replay.py")},
              "platform": platform.platform(), "python": platform.python_version(),
              "kernel_only": True, "new_training_updates": 0,
              "adoption_authorized": False, "natural_multimodal_quality_qualified": False,
              "unmeasured": ["energy_joules", "physical_disk_bytes", "fsync_durability",
                             "historical_training_cost", "Agentd_and_durable_control_cost", "per_helper_peak_rss_bytes"],
              "cost_semantics": "Each child and harness CPU interval is disjoint. Child wall phases and parent residual partition call wall; do not add whole call wall again. RSS is cumulative high-water across every child of this harness including git provenance reads, not per-helper RSS."}
    try:
        experiment = Experiment(args, manifest)
        result["executable_sha256"] = experiment.binary_hash
        experiment.run()
        result["status"] = "passed"
    except Exception as error:
        result.update(status="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(wall_seconds=time.perf_counter() - started,
                      harness_cpu_seconds=time.process_time() - cpu,
                      harness_children_peak_rss_bytes=usage.ru_maxrss * 1024)
        if experiment:
            result.update(checks=experiment.checks, steps=experiment.steps,
                          child_cpu_seconds=sum(step["child_cpu_seconds"] for step in experiment.steps),
                          ipc_bytes=sum(step["ipc_bytes"] for step in experiment.steps))
            write_json(args.output / "steps.json", experiment.steps)
        write_json(args.output / "RESULTS.json", result)


if __name__ == "__main__":
    main()
