"""Measure a frozen candidate only in the reserved, isolated native fixture.

Production serving remains in worker.py and requires admission. This separate
entry point preserves failed calibration and applies exactly the same learned
policies. It grants no final-use authority and refuses every other owner scope.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap
from addressing.worker import MAX_FRAME_BYTES, MAX_RESPONSE_BYTES, serve, unique_object
from v6.encoder import MiniLMEncoder
from v8_addressing.model import SelectiveIntentModel, policy_digest


FIXTURE_OWNER = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c81"
FIXTURE_SCOPE = "cognitive:" + FIXTURE_OWNER + ":" + hashlib.sha256(b"agent_private").hexdigest()


class ShadowModel(SelectiveIntentModel):
    def decide(self, hypothesis):
        decision = super().decide(hypothesis)
        decision["score_kind"] = "qualification-shadow: " + decision["score_kind"]
        return decision


class FixtureInput:
    def __init__(self, incoming):
        self.incoming = incoming

    def readline(self, limit):
        raw = self.incoming.readline(limit)
        if not raw or len(raw) >= limit or not raw.endswith(b"\n"):
            return raw
        try:
            frame = json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return raw
        if isinstance(frame, dict) and isinstance(frame.get("request"), dict) and isinstance(frame.get("registry"), dict):
            if frame["request"].get("scope") != FIXTURE_SCOPE or frame["registry"].get("scope") != FIXTURE_SCOPE:
                raise ValueError("shadow evaluation cannot leave the reserved fixture scope")
        return raw


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        model = ShadowModel.load(arguments.model, MiniLMEncoder(arguments.encoder), arguments.model_digest)
        if not isinstance(model.calibration, dict):
            raise ValueError("shadow evaluation requires the completed, preserved calibration result")
        print(json.dumps({"schema": "hepta.memory.v7.address-worker-ready.v1", "model_digest": model.identity,
                          "policy_digest": policy_digest(), "max_frame_bytes": MAX_FRAME_BYTES,
                          "max_response_bytes": MAX_RESPONSE_BYTES}), file=sys.stderr, flush=True)
        raise SystemExit(serve(model, FixtureInput(sys.stdin.buffer), sys.stdout.buffer, sys.stderr))
    except (OSError, ValueError, KeyError) as error:
        print("qualification shadow worker rejected: " + type(error).__name__, file=sys.stderr, flush=True)
        raise SystemExit(2) from error
