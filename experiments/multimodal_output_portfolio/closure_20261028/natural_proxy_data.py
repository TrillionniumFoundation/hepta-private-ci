"""Lazy per-source supervised tensors and tightly bound frozen public features.

Only the small pretrained context features remain resident. Neither trainable
encoder states nor generated emissions are cached. Actual deployment episodes
always recompute their public features and pay their full execution costs.
"""
import json
from pathlib import Path
import time

import numpy as np
import torch

from .data_sources import digest, save
from .natural_port import public_tensors
from .profile_contract import cpu_seconds
from .semantic_backbones import PINS, SemanticBackbones
from .semantic_tsm import TSM_FILE, TSM_SHA, TsmObserver


CACHE_FILES = ("natural_proxy_data.py", "natural_port.py", "semantic_backbones.py", "semantic_tsm.py")


def context_cache(root, rows, output):
    plan = json.loads((root / "SOURCE_PROTOCOL.json").read_text())
    specification = {"schema": "hepta.closure.proxy-cache-contract.v2",
        "source_protocol_sha256": plan["protocol_sha256"],
        "inputs": [{"event_id": row["event_id"], "source_id": row["source_id"],
                    "event_file_sha256": digest((directory / "EVENT.npz").read_bytes())} for directory, row in rows],
        "weights": {**PINS, TSM_FILE: TSM_SHA},
        "implementation_sha256": {name: digest((Path(__file__).parent / name).read_bytes()) for name in CACHE_FILES},
        "public_fields_only": ["context_video", "context_audio", "context_video_mask", "context_audio_mask"],
        "features": ["video_features", "audio_features"],
        "no_trainable_state_or_emission_cache": True}
    cache_path, receipt_path = output / "PUBLIC_CONTEXT_CACHE.npz", output / "PUBLIC_CONTEXT_CACHE.json"
    if cache_path.exists() and receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        if receipt["contract"] != specification or digest(cache_path.read_bytes()) != receipt["sha256"]:
            raise ValueError("Public cache inputs, weights, implementation or retained bytes changed")
    else:
        pann, tsm = SemanticBackbones(root / "pretrained"), TsmObserver(root / "pretrained")
        contexts, started, cpu = {}, time.monotonic(), cpu_seconds()
        for index, (directory, _) in enumerate(rows):
            with np.load(directory / "EVENT.npz") as arrays:
                public = public_tensors(arrays, tsm, pann)
            for key in specification["features"]:
                contexts.setdefault(key, []).append(public[key].numpy()[0])
            if (index + 1) % 16 == 0:
                print(json.dumps({"warmstart_contexts": index + 1, "total": len(rows)}), flush=True)
        with cache_path.with_suffix(".pending").open("wb") as stream:
            np.savez_compressed(stream, **{key: np.stack(value) for key, value in contexts.items()})
        cache_path.with_suffix(".pending").replace(cache_path)
        save(receipt_path, {"schema": "hepta.closure.proxy-cache.v2", "contract": specification,
            "sha256": digest(cache_path.read_bytes()), "cpu_seconds": cpu_seconds() - cpu,
            "wall_seconds": time.monotonic() - started,
            "use": "supervised proxy only; actual complete episodes recompute and bill public features"})
        del pann, tsm
    with np.load(cache_path) as cached:
        result = {key: cached[key].copy() for key in specification["features"]}
    if any(len(array) != len(rows) or not np.isfinite(array).all() for array in result.values()):
        raise ValueError("Invalid bound public context cache")
    return result


class LazyProxyDataset:
    def __init__(self, rows, ontology, contexts):
        self.rows, self.contexts = rows, contexts
        self.action_ids = sorted(map(int, ontology["action"]))
        self.sound_ids = sorted(map(int, ontology["sound"]))

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        index = int(index)
        directory, row = self.rows[index]
        with np.load(directory / "EVENT.npz") as arrays:
            public = {"video": arrays["context_video"].transpose(0, 3, 1, 2).copy(),
                "audio": arrays["context_audio"],
                "video_mask": arrays["context_video_mask"].astype(np.float32) if "context_video_mask" in arrays else np.ones(16, np.float32),
                "audio_mask": arrays["context_audio_mask"].astype(np.float32) if "context_audio_mask" in arrays else np.ones(32000, np.float32)}
            truth = {"video": arrays["target_video"].transpose(0, 3, 1, 2).copy(),
                "image": arrays["target_image"].transpose(2, 0, 1).copy(), "audio": arrays["target_audio"],
                "action": np.asarray(self.action_ids.index(row["action_id"]), np.int64),
                "sound": np.asarray(self.sound_ids.index(row["sound_id"]), np.int64)}
        public.update({key: value[index] for key, value in self.contexts.items()})
        public = {key: torch.from_numpy(np.asarray(value).copy()).unsqueeze(0) for key, value in public.items()}
        truth = {key: torch.from_numpy(np.asarray(value).copy()).unsqueeze(0) for key, value in truth.items()}
        public["video"] = public["video"].float() / 255
        for name in ("video", "image"):
            truth[name] = truth[name].float() / 255
        return public, truth
