"""Development-only codec capability diagnosis; never consumes heldout seeds."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import torch

EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXPERIMENT))
from codec import Decoder, _audio_readback, _image_readback, loss_decoder, semantic_metrics
from data import make_worlds, subset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--min-lr", type=float, default=0.001)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.manual_seed(919)
    decoder = Decoder()
    if args.initial is not None:
        decoder.load_state_dict(torch.load(args.initial, map_location="cpu", weights_only=True))
    training = make_worlds(2048, 3000919)
    validation = make_worlds(128, 4000919)
    generator = torch.Generator().manual_seed(20919 if args.initial is not None else 950)
    optimizer = torch.optim.AdamW(decoder.parameters(), lr=0.001)
    log, started = [], time.perf_counter()
    for step in range(args.steps):
        fraction = step / max(1, args.steps - 1)
        for group in optimizer.param_groups:
            group["lr"] = args.min_lr + 0.5 * (0.001 - args.min_lr) * (1 + math.cos(math.pi * fraction))
        batch = subset(training, torch.randint(2048, (64,), generator=generator))
        loss = loss_decoder(decoder(torch.cat((batch["facts"], batch["style"]), 1)), batch["targets"])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(decoder.parameters(), 10)
        optimizer.step()
        if step % 500 == 0 or step == args.steps - 1:
            log.append({"step": step, "loss": float(loss.detach())})
        if step % 2000 == 0:
            print(json.dumps({"step": step, "loss": float(loss.detach()),
                              "elapsed": time.perf_counter() - started}), flush=True)
    decoder.eval()
    with torch.no_grad():
        predicted = decoder(torch.cat((validation["facts"], validation["style"]), 1))
        metrics = semantic_metrics(predicted, validation["facts"])
        _, iw, _, ir = _image_readback(predicted["image"])
        _, vw, _, vr = _image_readback(predicted["video"].reshape(-1, 3, 16, 16))
        _, phase, amplitude, ar = _audio_readback(predicted["audio"])

    def stat(value):
        return {"mean": float(value.mean()), "q10": float(value.quantile(.1)),
                "q90": float(value.quantile(.9))}

    result = {"scope": "Development codec capability; actual true fact coordinates supplied as diagnostic ceiling",
              "heldout_accessed": False, "finished_utc": datetime.now(timezone.utc).isoformat(),
              "initial_sha256": hashlib.sha256(args.initial.read_bytes()).hexdigest() if args.initial is not None else None,
              "initialization_seed": 919, "min_learning_rate": args.min_lr,
              "decoder_parameters": sum(p.numel() for p in decoder.parameters()),
              "codec_source_sha256": hashlib.sha256((EXPERIMENT / "codec.py").read_bytes()).hexdigest(),
              "updates": args.steps, "runtime_seconds": time.perf_counter() - started, "log": log,
              "modality_loss": metrics["modality_loss"].mean(0).tolist(),
              "metrics": {key: float(metrics[key].mean()) for key in
                          ("factual_loss", "correct", "resolved", "correct_resolved", "style_lawful", "style_consistent", "lawful_consistent")},
              "readback": {"image_width": stat(iw), "video_width": stat(vw),
                           "image_residual": stat(ir), "video_residual": stat(vr),
                           "audio_residual": stat(ar), "audio_phase": stat(phase),
                           "audio_amplitude": stat(amplitude)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(decoder.state_dict(), args.output.with_suffix(".pt"))
    args.output.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
