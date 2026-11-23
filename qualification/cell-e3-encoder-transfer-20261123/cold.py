"""Load one standalone student in a new network- and teacher-isolated process."""
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from encoder import Encoder, file_sha, score

arm = sys.argv[1]
root = Path(sys.argv[2])
torch.set_num_threads(2)
started, cpu = time.perf_counter(), time.process_time()
freeze = json.loads((root / "freeze.json").read_bytes())
for f,k in (("heads.npz","heads_sha256"),("policy.json","policy_sha256")):
    assert file_sha(root / f) == freeze[k]
nets = {f.name for f in Path("/sys/class/net").iterdir()}
assert nets == {"lo"}
def traffic():
    return sum(int((Path("/sys/class/net/lo/statistics")/p).read_text())
               for p in ("rx_bytes","tx_bytes"))
assert traffic() == 0
encoder = Encoder(root / "encoder")
assert encoder.info == freeze["encoder"]
rows = json.loads((root / "blind.json").read_bytes())
assert all(set(r) == {"id","domain","query","candidates"} for r in rows)
with np.load(root/"heads.npz", allow_pickle=False) as heads:
    policy = json.loads((root/"policy.json").read_bytes())
    x, gates, cosine = encoder.features(rows)
    predictions = score(heads, policy, arm, rows, x, gates, cosine)
assert traffic() == 0
rec = dict(arm=arm, rows=predictions, wall_seconds=time.perf_counter()-started,
           cpu_seconds=time.process_time()-cpu, encoder_inputs=encoder.presentations,
           encoder_batches=encoder.batches, input_tokens=encoder.input_tokens,
           network_interfaces=sorted(nets), network_bytes=traffic(), freeze_sha256=file_sha(root/"freeze.json"),
           blind_sha256=file_sha(root/"blind.json"))
(root / ("cold-"+arm+".json")).write_text(json.dumps(rec, separators=(",",":")))
