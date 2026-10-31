"""Qualify a real selected training checkpoint on the independent Rust backend.

Retains numeric evidence, actual native stream journal/chunks, final media and
complete subprocess costs. It is an implementation experiment, not a new model
quality panel. Run as a module from the repository root.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import wave

import numpy as np
from PIL import Image
import torch

from ...mechanism_data import batch
from ...media import read_bundle
from ..model import JointGenerator
from ..native_bridge import NativeSession, build_native, differential


def run(checkpoint, output, rustc):
    checkpoint, output = Path(checkpoint).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    torch.set_num_threads(1)
    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if set(("config", "state_dict")) - saved.keys():
        raise ValueError("Expected the selected training checkpoint with config/state_dict")
    model = JointGenerator(**saved["config"]).eval()
    model.load_state_dict(saved["state_dict"], strict=True)
    public, _ = batch([3], "v3-native-implementation")
    with tempfile.TemporaryDirectory(prefix="hepta-native-qualified-") as temp:
        temp = Path(temp)
        binary, build = build_native(temp / "native", rustc=rustc)
        result = differential(model, public, temp / "differential", binary)
        if not result["passed"]:
            raise RuntimeError("Selected training checkpoint failed native numeric comparison")
        export = temp / "differential" / "export"
        policy = NativeSession(binary, export / "weights.hps", export / "public.hps", temp / "policy")
        policy.create(seed=20261031, sampler="mean")
        reference = deepcopy(model).double()
        public64 = {k: v.to(torch.int64 if k == "tokens" else torch.float64) for k, v in public.items()}
        with torch.no_grad():
            logp, _ = reference.policy(reference.encode(public64), 1.0)
        action_names = ("shared", "image", "audio", "video", "text", "verify", "stop")
        expected_action = action_names[int(logp.argmax(-1)[0])]
        selected = policy.auto(1.0)
        if selected["argument"] != expected_action:
            raise RuntimeError("Native trained actor dispatch differs from original Torch")
        session = NativeSession(binary, export / "weights.hps", export / "public.hps", temp / "stream")
        session.create(seed=20261031, sampler="splitmix-normal-v1")
        session.step("shared")
        for modality, count in [("image", 5), ("audio", 128), ("video", 1), ("text", 1)]:
            session.commit(modality, count)
        prefix_meta, prefix_tensors = session.inspect()
        retained = {m: hashlib.sha256(prefix_tensors[f"prefix.{m}"].astype("u1").tobytes()).hexdigest()
                    for m in ("image", "audio", "video", "text")}
        expected_head, prior_calls = session.head, list(session.calls)
        session = NativeSession(binary, export / "weights.hps", export / "public.hps", temp / "stream")
        session.refresh(expected_head=expected_head)
        # Later genuine native content evolution must preserve all committed bytes.
        for action in ("image", "verify", "audio", "video", "text"):
            session.step(action)
        _, changed = session.inspect()
        unchanged = all(np.array_equal(changed[f"prefix.{m}"], prefix_tensors[f"prefix.{m}"])
                        for m in ("image", "audio", "video", "text"))
        if not unchanged:
            raise RuntimeError("Committed output was rewritten by native continuation")
        for modality, count in [("image", 11), ("audio", 896), ("video", 3), ("text", 1)]:
            session.commit(modality, count)
        session.step("stop")
        session.refresh(expected_head=session.head)
        _, final_tensors = session.inspect()
        manifest = session.export(temp / "outputs")
        readback, identities = read_bundle(temp / "outputs")
        with Image.open(temp / "outputs" / "image.png") as picture:
            image_exact = picture.convert("RGB").tobytes() == final_tensors["prefix.image"].astype("u1").tobytes()
        with wave.open(str(temp / "outputs" / "audio.wav")) as sound:
            audio_exact = sound.readframes(1024) == final_tensors["prefix.audio"].astype("u1").tobytes()
        with Image.open(temp / "outputs" / "video.gif") as video:
            frames = []
            for index in range(video.n_frames):
                video.seek(index); frames.append(video.convert("RGB").tobytes())
            video_exact = b"".join(frames) == final_tensors["prefix.video"].astype("u1").tobytes()
        text_exact = (temp / "outputs" / "text.txt").read_bytes() == final_tensors["prefix.text"].astype("u1").tobytes()
        exact = {"image": image_exact, "audio": audio_exact, "video": video_exact, "text": text_exact}
        if not all(exact.values()) or len(readback["audio"][0]) != 1024 or readback["video"].shape[1] != 4:
            raise RuntimeError("Independent native media readback failed")
        calls = prior_calls + session.calls
        execution = {"schema": "hepta.selected-trained-native-content.v3",
                     "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                     "checkpoint_name": checkpoint.name, "checkpoint_metadata": saved.get("metadata", {}),
                     "config": saved["config"], "build": build,
                     "differential": result,
                     "trained_actor": {"selected_action": selected["argument"], "original_torch_action": expected_action,
                                       "successor_head": policy.head, "calls": policy.calls},
                     "stream": {"prefix_commit_head": expected_head, "final_head": session.head,
                                "committed_prefix_sha256": retained, "prefix_bytes_preserved": unchanged,
                                "actual_bundle": manifest, "independent_readback_sha256": identities,
                                "all_delivered_bytes_match_committed_prefix": exact,
                                "selected_model_executed_in_rust": True,
                                "external_python_model_invocations": 0,
                                "native_subprocess_calls": len(calls), "calls": calls,
                                "child_cpu_seconds": sum(c["child_cpu_seconds"] for c in calls),
                                "call_wall_seconds": sum(c["wall_seconds"] for c in calls)},
                     "implementation_acceptance": True, "quality_or_cost_superiority": False,
                     "streaming_policy_trained_for_committed_prefix": False,
                     "total_qualification_wall_seconds": time.perf_counter() - start}
        # Retain the full lightweight native recovery chain and exact delivered bytes.
        # The original trained checkpoint is the reproducible weight source; avoid
        # duplicating the larger exported FP64 model into the evidence publication.
        shutil.copytree(temp / "stream" / "events", output / "events")
        shutil.copytree(temp / "stream" / "chunks", output / "chunks")
        shutil.copytree(temp / "outputs", output / "outputs")
        shutil.copyfile(export / "EXPORT.json", output / "EXPORT.json")
        shutil.copyfile(export / "public.hps", output / "public.hps")
        (output / "RESULTS.json").write_text(json.dumps(execution, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"implementation_acceptance": True,
                      "maximum_fp64_absolute": result["maximum_fp64_absolute"],
                      "maximum_fp32_absolute": result["maximum_fp32_absolute"],
                      "prefix_bytes_preserved": unchanged,
                      "checkpoint_sha256": execution["checkpoint_sha256"]}))
    return execution


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rustc", required=True)
    args = parser.parse_args()
    run(args.checkpoint, args.output, args.rustc)
