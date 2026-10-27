"""One original owner subprocess; complete public request/response transcript."""
import hashlib
import json
from pathlib import Path
import subprocess


Q = 1 << 24


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


class Native:
    def __init__(self, binary):
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, bufsize=1)
        self.transcript = []

    def call(self, request, expect_error=False):
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("Original owner host stopped: " + self.process.stderr.read())
        response = json.loads(line)
        self.transcript.append({"request": request, "response": response})
        if response["ok"] == expect_error:
            raise RuntimeError("Unexpected owner result: " + repr(response))
        return response.get("result", response)

    def open(self, directory, case, expires, model, calibration):
        self.transcript = []
        self.case = case
        return self.call({"command": "Open", "directory": str(directory), "case": case,
            "expires": expires, "model": str(model), "model_sha256": sha(model),
            "calibration": str(calibration), "calibration_sha256": sha(calibration)})

    def tick(self, phase, feedback, receipt):
        event = f"{self.case}.scan.{receipt['candidate']}" if phase == 0 else f"{self.case}.initial.phase.{phase}"
        return self.call({"command": "Tick", "event_id": event, "phase": phase,
            "feedback_q24": round(feedback * Q), "receipt_digest": digest(receipt)})

    def close(self):
        return self.call({"command": "Close"})

    def finish(self):
        self.process.stdin.close()
        self.process.wait(timeout=10)
        stderr = self.process.stderr.read()
        if self.process.returncode:
            raise RuntimeError(stderr)


def continuation(native, feedback, observed):
    return [native.tick(1, feedback, observed), native.tick(2, 0, observed), native.tick(3, 0, observed)]


def numerical_projection(ticks):
    return [{key: row[key] for key in ("phase", "feedback_q24", "sequence", "activation_q24",
        "eligibility_before_q24", "eligibility_after_q24", "native_abstain", "confidence_ppm",
        "ood_ppm", "proposed_repair", "readout_logit", "owner_authority")} for row in ticks]
