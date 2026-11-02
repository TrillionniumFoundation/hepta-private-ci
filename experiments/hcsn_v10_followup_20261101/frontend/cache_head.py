"""Actual common-cache adapter for the selected window-input ordinary head."""

import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_v7_support_20261101.content_interface.content_interface import ContractError
from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import cache_rows
from .fit_frontend import features, predict


class OrdinaryCacheHead:
    """Predict from observed cache; no empirical correctness or quality claim."""

    def __init__(self, checkpoint, *, expected_sha256):
        checkpoint = Path(checkpoint)
        if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != expected_sha256:
            raise ContractError("Ordinary frontend weight identity mismatch")
        protocol = json.loads((checkpoint.parent.parent / "PROTOCOL.json").read_text())
        if protocol.get("input_policy", "window") != "window":
            raise ContractError("Native-rate model cannot consume a compressed window cache")
        selections = json.loads((checkpoint.parent.parent / "SELECTION_COMPLETE.json").read_text())
        if expected_sha256 not in {row["selected_sha256"] for row in selections.values()}:
            raise ContractError("Checkpoint is not selected by the declared training protocol")
        with np.load(checkpoint, allow_pickle=False) as z:
            self.model = {k:z[k].copy() for k in z.files}
        for value in self.model.values():
            value.setflags(write=False)
        self.head_id = "ordinary-window-v10-" + expected_sha256

    def classify(self, content):
        x, observed = cache_rows(content)
        ordered = []
        prefix = 0.
        for kind, packet in enumerate((content.audio, content.video)):
            if packet is None:
                continue
            rows = np.asarray(packet.raw[2:],float).reshape(-1,17)
            prefix = max(prefix,packet.prefix_end)
            ordered.extend((r[0],kind,i) for i,r in enumerate(rows))
        ordered.sort()
        times = np.array([r[0] for r in ordered])
        if prefix <= 0 or prefix > 3.:
            raise ContractError("Head supports accepted prefixes in (0,3] seconds")
        value = features(x,observed,times,str(self.model['modality']),str(self.model['family']),prefix)
        return predict(self.model,value[None])[0]
