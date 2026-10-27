"""Hash-bound input reads and weights-only saved parameter / SGD checks.

Torch is imported only in tensor-deserialization helpers, never to construct
or execute a research model. The old-input precheck uses released V3 files.
"""
import hashlib
import io
import json
from pathlib import Path
import numpy as np

if __package__:
    from .training_audit_common import (SEEDS, need, valid_hash)
else:
    from training_audit_common import (SEEDS, need, valid_hash)

if __package__:
    from .training_audit_trace import (fit_initial, head_prediction)
else:
    from training_audit_trace import (fit_initial, head_prediction)

class Inputs:
    def __init__(self):
        self.identities = {}
        self.read_bytes = 0
        self.read_calls = 0
        self.checkpoint_loads = 0

    def data(self,path,expected=None):
        path = Path(path).resolve()
        raw = path.read_bytes()
        self.read_bytes += len(raw)
        self.read_calls += 1
        digest = hashlib.sha256(raw).hexdigest()
        need(expected is None or digest==expected,"Input SHA mismatch: "+str(path))
        need(str(path) not in self.identities or self.identities[str(path)]["sha256"]==digest,"Input changed while reading: "+str(path))
        self.identities[str(path)] = {"sha256":digest,"bytes":len(raw)}
        return raw

    def json(self,path,expected=None):
        return json.loads(self.data(path,expected))

    def files(self,root,expected,exact=True,exclude=()):
        root = Path(root).resolve()
        need(expected,"Empty file inventory")
        for relative,digest in expected.items():
            path = (root/relative).resolve()
            need(not Path(relative).is_absolute() and path.is_relative_to(root) and path.is_file(),"Unsafe/missing inventory entry")
            self.data(path,digest)
        if exact:
            actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()
                      and str(p.relative_to(root)) not in exclude}
            need(actual==set(expected),"Unexpected/missing file in "+str(root))

    def unchanged(self):
        for path,record in list(self.identities.items()):
            self.data(path,record["sha256"])

def tensor_array(value,label):
    import torch
    need(isinstance(value,torch.Tensor) and value.device.type=="cpu" and value.layout==torch.strided,label+" is not a dense CPU tensor")
    result = value.detach().contiguous().numpy()
    need(np.isfinite(result).all(),label+" contains nonfinite values")
    return result

def saved_state_identity(parameters,optimizer):
    digest = hashlib.sha256()
    for name,value in parameters.items():
        digest.update(name.encode())
        digest.update(tensor_array(value,"parameter "+name).tobytes())
    parameter_sha = digest.hexdigest()
    digest = hashlib.sha256(json.dumps(optimizer["param_groups"],sort_keys=True).encode())
    for index,fields in sorted(optimizer["state"].items()):
        digest.update(str(index).encode())
        for name,value in sorted(fields.items()):
            digest.update(name.encode())
            digest.update(tensor_array(value,"optimizer "+name).tobytes())
    return {"parameters":parameter_sha,"optimizer":digest.hexdigest()}

