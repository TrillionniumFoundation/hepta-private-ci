#!/usr/bin/env python3
"""Compare the actual Cargo proposal helper with pinned historical Torch code."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import resource
import struct
import subprocess
import time
import traceback
import wave

from recover import CHECKPOINT_SHA256, SOURCE_SHA, checked, digest, donor_modules


MODALITIES = ("image", "audio", "video", "text")
ACTIONS = ("shared", "image", "audio", "video", "text", "verify", "stop")
TOTAL_UNITS = (16, 1024, 4, 2)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, length):
        end = self.offset + length
        if length < 0 or end > len(self.data):
            raise ValueError("Truncated actual helper response")
        result, self.offset = self.data[self.offset:end], end
        return result

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def blob(self):
        length = self.u32()
        if length > 65_536:
            raise ValueError("Actual helper response exceeds blob bound")
        return self.take(length)


def prefix_data(data):
    reader, cursors, outputs = Reader(data), [0] * 4, [bytearray() for _ in range(4)]
    while reader.offset < len(data):
        if reader.take(4) != b"HGC1":
            raise ValueError("Actual media frame magic")
        modality = reader.take(1)[0]
        start, units, length = reader.u32(), reader.u32(), reader.u32()
        if modality >= 4 or start != cursors[modality] or units == 0 or start + units > TOTAL_UNITS[modality]:
            raise ValueError("Actual media cursor continuity")
        payload = reader.take(length)
        if modality < 3 and length != units * (48, 2, 768)[modality]:
            raise ValueError("Actual media payload size")
        if modality == 3:
            text = payload.decode("utf8")
            for index in range(start, start + units):
                key, delimiter, maximum = (("action=", ";", 62), ("sound=", "\n", 16))[index]
                if not text.startswith(key):
                    raise ValueError("Actual text label")
                digits, text = text[len(key):].split(delimiter, 1)
                if str(int(digits)) != digits or not 0 <= int(digits) <= maximum:
                    raise ValueError("Actual text label domain")
            if text:
                raise ValueError("Actual text trailing data")
        outputs[modality].extend(payload)
        cursors[modality] += units
    return cursors, [bytes(value) for value in outputs]


class Helper:
    def __init__(self, path, weights, public, output):
        self.path, self.weights, self.public, self.output = path, weights, public, output
        self.calls = []

    def call(self, name, state, prefix, command):
        identity = digest(name.encode() + state + prefix + command)
        request = bytearray(b"HJREQV01" + bytes.fromhex(identity))
        for blob in (self.weights, self.public, state, prefix):
            request.extend(struct.pack("<I", len(blob)) + blob)
        request.extend(command)
        started, before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
        with subprocess.Popen([str(self.path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE) as child:
            timed_out = False
            try:
                stdout, stderr = child.communicate(request, timeout=30)
            except subprocess.TimeoutExpired:
                timed_out = True
                child.kill()
                stdout, stderr = child.communicate()
            after = resource.getrusage(resource.RUSAGE_CHILDREN)
            record = {"index": len(self.calls), "operation": name, "pid": child.pid,
                      "request_sha256": digest(request), "operation_digest": identity,
                      "request_bytes": len(request), "response_bytes": len(stdout),
                      "response_sha256": digest(stdout), "stderr": stderr.decode("utf8", errors="replace"),
                      "returncode": child.returncode, "timed_out": timed_out,
                      "wall_seconds": time.perf_counter() - started,
                      "child_cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime}
        self.calls.append(record)
        write_json(self.output / "CALLS.json", self.calls)
        if child.returncode != 0 or timed_out:
            raise RuntimeError("Actual helper failed: " + name)
        if len(stdout) < 145 or digest(stdout[:-64]).encode() != stdout[-64:]:
            raise ValueError("Actual helper response checksum")
        reader = Reader(stdout[:-64])
        if reader.take(8) != b"HJRESV01" or reader.take(32).hex() != identity:
            raise ValueError("Actual helper response identity")
        stopped = reader.take(1)[0]
        if stopped not in (0, 1):
            raise ValueError("Actual helper disposition")
        phases = list(struct.unpack("<4Q", reader.take(32)))
        successor, delta = reader.blob(), reader.blob()
        if reader.offset != len(reader.data) or sum(phases) > record["wall_seconds"] * 1_000_000:
            raise ValueError("Actual helper response trailing data or timer scope")
        record["child_disjoint_phase_micros"] = dict(zip(("codec", "encoder", "inference", "planning"), phases))
        record["state_sha256"], record["delta_sha256"] = digest(successor), digest(delta)
        write_json(self.output / "CALLS.json", self.calls)
        return successor, prefix + delta, bool(stopped)


def state_vectors(state):
    result = {name: getattr(state, name).detach().cpu().numpy().reshape(-1)
              for name in ("context", "shared", "slots", "feedback")}
    for layer, values in enumerate(state.core):
        result.update({f"core.{layer}.{name}": value.detach().cpu().numpy().reshape(-1)
                       for name, value in values.items()})
    return result


def check_state(donor, actual, prefix, stopped, state64, state32, protocol):
    import numpy as np

    metadata, tensors = donor["bridge"].unpack(actual)
    cursors, outputs = prefix_data(prefix)
    expected_metadata = {
        "kind": "joint-generation-proposal-state-v1", "seed": "17", "sampler": "mean",
        "weights": protocol["weights_sha256"], "input": protocol["public_sha256"],
        "bridge.prefix_sha256": digest(prefix), "steps": str(state64.steps),
        "stopped": str(state64.stopped).lower(),
        "verified": str(state64.verified_revision == state64.content_revision).lower(),
        "content_revision": str(state64.content_revision), "verified_revision": str(state64.verified_revision),
        **{f"cursor.{name}": str(cursors[index]) for index, name in enumerate(MODALITIES)},
    }
    if metadata != expected_metadata or stopped != state64.stopped:
        raise ValueError("Actual helper discrete state/asset binding differs from Torch")
    expected64, expected32 = state_vectors(state64), state_vectors(state32)
    prefix_keys = {f"prefix.{name}" for name in MODALITIES}
    if set(tensors) != set(expected64) | prefix_keys:
        raise ValueError("Actual helper complete state tensor inventory differs")
    errors64, errors32 = {}, {}
    for name, expected in expected64.items():
        if tensors[name].shape != expected.shape:
            raise ValueError("Actual helper state tensor shape differs")
        errors64[name] = float(np.max(np.abs(tensors[name] - expected)))
        errors32[name] = float(np.max(np.abs(tensors[name] - expected32[name])))
    for index, name in enumerate(MODALITIES):
        if not np.array_equal(tensors[f"prefix.{name}"], np.frombuffer(outputs[index], dtype=np.uint8)):
            raise ValueError("Actual prefix tensors differ from emitted bytes")
    passed = (max(errors64.values()) < protocol["state_absolute_error_strictly_below_fp64"]
              and max(errors32.values()) < protocol["state_absolute_error_strictly_below_fp32"])
    return {"passed": passed, "fp64_absolute_errors": errors64, "fp32_absolute_errors": errors32,
            "discrete_state_and_prefix_exact": True}


def media_bytes(model, state):
    import numpy as np
    import torch

    raw = model.outputs(state)
    result = []
    for name in MODALITIES[:3]:
        values = (torch.tanh(raw[name]) if name == "audio" else torch.sigmoid(raw[name])).cpu().numpy()
        if name == "audio":
            result.append(np.rint(np.clip(values, -1, 1) * 32767).astype("<i2").tobytes())
        else:
            frames = 4 if name == "video" else 1
            pixels = values.reshape(frames, 3, 16, 16).transpose(0, 2, 3, 1)
            result.append(np.rint(pixels * 255).astype(np.uint8).tobytes())
    labels = [int(values.argmax(-1).item()) for values in raw["text"]]
    result.append(f"action={labels[0]};sound={labels[1]}\n".encode())
    return result


def run(args, protocol, helper, donor, saved):
    import torch

    model = donor["model"].JointGenerator(**saved["config"]).eval()
    model.load_state_dict(saved["state_dict"], strict=True)
    public_metadata, values = donor["bridge"].unpack(helper.public)
    if public_metadata != {"kind": "joint-generator-public-v3"}:
        raise ValueError("Unexpected public packet schema")
    public64 = {name: torch.from_numpy(value.copy()).to(torch.int64 if name == "tokens" else torch.float64)
                for name, value in values.items()}
    public32 = {name: value.to(torch.int64 if name == "tokens" else torch.float32) for name, value in public64.items()}
    double, single = deepcopy(model).double(), deepcopy(model).float()
    states, media, automatic = [], [], []
    actual, prefix = b"", b""
    with torch.no_grad():
        state64, state32 = double.encode(public64), single.encode(public32)
        for index, action in enumerate(("init", *protocol["action_sequence"])):
            if action == "init":
                command = b"\x00" + struct.pack("<Q", protocol["seed"]) + b"\x00"
            else:
                command = bytes((1, ACTIONS.index(action)))
                state64, _ = double.advance(state64, action, public64)
                state32, _ = single.advance(state32, action, public32)
            actual, prefix, stopped = helper.call(action, actual, prefix, command)
            comparison = check_state(donor, actual, prefix, stopped, state64, state32, protocol)
            states.append({"action": action, **comparison})
            (args.output / f"state-{index:02}-{action}.hps").write_bytes(actual)
            expected_media = media_bytes(double, state64)
            if not stopped and prefix:
                raise ValueError("Nonterminal advance unexpectedly published output")
            if stopped:
                cursors, emitted = prefix_data(prefix)
                media.append({"action": action, "all_media_exact": emitted == expected_media,
                              "complete_cursors": cursors == list(TOTAL_UNITS)})
            else:
                for modality, name in enumerate(MODALITIES):
                    child, child_prefix, child_stop = helper.call(
                        f"{action}-commit-{name}", actual, prefix,
                        bytes((3, modality)) + struct.pack("<I", TOTAL_UNITS[modality]))
                    branch = check_state(donor, child, child_prefix, child_stop, state64, state32, protocol)
                    cursors, emitted = prefix_data(child_prefix)
                    media.append({"action": action, "modality": name,
                                  "payload_sha256": digest(emitted[modality]),
                                  "bytes": len(emitted[modality]),
                                  "exact": (emitted[modality] == expected_media[modality]
                                            and cursors == [TOTAL_UNITS[i] if i == modality else 0 for i in range(4)]),
                                  "state": branch})
            if action in protocol["auto_remaining_millionths_after"]:
                remaining = protocol["auto_remaining_millionths_after"][action]
                choice64 = int(double.policy(state64, remaining / 1_000_000)[0].argmax(-1).item())
                choice32 = int(single.policy(state32, remaining / 1_000_000)[0].argmax(-1).item())
                next64, _ = double.advance(state64, ACTIONS[choice64], public64)
                next32, _ = single.advance(state32, ACTIONS[choice64], public32)
                child, child_prefix, child_stop = helper.call(
                    f"{action}-auto", actual, prefix, b"\x02" + struct.pack("<I", remaining))
                comparison = check_state(donor, child, child_prefix, child_stop, next64, next32, protocol)
                auto_cursors, auto_emitted = prefix_data(child_prefix)
                auto_output_matches = ((auto_cursors == list(TOTAL_UNITS)
                                        and auto_emitted == media_bytes(double, next64))
                                       if child_stop else child_prefix == prefix)
                automatic.append({"after": action, "remaining_millionths": remaining,
                                  "expected_fp64_action": ACTIONS[choice64], "fp32_choice_matches": choice32 == choice64,
                                  "output_exact": auto_output_matches,
                                  "planning_wall_observed": helper.calls[-1]["child_disjoint_phase_micros"]["planning"] > 0,
                                  "state": comparison})
            print(json.dumps({"action": action, "helper_calls": len(helper.calls), "state_passed": states[-1]["passed"]}), flush=True)
    (args.output / "prefix.hgc").write_bytes(prefix)
    _, emitted = prefix_data(prefix)
    from PIL import Image
    for name, data in zip(("image.rgb", "audio.s16le", "video.rgb", "text.txt"), emitted):
        (args.output / name).write_bytes(data)
    Image.frombytes("RGB", (16, 16), emitted[0]).save(args.output / "image.png")
    with Image.open(args.output / "image.png") as decoded:
        if decoded.convert("RGB").tobytes() != emitted[0]:
            raise ValueError("Saved image readback differs")
    for index in range(4):
        Image.frombytes("RGB", (16, 16), emitted[2][index * 768:(index + 1) * 768]).save(args.output / f"video-{index}.png")
    with wave.open(str(args.output / "audio.wav"), "wb") as audio:
        audio.setparams((1, 2, 2048, 1024, "NONE", "not compressed"))
        audio.writeframes(emitted[1])
    with wave.open(str(args.output / "audio.wav"), "rb") as audio:
        if audio.readframes(1024) != emitted[1] or audio.getnframes() != 1024:
            raise ValueError("Saved audio readback differs")
    passed = (all(item["passed"] for item in states)
              and all(item.get("all_media_exact", item.get("exact")) and item.get("complete_cursors", True)
                      and item.get("state", {"passed": True})["passed"] for item in media)
              and all(item["state"]["passed"] and item["fp32_choice_matches"] and item["output_exact"]
                      and item["planning_wall_observed"] for item in automatic))
    comparisons = states + [item["state"] for item in media if "state" in item] + [item["state"] for item in automatic]
    return {"passed": passed, "states": states, "media": media, "auto": automatic,
            "prefix_sha256": digest(prefix), "actual_helper_calls": len(helper.calls),
            "state_comparisons": len(comparisons),
            "state_maximum_fp64_absolute": max(max(item["fp64_absolute_errors"].values()) for item in comparisons),
            "state_maximum_fp32_absolute": max(max(item["fp32_absolute_errors"].values()) for item in comparisons)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--helper", required=True, type=Path)
    parser.add_argument("--expected-helper-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    args.output.mkdir(parents=True, exist_ok=False)
    directory = Path(__file__).resolve().parent
    protocol_raw = (directory / "NUMERICAL-PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_raw)
    repository = directory.parents[1]
    fixtures = repository / "codex-rs/hepta-neuron/tests/fixtures"
    manifest = json.loads(checked((fixtures / "joint-trained-v1.json").read_bytes(), protocol["fixture_manifest_sha256"]))
    weights = b"".join(checked((fixtures / chunk["path"]).read_bytes(), chunk["sha256"], chunk["bytes"])
                       for chunk in manifest["weight_chunks"])
    checked(weights, protocol["weights_sha256"])
    public = checked((fixtures / "joint-trained-public.hps").read_bytes(), protocol["public_sha256"])
    binary = checked(args.helper.read_bytes(), args.expected_helper_sha256)
    helper = Helper(args.helper.resolve(), weights, public, args.output)
    registration = {"schema": "hepta.historical-trained-joint-numeric-run.v1",
                    "registered_utc": datetime.now(timezone.utc).isoformat(), "protocol_sha256": digest(protocol_raw),
                    "reference_source_sha": SOURCE_SHA,
                    "protocol": protocol, "helper_sha256": digest(binary), "helper_bytes": len(binary),
                    "helper_build_origin": "Actual Cargo hepta-joint-propose supplied by unified candidate native gate; no alternate kernel.",
                    "validator_sha256": digest(Path(__file__).read_bytes()), "recovery_source_sha256": digest((directory / "recover.py").read_bytes()),
                    "helper_sources": {str(path.relative_to(repository)): digest(path.read_bytes())
                                       for path in sorted((repository / "codex-rs/hepta-infer-worker-host/src/joint_generation").glob("*.rs"))},
                    "helper_entry_sha256": digest((repository / "codex-rs/hepta-infer-worker-host/src/bin/hepta-joint-propose.rs").read_bytes()),
                    "python": platform.python_version(), "platform": platform.platform(), "new_training_updates": 0}
    write_json(args.output / "REGISTERED.json", registration)
    result = {"status": "failed", "passed": False}
    try:
        import torch
        torch.set_num_threads(1)
        checked(args.checkpoint.read_bytes(), CHECKPOINT_SHA256)
        saved = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
        with donor_modules(args.source_repository) as donor:
            if donor["hashes"] != manifest["source_files"]:
                raise ValueError("Reference source differs from recovery manifest")
            if donor["parent"].tensor_digest(saved["state_dict"]) != manifest["checkpoint"]["joint_tensor_sha256"]:
                raise ValueError("Historical reference tensor identity differs")
            result.update(run(args, protocol, helper, donor, saved))
        result["status"] = "passed" if result["passed"] else "failed_comparison"
        result["torch"] = str(torch.__version__)
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
        (args.output / "failure.txt").write_text(traceback.format_exc())
    finally:
        result.update({"registration_sha256": digest((args.output / "REGISTERED.json").read_bytes()),
                       "wall_seconds": time.perf_counter() - started,
                       "parent_cpu_seconds": time.process_time() - cpu,
                       "sum_helper_process_wall_seconds": sum(item["wall_seconds"] for item in helper.calls),
                       "sum_helper_process_cpu_seconds": sum(item["child_cpu_seconds"] for item in helper.calls),
                       "cpu_scope": "Parent measurement starts after stdlib imports. Child CPU includes full spawned helper lifetime; nested wall is not additive.",
                       "energy": None, "physical_helper_attempts": len(helper.calls), "new_training_updates": 0,
                       "scope": "Actual proposal helper differential; ordinary Agentd owner/ACK/cancel qualification is recorded separately.",
                       "excluded": protocol["excluded"]})
        write_json(args.output / "RESULTS.json", result)
    print(json.dumps({key: result[key] for key in ("status", "passed", "physical_helper_attempts", "wall_seconds")}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
