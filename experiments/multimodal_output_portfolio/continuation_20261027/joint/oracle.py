"""Offline original-generator upper bound, with every candidate byte retained.

The oracle sees evaluation truth and searches sixteen plans. It is not a
deployable matched-information arm; beating it identifies gains that cannot
come from routing the original generator's two-transition action family.
"""

import hashlib
import io
from itertools import product
import json
from pathlib import Path
import zipfile

import numpy as np
from PIL import Image
import torch

from ...v6.data import make_batch, render_tokens
from ...v6.neural import ACTIONS, parameter_hash
from ...v6.observer import observe_tensors
from ...v6.plan_training import ControlledSnapshot
from ...repair_20261026.joint.train import apply_plan
from .protocol import PROTOCOL as P, checksum, write_json


@torch.inference_mode()
def original_oracle(assets, corpus, audit, output):
    plans = tuple(product(ACTIONS, repeat=2))
    archive = output / "ORACLE_OUTPUTS.zip"
    rows, bundle_count = [], 0
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as packed:
        with (output / "ORACLE_ROWS.jsonl").open("x") as stream:
            for seed in P["seeds"]:
                original = ControlledSnapshot.load(Path(assets) / f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt")
                model = original._base._model
                before = parameter_hash(model)
                for k, condition in enumerate(P["conditions"]):
                    for start in range(0, P["test_pairs"], 32):
                        n = min(32, P["test_pairs"] - start)
                        batch = make_batch(corpus, "test", n, P["evaluation_seed"] + start + k * 10000,
                                           corruption=condition, offset=start)
                        rng = torch.Generator().manual_seed(seed * 100003 + start + k * 1009)
                        initial = model.encode(batch.observation, torch.randn(n, model.hidden, generator=rng))
                        candidates = [[] for _ in range(n)]
                        for plan_index, plan in enumerate(plans):
                            generated = model.decode(apply_plan(model, initial, plan))
                            decoded, captions, receipts = [], [], []
                            arrays = (generated.image_logits.sigmoid() * 255).round().to(torch.uint8).squeeze(1).numpy()
                            for j, array in enumerate(arrays):
                                image_stream = io.BytesIO()
                                Image.fromarray(array).save(image_stream, format="PNG")
                                image_bytes = image_stream.getvalue()
                                caption_bytes = render_tokens(generated.token_ids[j]).encode("utf-8")
                                key = f"{seed}/{condition}/{start + j}/{plan_index}"
                                image_member, text_member = key + ".png", key + ".txt"
                                packed.writestr(image_member, image_bytes)
                                packed.writestr(text_member, caption_bytes)
                                # Read the persisted archive member before scoring it.
                                png, text = packed.read(image_member), packed.read(text_member)
                                with Image.open(io.BytesIO(png)) as image:
                                    decoded.append(torch.from_numpy(np.array(image, copy=True)).float()[None, None] / 255)
                                captions.append(text.decode("utf-8"))
                                receipts.append({"image_member": image_member, "text_member": text_member,
                                    "image_sha256": hashlib.sha256(png).hexdigest(),
                                    "text_sha256": hashlib.sha256(text).hexdigest()})
                                bundle_count += 1
                            scores = observe_tensors(audit, torch.cat(decoded), captions, batch.target.pixels, batch.target.labels)
                            for j in range(n):
                                candidates[j].append({"plan_index": plan_index, "plan": plan,
                                    "audit": scores[j], "artifacts": receipts[j]})
                        for j in range(n):
                            best = max(candidates[j], key=lambda c: c["audit"]["utility"])
                            row = {"seed": seed, "pair": start + j, "condition": condition,
                                "source_ids": batch.source_ids[j], "utility": best["audit"]["utility"],
                                "selected_plan": best["plan_index"], "candidates": candidates[j]}
                            stream.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                            rows.append(row)
                        stream.flush()
                if parameter_hash(model) != before:
                    raise RuntimeError("Oracle modified the original generator")
                print(f"oracle seed={seed} accumulated_candidate_bundles={bundle_count}", flush=True)
    write_json(output / "ORACLE_RECEIPT.json", {"schema": "hepta.ndu.original-oracle.v1", "plans": plans,
        "offline_privileged_target_access": True, "equal_budget_deployed_arm": False,
        "same_initial_latent_noise": True, "candidate_bundles": bundle_count,
        "archive_sha256": checksum(archive), "rows_sha256": checksum(output / "ORACLE_ROWS.jsonl")})
    return rows


def compare_to_oracle(delivered, oracle):
    from .evaluation import joint_ce
    shape = len(P["seeds"]), P["test_pairs"], len(P["conditions"])
    upper, candidate = np.full(shape, np.nan), np.full(shape, np.nan)
    source_ids = {}
    for row in oracle:
        index = P["seeds"].index(row["seed"]), row["pair"], P["conditions"].index(row["condition"])
        if np.isfinite(upper[index]):
            raise ValueError("Duplicate oracle source/condition")
        upper[index] = row["utility"]
        source_ids[index] = tuple(row["source_ids"])
    for row in delivered:
        if row["split"] == "test" and row["arm"] == "joint_risk":
            index = P["seeds"].index(row["seed"]), row["pair"], P["conditions"].index(row["condition"])
            if np.isfinite(candidate[index]) or tuple(row["source_ids"]) != source_ids.get(index):
                raise ValueError("Repeated or different-source oracle comparison")
            candidate[index] = row["audit"]["utility"]
    if not np.isfinite(upper).all() or not np.isfinite(candidate).all():
        raise ValueError("Incomplete oracle comparison grid")
    rng = np.random.default_rng(P["bootstrap_seed"] + 1)
    differences = []
    for _ in range(P["bootstrap_replicates"]):
        ids = rng.integers(P["test_pairs"], size=P["test_pairs"])
        differences.append(joint_ce(candidate[:, ids]) - joint_ce(upper[:, ids]))
    alpha = (1 - P["interval"]) / 2
    interval = np.quantile(differences, [alpha, 1 - alpha]).tolist()
    per_seed = [joint_ce(a[None]) - joint_ce(b[None]) for a, b in zip(candidate, upper)]
    return {"comparison": "joint_risk-original_16_plan_privileged_oracle", "ce_difference": joint_ce(candidate) - joint_ce(upper),
        "paired_97_5_interval": interval, "per_seed_ce_differences": per_seed,
        "attribution_gate_passed": interval[0] > 0 and min(per_seed) > 0,
        "oracle_ce": joint_ce(upper), "same_budget_deployed_baseline": False}
