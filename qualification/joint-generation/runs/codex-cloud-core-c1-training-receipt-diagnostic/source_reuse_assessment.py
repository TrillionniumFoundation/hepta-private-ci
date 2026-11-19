"""Source-only assessment added after the original saved-receipt extraction."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


cpu, wall = time.process_time_ns(), time.perf_counter_ns()
started = datetime.now(timezone.utc).isoformat()
out = Path(__file__).resolve().parent
text = """# Decoder-bound finite-code codec reuse hypothesis

This is a prospective implementation candidate, not a measured repair or a qualification result. It uses the retained TRAIN breakdown and source, without reading formal results or held-out inputs.

Across 216 TRAIN calibration requests per seed, output encoding plus its ledger consumed:

| Seed | Service CPU (ms) | Generation+ledger (ms) | Output+ledger (ms) | Output fraction |
|---|---:|---:|---:|---:|
| 11 | 162.171136 | 37.425399 | 124.376073 | 76.69% |
| 23 | 18.222238 | 2.798681 | 15.305252 | 83.99% |
| 47 | 51.214770 | 8.887626 | 42.162215 | 82.32% |

The expensive seed 11 repeat medians are 809584.3125, 763512.875 and 476919.484375 ns/request. All three are retained; this is not one removable outlier. Every request executes the same 19236 declared units, and same-seed output-byte arrays are identical across repeats. The timing variation's cause remains unknown.

`independent/evaluation.py::_outputs` decodes sampled image codes, quantizes them and calls PNG encoding per request. `FrozenGenerator` owns a read-only decoder with 12 fixed image-code rows. A sampled code's learned image and PNG are thus deterministic for that decoder, independently of input labels. The source supports a local per-generator 12-code codec table as concrete repeated-work reuse.

A valid implementation must bind the table to that generator's exact decoder snapshot and quantization/codec specification; produce all 12 images/PNGs during actual charged preparation; retain each request's original categorical RNG order, caption/choice selection, JSON construction and actual serialized output; preserve byte-identical PNG, SHA256 and base64 results; and keep corrupted-decoder observers independent. A table must never be shared by changed decoders or cache ground-truth outcomes, inputs or scoring results.

All actual table preparation, decoding, codec work, memory and lookups must remain in complete CPU accounting. Arithmetic inventories must quote only decoder operations actually executed; no per-request decoder charge remains if it was replaced by an already-paid lookup. PNG/JSON primitives retain byte and measured CPU accounting rather than invented FLOPs. Every arm needs the same service implementation. Existing uncached protocols and failures must remain retained; this changes the declared codec profile prospectively.

The component timer combines sampling, learned decoding, quantization, PNG/hash/base64, JSON and output-ledger work. Its 76.69–83.99% share is an upper bound on the affected segment, not a measured PNG-only cost or a promised speedup. There is no evidence here that caching explains the execution-wave variability, improves content or makes either independent contribution statistically reliable.

The supported next step is implementation plus hand-array equivalence and accounting tests for a separately declared codec profile. No new timing measurement, training, data construction or confirmation is proposed or performed by this assessment. Whether any actual saving can fund content updates, and whether those updates generalize, remain separate questions.
"""
(out / "CODEC_REUSE.md").write_text(text)
with (out / "REPORT.md").open("a", encoding="utf-8") as stream:
    stream.write("\nA subsequent source-only hypothesis supplied after extraction is evaluated in [CODEC_REUSE.md](CODEC_REUSE.md): a decoder-bound local finite-code codec table. Its repeated-work basis is supported; no implementation, speed or scientific-benefit claim is made. The earlier absence of an identified primitive-level timing cause remains unchanged.\n")
receipt = {"command": "PYTHONDONTWRITEBYTECODE=1 python runs/codex-cloud-core-c1-training-receipt-diagnostic/source_reuse_assessment.py",
    "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
    "process_cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall,
    "scope": "administrative source-only prose assessment and report link; no new input receipt, model or dataset reads; final receipt/manifest persistence excluded",
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(out / "SOURCE_REUSE_ADMIN.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
manifest = {path.name: {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
            for path in sorted(out.iterdir()) if path.is_file() and path.name != "SHA256.json"}
(out / "SHA256.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
print(json.dumps(receipt, sort_keys=True))
