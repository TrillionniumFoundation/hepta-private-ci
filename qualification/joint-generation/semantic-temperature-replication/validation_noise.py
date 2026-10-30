"""Fixed two NEW noise draws on the unchanged validation GROUPS only.

No TEST endpoint or default seed override. Renderer/body/order/variants follow the
original dataset implementation; only the prospective noise seed differs. These
are new corruptions of already used validation groups,not new held-out groups.
"""
import hashlib
import numpy as np
from data import _groups,attributes,render,SIDE

def validation_noise(noise_seed, variants=6):
    if type(noise_seed) is not int or noise_seed not in (9001,9002) or type(variants) is not int or variants != 6:
        raise ValueError("invalid dataset request")
    rng = np.random.default_rng(noise_seed)
    low, full, targets, group_ids, hashes = [], [], [], [], []
    for scene, color_cmd, shape_cmd, position_cmd in _groups()['validation']:
        color, shape, position = attributes(scene)
        target = ((color if color_cmd == 0 else color_cmd - 1) * 2
                  + (shape if shape_cmd == 0 else shape_cmd - 1)) * 2
        target += position if position_cmd == 0 else position_cmd - 1
        # Instruction features encode words, not the target scene.
        instruction = np.concatenate((np.eye(4)[color_cmd], np.eye(3)[shape_cmd],
                                      np.eye(3)[position_cmd]))
        group = f"{scene}:{color_cmd}:{shape_cmd}:{position_cmd}"
        for _ in range(variants):
            noise = rng.uniform(0.03, 0.25)
            observed = np.clip(render(scene) + rng.normal(0, noise, (SIDE, SIDE, 3)), 0, 1)
            thumbnail = observed.reshape(4, 2, 4, 2, 3).mean(axis=(1, 3))
            thumbnail = thumbnail.repeat(2, axis=0).repeat(2, axis=1)
            full.append(np.concatenate((observed.reshape(-1), instruction)))
            low.append(np.concatenate((thumbnail.reshape(-1), instruction)))
            targets.append(target)
            group_ids.append(group)
            hashes.append(hashlib.sha256(full[-1].astype("<f8").tobytes()).hexdigest())
    return {"low": np.asarray(low), "full": np.asarray(full),
            "labels": np.asarray(targets), "groups": group_ids, "input_hashes": hashes}

