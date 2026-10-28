"""V8 learned heads on the existing bounded, authority-free worker protocol."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
from addressing.worker import MAX_FRAME_BYTES, MAX_RESPONSE_BYTES, serve
from v6.encoder import MiniLMEncoder
from v8_addressing.model import SelectiveIntentModel, policy_digest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        model = SelectiveIntentModel.load(arguments.model, MiniLMEncoder(arguments.encoder), arguments.model_digest)
        if not isinstance(model.calibration, dict) or not model.calibration.get("empirical_gate_passed"):
            raise ValueError("independent calibration gate has not passed")
        print(json.dumps({"schema": "hepta.memory.v7.address-worker-ready.v1", "model_digest": model.identity,
                          "policy_digest": policy_digest(), "max_frame_bytes": MAX_FRAME_BYTES,
                          "max_response_bytes": MAX_RESPONSE_BYTES}), file=sys.stderr, flush=True)
        raise SystemExit(serve(model, sys.stdin.buffer, sys.stdout.buffer, sys.stderr))
    except (OSError, ValueError, KeyError) as error:
        print("memory-address-worker startup rejected: " + type(error).__name__, file=sys.stderr, flush=True)
        raise SystemExit(2) from error