def checkpoint_audit(inputs,path,digest,protocol,seed,metadata_expected,*,old=False):
    import torch
    raw = inputs.data(path,digest)
    value = torch.load(io.BytesIO(raw),map_location="cpu",weights_only=True)
    inputs.checkpoint_loads += 1
    expected_schema = "hepta.field-bridge.v3.complete-adapter.1" if old else "hepta.field-bridge.v4.complete-adapter.1"
    need(value["schema"]==expected_schema and value["training_configuration"]==protocol["training"],"Checkpoint schema/configuration differs")
    need(value["metadata"]==metadata_expected and value["metadata"]["seed"]==seed,"Checkpoint metadata differs")
    if not old:
        need(value["study_id"]==protocol["study_id"],"Checkpoint study identity differs")
    state = value if old else value["state"]
    parameters,optimizer = state["parameters"],state["optimizer"]
    expected_names = {name+suffix for name in protocol["training"]["adapter_modules"] for suffix in (".up",".down")}
    need(set(parameters)==expected_names and len(parameters)==16,"Checkpoint adapter capacity differs")
    shapes = {}
    count = 0
    for name,tensor in parameters.items():
        array = tensor_array(tensor,name)
        need(array.dtype==np.float32 and array.ndim==2 and array.shape[0 if name.endswith('.down') else 1]==8,
             "Adapter dtype/rank differs")
        shapes[name] = list(array.shape)
        count += array.size
    need(set(optimizer)=={"param_groups","state"} and len(optimizer["param_groups"])==1,"Incomplete/non-SGD optimizer structure")
    group = optimizer["param_groups"][0]
    need(group["params"]==list(range(16)) and group["momentum"]==protocol["training"]["momentum"]
         and group["dampening"]==0 and group["weight_decay"]==0 and group["nesterov"] is False
         and group["maximize"] is False and group["differentiable"] is False
         and group["foreach"] is None and group["fused"] is None,"Plain-SGD semantics differ")
    need(set(optimizer["state"]).issubset(set(range(16))),"Unknown optimizer parameter state")
    ordered = list(parameters.values())
    for index,fields in optimizer["state"].items():
        need(set(fields)=={"momentum_buffer"},"Unexpected SGD state fields")
        buffer = tensor_array(fields["momentum_buffer"],"momentum buffer")
        need(buffer.shape==tuple(ordered[index].shape) and buffer.dtype==np.float32,"Momentum tensor inventory differs")
    actual = saved_state_identity(parameters,optimizer)
    need(state["identity"]==actual,"Saved parameter/SGD tensors do not match recorded identity")
    gradient_sha,rng_sha = None,None
    if not old:
        need(set(state)=={"parameters","optimizer","gradients","identity","rng"},"Incomplete full transaction state")
        need(len(state["gradients"])==16,"Missing incoming gradients")
        hasher = hashlib.sha256()
        for parameter,gradient in zip(ordered,state["gradients"],strict=True):
            if gradient is None:
                hasher.update(b"none\0")
            else:
                array = tensor_array(gradient,"saved gradient")
                need(tuple(array.shape)==tuple(parameter.shape) and array.dtype==np.float32,"Saved gradient shape/dtype differs")
                hasher.update(str((tuple(gradient.shape),str(gradient.dtype))).encode()+b"\0")
                hasher.update(array.tobytes())
        gradient_sha = hasher.hexdigest()
        rng = tensor_array(state["rng"],"saved RNG")
        need(rng.dtype==np.uint8 and rng.ndim==1 and rng.size>0,"Incomplete CPU RNG snapshot")
        rng_sha = hashlib.sha256(rng.tobytes()).hexdigest()
    need(valid_hash(value["frozen_base_sha256"]),"Missing frozen base identity")
    return {"file_sha256":digest,"bytes":len(raw),"identity":actual,"parameter_count":int(count),
            "parameter_shapes":shapes,"learning_rate":group["lr"],"momentum_state_parameters":len(optimizer["state"]),
            "gradient_tensor_sha256":gradient_sha,"rng_sha256":rng_sha,"frozen_base_sha256":value["frozen_base_sha256"]}


def old_input_check(protocol_path, old_root, inputs):
    """Same released-V3 precheck previously executed by the retained inline driver."""
    protocol = inputs.json(protocol_path)
    old = Path(old_root).resolve()
    rows = []
    for seed in SEEDS:
        pins = protocol["frozen_v3_learning_artifacts"][str(seed)]
        bank = inputs.json(old/f"bank/{seed}/BANK.json", pins[f"bank/{seed}/BANK.json"]["sha256"])
        reference = inputs.json(old/f"reference/{seed}/REFERENCE.json", pins[f"reference/{seed}/REFERENCE.json"]["sha256"])
        fitted = inputs.json(old/f"fit/{seed}/CONTROLLERS.json", pins[f"fit/{seed}/CONTROLLERS.json"]["sha256"])
        complete = inputs.json(old/f"reference/{seed}/COMPLETE.json")
        zero = next(row for row in reference["candidates"] if row["action_index"] == 0)
        checked = checkpoint_audit(inputs, old/f"reference/{seed}/constant-0.pt",
            complete["files"]["constant-0.pt"], protocol, seed, zero["checkpoint"]["metadata"], old=True)
        origin, initial = fit_initial(bank)
        need(checked["identity"] == initial and checked["momentum_state_parameters"] == 0,
             "Released V3 zero checkpoint differs from the bank initial state")
        for head in fitted["controllers"].values():
            head_prediction(head, origin)
        rows.append({"seed": seed, "old_zero_checkpoint": checked, "four_head_shapes_checked": True})
    inputs.unchanged()
    return {"schema": "hepta.field-bridge.v4.auditor-old-input-precheck.1", "passed": True,
        "scope": "Only already released V3 heads/bank/reference metadata and three zero adapter checkpoint files; no new V4 run or role loaded",
        "rows": rows, "synthetic_only": False}
