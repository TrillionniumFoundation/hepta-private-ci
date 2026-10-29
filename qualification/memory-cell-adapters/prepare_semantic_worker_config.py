"""Create a locally pinned, opt-in encoder configuration without spawning it."""
import argparse
import hashlib
import json
from pathlib import Path

from semantic_protocol import ENCODER_DIGEST, canonical

SOURCE_SHA256 = "fc6d50ec0c5cfb1607e473a4b505d625e156c10a32ee6054449f84667e6ef0bd"


def main(args):
    source, script = args.encoder_source.resolve(strict=True), args.worker.resolve(strict=True)
    source_raw, script_raw = source.read_bytes(), script.read_bytes()
    if hashlib.sha256(source_raw).hexdigest() != SOURCE_SHA256 or not 0 < len(script_raw) <= 32768:
        raise ValueError("encoder source identity or worker bound differs")
    value = {"python": str(args.python.absolute()), "worker_script": str(script),
             "worker_digest": hashlib.sha256(script_raw).hexdigest(), "encoder_source": str(source),
             "source_digest": SOURCE_SHA256, "encoder_directory": str(args.encoder.resolve(strict=True)),
             "encoder_digest": ENCODER_DIGEST, "startup_timeout_ms": 60000, "request_timeout_ms": 4000}
    if not args.python.absolute().is_file():
        raise ValueError("explicit Python interpreter is unavailable")
    with args.output.open("xb") as output:
        output.write(canonical(value))
    print(json.dumps({"output": str(args.output), "configuration_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "worker_sha256": value["worker_digest"], "encoder_digest": ENCODER_DIGEST}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--encoder-source", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
