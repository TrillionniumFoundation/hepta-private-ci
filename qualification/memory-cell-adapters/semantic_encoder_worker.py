"""One pinned MiniLM session; bounded, serialized, authority-free embeddings.

Run with python -I -u -B.  No batch inference, text normalization, cell values,
labels, owner records, mutable weights or retrieval fallback enter this worker.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import types

MAX_REQUEST = 16384
MAX_RESPONSE = 32768


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def load_encoder(source, expected_source, directory, expected_encoder):
    raw = source.read_bytes()
    if len(raw) > 32768 or hashlib.sha256(raw).hexdigest() != expected_source:
        raise ValueError("encoder source identity differs")
    module = types.ModuleType("pinned_inventory_encoder")
    module.__file__ = str(source)
    exec(compile(raw, str(source), "exec"), module.__dict__)
    encoder = module.PinnedMiniLMEncoder(directory, threads=1, max_tokens=128)
    if encoder.digest != expected_encoder:
        raise ValueError("encoder feature identity differs")
    return encoder


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--encoder-source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--encoder-digest", required=True)
    args = parser.parse_args()
    encoder = load_encoder(args.encoder_source, args.source_sha256, args.encoder, args.encoder_digest)
    # Warm the existing session before accepting a request; the warm-up is
    # deliberately separate from all training and evaluation queries.
    encoder.encode(["Pinned inventory semantic encoder warm up."])
    ready = {"schema": "hepta.memory.inventory-encoder-ready.v1", "encoder_digest": encoder.digest,
             "worker_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
             "source_digest": args.source_sha256, "dimension": 384, "native_batch": 1,
             "max_request": MAX_REQUEST, "max_response": MAX_RESPONSE, "base_bytes": encoder.base_bytes}
    sys.stderr.buffer.write(canonical(ready) + b"\n"); sys.stderr.buffer.flush()
    previous_id = 0
    while True:
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 1)
        if not raw:
            return
        if len(raw) > MAX_REQUEST or not raw.endswith(b"\n"):
            raise ValueError("request frame bound")
        request = json.loads(raw, object_pairs_hook=unique_object)
        if set(request) != {"schema", "request_id", "text", "text_digest", "encoder_digest"} \
                or request["schema"] != "hepta.memory.inventory-encoder-request.v1" \
                or type(request["request_id"]) is not int or not previous_id < request["request_id"] < 2**64 \
                or request["encoder_digest"] != encoder.digest:
            raise ValueError("request binding")
        text = request["text"]
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 8192 \
                or hashlib.sha256(text.encode()).hexdigest() != request["text_digest"]:
            raise ValueError("request text identity")
        previous_id = request["request_id"]
        wall, cpu = time.perf_counter_ns(), time.process_time_ns()
        tokenized = encoder.tokenizer.encode(text)
        truncated = bool(tokenized.overflowing)
        features = [] if truncated else encoder.encode([text])[0].tolist()
        response = {"schema": "hepta.memory.inventory-encoder-response.v1", "request_id": previous_id,
                    "text_digest": request["text_digest"], "encoder_digest": encoder.digest,
                    "features": features, "truncated": truncated, "tokens": len(tokenized.ids),
                    "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall}
        encoded = canonical(response)
        if len(encoded) > MAX_RESPONSE:
            raise ValueError("response frame bound")
        sys.stdout.buffer.write(encoded + b"\n"); sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
