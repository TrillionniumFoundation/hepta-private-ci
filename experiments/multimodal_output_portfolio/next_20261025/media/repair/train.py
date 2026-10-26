"""Two fixed additional fit-only seeds; old cohorts are explicitly development."""

import argparse
import json
from pathlib import Path
import time

import torch
from torch.nn import functional as F

from ....closure_20261025.media.coherent import MelSpeech
from ....closure_20261025.media.sources import save_json, sha
from ....v7_media.corpus import speech_spectrum
from ....v7_media.models import weights_sha256
from ..audio_sources import load_audio
from .model import EnsembleIngress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("sources", "allocation", "initial", "original", "old-development", "protocol", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol = json.loads(args.protocol.read_text())
    if protocol.get("additional_seeds") != [23179, 23197]:
        raise ValueError("Require the two prospectively specified training seeds")
    for path, expected in protocol["frozen_candidate_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Prospective repair training bytes changed")
    for path in (args.allocation, args.initial, args.original):
        if protocol["frozen_candidate_sha256"].get(str(path.resolve())) != sha(path):
            raise ValueError("Actual repair training argument identity differs")
    save_json(args.output / "registration.json", {"schema": "hepta.next.media-repair-training.v1",
              "protocol_path": str(args.protocol.resolve()), "protocol_sha256": sha(args.protocol),
              "frozen_candidate_sha256": protocol["frozen_candidate_sha256"],
              "started_unix_ns": time.time_ns(), "audit_model_loaded": False,
              "new_qualification_or_confirmation_opened": False})
    allocation = json.loads(args.allocation.read_text())
    rows = allocation["roles"]["fit"]
    if len(rows) != 3000:
        raise ValueError("Training must use the same registered three thousand fit recordings")
    sounds = load_audio(args.sources, rows)
    labels = torch.tensor([row["label"] for row in rows])
    initial = torch.load(args.initial, map_location="cpu", weights_only=True)["state_dict"]
    front = MelSpeech().eval().requires_grad_(False)
    front.load_state_dict(initial)
    with torch.no_grad():
        features = torch.cat([front.front_end(speech_spectrum(sounds[start:start + 64]))
                              for start in range(0, len(sounds), 64)])
    del sounds, front
    members, training = [], []
    original = MelSpeech().eval().requires_grad_(False)
    original.load_state_dict(torch.load(args.original, map_location="cpu", weights_only=True)["state_dict"])
    if not torch.equal(original.mel_bank, initial["mel_bank"]):
        raise ValueError("Original and initial ingress models use different auditory transforms")
    members.append(original)
    for seed in protocol["additional_seeds"]:
        torch.manual_seed(seed)
        rng = torch.Generator().manual_seed(seed)
        model = MelSpeech()
        model.load_state_dict(initial)
        before = weights_sha256(model)
        model.train().requires_grad_(True)
        optimizer = torch.optim.AdamW(model.parameters(), lr=.0008, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, 2000, eta_min=.00008)
        losses, gradient_max = [], 0.
        stage_wall, stage_cpu = time.perf_counter_ns(), time.process_time_ns()
        for step in range(2000):
            ids = torch.randint(len(labels), (32,), generator=rng)
            x = torch.roll(features[ids], int(torch.randint(-3, 4, (), generator=rng)), -1).clone()
            x += .025 * torch.randn(x.shape, generator=rng)
            f, t = int(torch.randint(37, (), generator=rng)), int(torch.randint(61, (), generator=rng))
            x[:, :, f:f + 4] = 0
            x[:, :, :, t:t + 4] = 0
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model.features(x), labels[ids])
            loss.backward()
            gradient_max = max(gradient_max, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
            optimizer.step()
            scheduler.step()
            losses.append(float(loss.detach()))
            if step % 400 == 0 or step == 1999:
                print(json.dumps({"seed": seed, "step": step + 1, "fit_ce": losses[-1]}), flush=True)
        model.eval().requires_grad_(False)
        after = weights_sha256(model)
        if before == after or gradient_max <= 0:
            raise ValueError("No actual new ingress learning")
        path = args.output / f"seed-{seed}.pt"
        torch.save({"state_dict": model.state_dict(), "architecture": "MelSpeech", "weights_sha256": after}, path)
        training.append({"seed": seed, "checkpoint": str(path.resolve()), "checkpoint_sha256": sha(path),
                         "initial_parameters_sha256": before, "parameters_sha256": after,
                         "gradient_abs_sum_max": gradient_max, "losses": losses,
                         "wall_ns": time.perf_counter_ns() - stage_wall,
                         "cpu_ns": time.process_time_ns() - stage_cpu})
        members.append(model)
    del features
    development = allocation["roles"]["qualification"]
    if any(not torch.equal(member.mel_bank, members[0].mel_bank) for member in members):
        raise ValueError("Candidate selection cannot share features across different auditory transforms")
    sounds = load_audio(args.sources, development)
    with torch.inference_mode():
        features = torch.cat([members[0].front_end(speech_spectrum(sounds[start:start + 64]))
                              for start in range(0, len(sounds), 64)])
        member_probabilities = torch.stack([member.features(features).softmax(-1) for member in members])
    del sounds, features
    source_index = {row["sha256"]: index for index, row in enumerate(development)}
    old_paths = sorted(args.old_development.glob("row-*-audio.json"))
    for old_path in old_paths:
        if protocol["frozen_candidate_sha256"].get(str(old_path.resolve())) != sha(old_path):
            raise ValueError("Actual development row argument differs from the registered selection cohort")
    old_rows = [json.loads(path.read_text()) for path in old_paths]
    if len(old_rows) != 12:
        raise ValueError("Require the same twelve old development tasks, not a new selected subset")
    candidates = []
    for name, indices in (("original", [0]), ("seed-23179", [1]), ("seed-23197", [2]), ("mean-three", [0, 1, 2])):
        predictions = member_probabilities[indices].mean(0).argmax(-1).tolist()
        correct = sum(value == row["label"] for value, row in zip(predictions, development))
        pair_correct = sum([predictions[source_index[key]] for key in row["speech_source_sha256"]]
                           == row["score"]["expected_after_observation"] for row in old_rows)
        candidates.append({"name": name, "members": indices, "old300_correct": correct,
                           "old12_audio_pair_correct": pair_correct, "old300_predictions": predictions,
                           "development_gate_pass": correct >= 255 and pair_correct >= 9})
    eligible = [row for row in candidates if row["development_gate_pass"]]
    selected = max(eligible or candidates,
                   key=lambda row: (row["old300_correct"], row["old12_audio_pair_correct"], -candidates.index(row)))
    ensemble = EnsembleIngress(len(selected["members"]))
    for target, index in zip(ensemble.members, selected["members"]):
        target.load_state_dict(members[index].state_dict())
    ensemble.eval().requires_grad_(False)
    path = args.output / "audio-input.pt"
    torch.save({"state_dict": ensemble.state_dict(), "member_count": len(selected["members"]),
                "selected_members": selected["members"], "architecture": "EnsembleIngress",
                "weights_sha256": weights_sha256(ensemble)}, path)
    if any(sha(path) != expected for path, expected in protocol["frozen_candidate_sha256"].items()):
        raise ValueError("Repair training dependency changed during execution")
    save_json(args.output / "summary.json", {"status": "completed", "checkpoint": str(path.resolve()),
              "checkpoint_sha256": sha(path), "parameters_sha256": weights_sha256(ensemble),
              "training": training, "candidate_selection": candidates, "selected_candidate": selected["name"],
              "development_accuracy": selected["old300_correct"] / 300,
              "development_audio_pair_accuracy": selected["old12_audio_pair_correct"] / 12,
              "development_gate_pass": selected["development_gate_pass"],
              "old_qualification_is_now_development": True,
              "independent_qualification_claimed": False,
              "new_qualification_or_confirmation_opened": False,
              "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})


if __name__ == "__main__":
    main()
