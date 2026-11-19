"""Fixed twofold group holdout within original FIT catalog, never original TEST.

Fold f holds out FIT catalog parity f; its training/calibration uses parity 1-f.
This is per-new-model group holdout,not globally never-observed groups. No learned
outcomes enter allocation. New evaluation corruptions use different fixed seeds.
"""
import hashlib
import numpy as np
from data import _groups,attributes,render,SIDE

def partition_groups(fold):
    if type(fold) is not int or fold not in (0,1):raise ValueError('fixed fold0/1')
    catalog=tuple(_groups()['train'])
    if len(catalog)!=260 or len(set(catalog))!=260:raise ValueError('fixed FIT catalog')
    held=tuple(catalog[fold::2]);fit=tuple(catalog[1-fold::2])
    if len(fit)!=130 or len(held)!=130 or set(fit)&set(held):raise ValueError('exact disjoint130/130')
    return fit,held

def group_dataset(fold,role,noise_slot=0,variants=6):
    if type(fold) is not int or fold not in (0,1) or type(variants) is not int or variants!=6:raise ValueError('fixed fold/variants')
    if role not in ('fit','heldout') or type(noise_slot) is not int:raise ValueError('no originalvalidation/TEST endpoint')
    if (role=='fit' and noise_slot!=0) or (role=='heldout' and noise_slot not in (0,1)):raise ValueError('fixed noise slots')
    fit,held=partition_groups(fold);groups=fit if role=='fit' else held
    noise_seed=1701+fold if role=='fit' else 2701+10*fold+noise_slot
    rng = np.random.default_rng(noise_seed)
    low, full, targets, group_ids, hashes = [], [], [], [], []
    for scene, color_cmd, shape_cmd, position_cmd in groups:
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

