"""Explicitly synthetic four-media mechanism task; never natural-task evidence."""

import hashlib

import numpy as np
import torch


def batch(ids, split="train"):
    rows = []
    for identity in ids:
        seed = int.from_bytes(hashlib.sha256(f"joint-mechanism-v1:{split}:{identity}".encode()).digest()[:8], "little")
        rng = np.random.default_rng(seed)
        shape, tone = int(rng.integers(4)), int(rng.integers(4))
        yy, xx = np.mgrid[:16, :16]
        cx, cy = rng.uniform(5, 10, 2)
        colour = np.eye(3)[shape % 3] * 0.7 + 0.15
        frames = []
        for step in range(4):
            dx, dy = xx - cx - 0.6 * step, yy - cy
            if shape == 0:
                mask = dx * dx + dy * dy < 13
            elif shape == 1:
                mask = (np.abs(dx) < 3.5) & (np.abs(dy) < 3.5)
            elif shape == 2:
                mask = (np.abs(dx) + np.abs(dy)) < 5
            else:
                mask = (np.abs(dx) < 1.8) | (np.abs(dy) < 1.8)
            frame = np.full((3, 16, 16), 0.04, dtype=np.float32)
            frame[:, mask] = colour[:, None]
            frames.append(frame)
        video = np.stack(frames)
        audio = (0.5 * np.sin(2 * np.pi * (tone + 2) * np.arange(1024) / 128 + rng.uniform(-0.1, 0.1))).astype(np.float32)
        image = video[2]
        image_mask = np.ones_like(image); image_mask[:, :, 6:10] = 0
        video_mask = np.ones_like(video); video_mask[1:3] = 0
        audio_mask = np.ones_like(audio); audio_mask[256:768] = 0
        observed = {"image": image * image_mask, "image_mask": image_mask,
                    "video": video * video_mask, "video_mask": video_mask,
                    "audio": audio * audio_mask, "audio_mask": audio_mask,
                    "tokens": np.array([1, 2 + int(rng.integers(4))], dtype=np.int64)}
        targets = {"image": image, "audio": audio, "video": video,
                   "text": np.array([shape, tone], dtype=np.int64)}
        rows.append((observed, targets))
    public = {key: torch.from_numpy(np.stack([r[0][key] for r in rows])) for key in rows[0][0]}
    target = {key: torch.from_numpy(np.stack([r[1][key] for r in rows])) for key in rows[0][1]}
    return public, target


def select(rows, index):
    return {k: v[index:index + 1] for k, v in rows.items()}
