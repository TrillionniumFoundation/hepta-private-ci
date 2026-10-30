"""Actual file-to-logits inherited learned HCSN content adapter, weights frozen."""
import json
import hashlib
from pathlib import Path
import time
import numpy as np
from common import ROOT, sha, protocol
from third.memory.reference import forward, readout


class ContentAdapter:
    def __init__(self):
        wall, cpu = time.perf_counter(), time.process_time()
        self.checkpoint = ROOT / protocol()["content_checkpoint"]
        self.parameters = dict(np.load(self.checkpoint))
        self.setup = dict(checkpoint_sha256=sha(self.checkpoint), trainable_parameters=0,
                          frozen_parameter_count=sum(a.size for a in self.parameters.values()),
                          load_wall_seconds=time.perf_counter()-wall,
                          load_cpu_seconds=time.process_time()-cpu)

    def read(self, path):
        wall, cpu = time.perf_counter(), time.process_time()
        start = time.perf_counter()
        raw = Path(path).read_bytes()
        packet = json.loads(raw)
        io = time.perf_counter()-start
        start = time.perf_counter()
        symbols = np.asarray(packet["symbols"], dtype=np.int32)
        assert symbols.ndim == 1 and symbols[-1] == -1
        assert np.all((symbols[:-1] >= 0) & (symbols[:-1] < 4))
        x = np.zeros((1, len(symbols), 16), np.float32)
        x[0, np.arange(len(symbols)-1), symbols[:-1]] = 1.
        x[0, 0, 4], x[0, -1, 5] = 1., 1.
        dt = np.asarray(packet["dt"], np.float32)[None]
        feature = time.perf_counter()-start
        start = time.perf_counter()
        state = forward(self.parameters, x, dt, "full")
        logits, numerical = readout(self.parameters, state, "mass", solver_dtype=np.float64)
        content = time.perf_counter()-start
        return dict(observation=int(np.argmax(logits[0, :2])), logits=logits[0].tolist(),
                    payload_sha256=hashlib.sha256(raw).hexdigest(), payload_bytes=len(raw),
                    io_wall_seconds=io, feature_wall_seconds=feature,
                    content_wall_seconds=content, total_wall_seconds=time.perf_counter()-wall,
                    total_cpu_seconds=time.process_time()-cpu, numerical=numerical)
