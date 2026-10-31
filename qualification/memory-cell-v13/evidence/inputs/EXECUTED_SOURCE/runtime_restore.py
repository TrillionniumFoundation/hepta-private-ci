"""Restore the pinned shared encoder on a resumed worker and probe real texts.

Only embedding replay uses declared floating-point tolerance. Adapter parameters,
Adam, RNG and sampler state remain bit-exact and unchanged by inference.
"""

import argparse
import json
from pathlib import Path
import resource
import time

import numpy as np

from backend import FrozenEncoder
from download_model import FILES, MODEL_ID, REVISION, download
from lifecycle import canonical, sha
from migration import file_sha, fixture, identity, load_model, same_execution, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "rows", "checkpoint", "model-dir", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    report = dict(schema="hepta.memory.runtime-restore.v13", passed=False,
                  embedding_tolerance=dict(rtol=1e-6, atol=1e-7),
                  timing_scope="excludes interpreter/import and pip installation; CI steps retain those durations")
    try:
        preparation = json.loads((args.input / "PREPARE.json").read_text())
        binding = preparation["binding"]
        report.update(binding=binding, node=identity("runtime-restore"))
        same_execution(preparation["node"], report["node"])
        rows = json.loads(args.rows.read_text())
        if sha(canonical(rows)) != binding["source_version"]:
            raise ValueError("raw training rows differ from the fitted source identity")
        frozen, labels = fixture(args.input, binding)
        if len(rows) != len(frozen) or [row["label"] for row in rows] != labels.tolist():
            raise ValueError("raw rows and preencoded feature labels differ")
        manifest = json.loads((args.input / "encoder_manifest.json").read_text())
        existing = {name for name in FILES if (args.model_dir / name).exists()}
        download_start = time.perf_counter()
        downloaded = download(args.model_dir)
        report["download_wall_seconds"] = time.perf_counter() - download_start
        report["downloaded_payload_bytes"] = sum(v["bytes"] for k, v in downloaded["files"].items() if k not in existing)
        report["downloaded_files"] = {name: value for name, value in downloaded["files"].items() if name not in existing}
        report["official_model"] = dict(model_id=MODEL_ID, revision=REVISION)
        encoder_start = time.perf_counter()
        encoder = FrozenEncoder(args.model_dir, threads=1)
        report["encoder_initialization_wall_seconds"] = time.perf_counter() - encoder_start
        if encoder.manifest_hash != binding["encoder_hash"] or encoder.manifest != manifest["encoder"]:
            raise ValueError("restored base files or runtime manifest differ")
        report["encoder_manifest"] = encoder.manifest
        report["encoder_hash"] = encoder.manifest_hash
        checkpoint_sha = file_sha(args.checkpoint)
        model = load_model(args.checkpoint, binding)
        state_before = model.state_hash()
        inference_start = time.perf_counter()
        restored = encoder.encode([row["text"] for row in rows])
        report["encoder_inference_wall_seconds"] = time.perf_counter() - inference_start
        delta = np.abs(restored.astype(np.float64) - frozen.astype(np.float64))
        prediction_start = time.perf_counter()
        fresh_predictions, frozen_predictions = model.predict(restored), model.predict(frozen)
        report["adapter_probe_wall_seconds"] = time.perf_counter() - prediction_start
        report.update(rows=len(rows), embedding_max_abs_delta=float(delta.max()),
                      embeddings_close=bool(np.allclose(restored, frozen, rtol=1e-6, atol=1e-7)),
                      predictions_equal=bool(np.array_equal(fresh_predictions, frozen_predictions)),
                      predictions=fresh_predictions.tolist(), encoder_stats=encoder.stats,
                      checkpoint_sha256=checkpoint_sha, state_before=state_before,
                      state_after=model.state_hash(),
                      checkpoint_file_unchanged=checkpoint_sha == file_sha(args.checkpoint))
        report["passed"] = (report["embeddings_close"] and report["predictions_equal"]
                            and report["state_after"] == state_before and report["checkpoint_file_unchanged"])
        if not report["passed"]:
            raise ValueError("restored backend numerical/state replay failed")
    except BaseException as error:
        report["error"] = dict(type=type(error).__name__, message=str(error))
        raise
    finally:
        report.update(wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      retained_base_files={str(p.relative_to(args.model_dir)): p.stat().st_size
                                           for p in args.model_dir.rglob("*") if p.is_file()})
        args.out.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.out, report)


if __name__ == "__main__":
    main()
