"""Frozen neural waveform reference; synthesis and observation have separate APIs."""

import base64
import json
from pathlib import Path
import subprocess

import numpy as np
import torch


class WaveReference:
    def __init__(self, python, assets, asr_assets, output, profile=None):
        output = Path(output)
        self.stderr = (output.parent / (output.name + ".stderr.log")).open("x")
        profile = Path(profile or Path(__file__).with_name("waveform_protocol.json"))
        self.samples_per_event = json.loads(profile.read_text())["synthesis"]["word_samples"]
        self.process = subprocess.Popen([str(python), "-B", "-m",
            "experiments.multimodal_output_portfolio.closure_20261025.media.wave_worker",
            "--assets", str(assets), "--asr-assets", str(asr_assets), "--output", str(output), "--profile", str(profile)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True)
        self.load_receipt = self._read()
        self.last_observation = None

    def _read(self):
        raw = self.process.stdout.readline()
        if not raw:
            raise RuntimeError("Frozen neural waveform worker exited")
        result = json.loads(raw)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "Waveform worker rejected request"))
        return result

    def _call(self, request):
        self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
        self.process.stdin.flush()
        return self._read()

    def generate(self, probabilities, directory):
        response = self._call({"operation": "synthesize", "probabilities": probabilities.detach().cpu().tolist(),
                               "output_directory": str(directory)})
        signal = np.frombuffer(base64.b64decode(response.pop("waveform_base64"), validate=True), dtype="<f4").copy().reshape(2, self.samples_per_event)
        if not np.isfinite(signal).all() or np.abs(signal).max() > 1:
            raise ValueError("Malformed neural decoder waveform")
        return torch.from_numpy(signal), response

    def predict_pcm16(self, actual_pcm):
        self.last_observation = self._call({"operation": "observe", "pcm16_base64": base64.b64encode(actual_pcm).decode()})
        return self.last_observation["predictions"]

    def close(self):
        if self.process.poll() is not None:
            self.stderr.close()
            return {"worker_exit_code": self.process.returncode}
        receipt = self._call({"operation": "close"})
        self.process.stdin.close()
        self.process.wait(timeout=20)
        self.stderr.close()
        if self.process.returncode != 0:
            raise RuntimeError("Neural waveform worker exit failure")
        return receipt
