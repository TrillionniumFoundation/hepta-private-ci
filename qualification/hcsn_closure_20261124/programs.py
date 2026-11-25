"""Bounded rule compilation and supervised relation heads on frozen HCSNs.

The relation dictionary is common, explicit prior knowledge. No claim is made
that its construction learns a representation or replaces backbone training.
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn

from qualification.hcsn_smallnet_20261124.data import TaskBatch
from qualification.hcsn_smallnet_20261124.editing import tensor_digest
from qualification.hcsn_smallnet_20261124.transfer_suite import (
    ReadoutBasisView, permute_model_state, permute_population_state)
from qualification.hcsn_smallnet_20261124.train import runtime_identity
from .provenance import sources as parent_sources


METHODS = ("KEEP", "BP", "ANALYTIC", "STRICT_WSP", "HYBRID")
RULES = ("AND", "OR", "XOR")


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def default_protocol():
    return {"schema": "hcsn-known-relation-program-v1", "rules": list(RULES),
            "sources": {"train": list(range(20000, 20012)),
                        "dev": list(range(21000, 21004)), "test": list(range(22000, 22016))},
            "per_source": 16, "length": 12, "chunk": 16, "ridge": 1e-4,
            "max_closures": 96, "update_cpu_seconds": 10.0, "gradient_tolerance": 1e-8,
            "transfer_pairs": 16, "transfer_atol": 3e-5, "transfer_rtol": 3e-5,
            "parent_ids": [f"n{n}-s{s}" for n in (8, 32, 64) for s in (17011, 27011, 37011)],
            "selection": "fixed final finite candidate; no development selection",
            "primary": "XOR ground-truth accuracy difference from KEEP; descriptive across three seeds",
            "discovery_cost": None, "discovery_cost_reason": "agent-authored rule family; not instrumented",
            "source_sha256": digest(__file__), "parent_source_hashes": parent_sources(),
            "transfer_source_hashes": {name: digest(Path(__file__).parent.parent/"hcsn_smallnet_20261124"/name)
                                       for name in ("editing.py", "transfer_suite.py")},
            "runtime": runtime_identity()}


def validate_protocol(p):
    if p["source_sha256"] != digest(__file__) or tuple(p["rules"]) != RULES:
        raise ValueError("changed executable or unsupported relation rules")
    if p["parent_source_hashes"] != parent_sources() or p["runtime"] != runtime_identity():
        raise ValueError("changed parent executable closure or runtime")
    if p["transfer_source_hashes"] != {name: digest(Path(__file__).parent.parent/"hcsn_smallnet_20261124"/name)
                                     for name in ("editing.py", "transfer_suite.py")}:
        raise ValueError("changed transfer/weight identity implementation")
    sources = [s for v in p["sources"].values() for s in v]
    if len(sources) != len(set(sources)) or p["per_source"] < 1 or p["length"] < 10:
        raise ValueError("source overlap or invalid sample geometry")
    if p["ridge"] <= 0 or not 1 <= p["max_closures"] <= 96:
        raise ValueError("invalid bounded optimization protocol")


@dataclass(frozen=True)
class PairBatch:
    a: TaskBatch
    b: TaskBatch

    @property
    def labels(self):
        return torch.stack((self.a.y & self.b.y, self.a.y | self.b.y,
                            self.a.y ^ self.b.y), -1)

    def digest(self):
        return identity({"a": self.a.digest(), "b": self.b.digest()})

    def select(self, indices):
        return PairBatch(self.a.select(indices), self.b.select(indices))


def make_pair_data(split, p):
    """Two separate RNG streams per source, with true sign(A+B) labels."""
    if split not in p["sources"]:
        raise ValueError("undeclared pair split")
    streams = []
    for lane in (0, 1):
        xs, ys, groups, margins, late_steps, ids = [], [], [], [], [], []
        for source in p["sources"][split]:
            rng = np.random.default_rng(np.random.SeedSequence([20261125, source, lane]))
            n, length = p["per_source"], p["length"]
            a, b = rng.uniform(-1, 1, (2, n))
            gain, noise, correlation = rng.uniform(.85, 1.15), rng.uniform(.08, .35), rng.uniform(-.5, .7)
            late = rng.integers(4, 7, n)
            x = np.zeros((length, n, 6))
            x[0, :, 0], x[0, :, 2] = gain*a, 1
            x[late, np.arange(n), 1], x[late, np.arange(n), 3] = gain*b, 1
            x[:, :, 4] = np.arange(length)[:, None]/(length-1)
            for tick in range(length):
                x[tick, :, 5] = noise*rng.normal(size=n)
                if tick:
                    x[tick, :, 5] += correlation*x[tick-1, :, 5]
            xs.append(x); ys.append((a+b > 0).astype(np.int64)); groups.extend([source]*n)
            margins.append(rng.uniform(.45, .85, n)); late_steps.append(late)
            ids.extend(f"relation-{split}:{source}:lane{lane}:{i}" for i in range(n))
        streams.append(TaskBatch(torch.tensor(np.concatenate(xs, 1), dtype=torch.float32),
            torch.tensor(np.concatenate(ys)), torch.tensor(groups),
            torch.tensor(np.concatenate(margins), dtype=torch.float32),
            torch.tensor(np.concatenate(late_steps)), tuple(ids)))
    return PairBatch(*streams)


def projection(readout_state):
    if set(readout_state) != {"weight", "bias"}:
        raise ValueError("explicit two-class affine readout required")
    w, b = (readout_state[k].detach().cpu().clone() for k in ("weight", "bias"))
    if w.ndim != 2 or w.shape[0] != 2 or b.shape != (2,) or not bool(torch.isfinite(w).all() and torch.isfinite(b).all()):
        raise ValueError("finite binary projection required")
    return {"projection_weight": w, "projection_bias": b}


def strict_program(readout_state, *, rules=RULES):
    """Weight-only compiler. No labels, activations, model, search or BP input.

    For nonzero component margins: AND=min(a,b), OR=max(a,b), and
    XOR=|a-b|-|a+b|. Exact zero component margins require separate reporting.
    """
    if tuple(rules) != RULES:
        raise ValueError("unknown rule; no automatic supervised fallback")
    state = projection(readout_state)
    state.update({"readout.weight": torch.tensor([[.5, .5, -.5, 0],
        [.5, .5, .5, 0], [0, 0, 1, -1]], dtype=torch.float64),
        "readout.bias": torch.zeros(3, dtype=torch.float64)})
    return state


class RelationHead(nn.Module):
    def __init__(self, readout_state):
        super().__init__()
        for name, tensor in projection(readout_state).items():
            self.register_buffer(name, tensor)
        self.readout = nn.Linear(4, 3, dtype=torch.float64)
        with torch.no_grad():
            self.readout.weight.zero_(); self.readout.weight[:, 0] = 1; self.readout.bias.zero_()

    def dictionary(self, a, b):
        logits = [nn.functional.linear(v.to(self.projection_weight), self.projection_weight,
                                        self.projection_bias).double() for v in (a, b)]
        x, y = (v[:, 1]-v[:, 0] for v in logits)
        return torch.stack((x, y, (x-y).abs(), (x+y).abs()), -1)

    def forward(self, a, b):
        return self.readout(self.dictionary(a, b))


def query_logits(scores, original_logits, query):
    """Observable query 0 preserves original logits exactly; 1..3 add rules."""
    if query.dtype != torch.long or query.shape != scores.shape[:1] or bool(((query < 0) | (query > 3)).any()):
        raise ValueError("one integer query in 0..3 per pair required")
    value = scores.gather(1, (query-1).clamp_min(0)[:, None])[:, 0].to(original_logits)
    novel = torch.stack((-value/2, value/2), -1)
    return torch.where((query == 0)[:, None], original_logits, novel)


@contextmanager
def phase(rows, name):
    wall, cpu, status = time.perf_counter(), time.process_time(), "failed"
    try:
        yield
        status = "completed"
    finally:
        rows.append({"phase": name, "status": status, "wall_seconds": time.perf_counter()-wall,
                     "cpu_seconds": time.process_time()-cpu})


@torch.no_grad()
def extract(parent, pairs, *, chunk, order=None, initial_parent=None):
    features, logits = [], []
    for batch in (pairs.a, pairs.b):
        fs, ls = [], []
        for start in range(0, len(batch.y), chunk):
            part = batch.select(torch.arange(start, min(start+chunk, len(batch.y))))
            initializer = parent if initial_parent is None else initial_parent
            state = initializer.initial_state(len(part.y), initial_margin=part.initial_margin[:, None])
            if order is not None:
                state = permute_population_state(state, order, parent.config.neurons)
            logit, feature, _ = parent(part.x, state=state, return_features=True)
            fs.append(feature[-1].cpu()); ls.append(logit.cpu())
        features.append(torch.cat(fs)); logits.append(torch.cat(ls, 1))
    return {"a": features[0], "b": features[1], "logits_a": logits[0], "logits_b": logits[1]}


def objective(head, design, target, ridge):
    return (head.readout(design)-target).square().mean()+ridge*head.readout.weight.square().sum()


def fit_head(head, design, labels, method, p, *, receipt=None):
    """Supervised methods alone receive labels. Bias is never regularized."""
    if method not in ("BP", "ANALYTIC", "HYBRID"):
        raise ValueError("supervised fitting method required")
    target = 2*labels.double()-1
    receipt = {} if receipt is None else receipt
    receipt.update(labels_read=int(labels.numel()), closures=0, solves=0)
    if method == "ANALYTIC":
        x = torch.cat((design, torch.ones(len(design), 1, dtype=design.dtype)), -1)
        penalty = torch.diag(design.new_tensor([p["ridge"]]*4+[0]))
        hessian = x.T@x/target.numel()+penalty
        rhs = x.T@target/target.numel()
        receipt["condition_number"] = float(torch.linalg.cond(hessian))
        receipt["solves"] = 1; answer = torch.linalg.solve(hessian, rhs)
        with torch.no_grad():
            head.readout.weight.copy_(answer[:4].T); head.readout.bias.copy_(answer[4])
    else:
        optimizer = torch.optim.LBFGS(head.readout.parameters(), lr=1, max_iter=1, max_eval=1,
                                      history_size=20, tolerance_grad=0, tolerance_change=0, line_search_fn=None)
        started = time.process_time(); receipt["stop"] = "closure_limit"
        for _ in range(p["max_closures"]):
            if time.process_time()-started >= p["update_cpu_seconds"]:
                receipt["stop"] = "cpu_limit"; break
            def closure():
                optimizer.zero_grad(set_to_none=True)
                receipt["closures"] += 1
                loss = objective(head, design, target, p["ridge"]); loss.backward()
                receipt["gradient_inf"] = max(float(t.grad.abs().max()) for t in head.readout.parameters())
                if not bool(torch.isfinite(loss)) or not np.isfinite(receipt["gradient_inf"]):
                    raise FloatingPointError("nonfinite supervised objective/gradient")
                return loss
            optimizer.step(closure)
            if receipt["gradient_inf"] <= p["gradient_tolerance"]:
                receipt["stop"] = "gradient_converged"; break
    if not all(bool(torch.isfinite(v).all()) for v in head.state_dict().values()):
        raise FloatingPointError("nonfinite fitted head")
    receipt["objective"] = float(objective(head, design, target, p["ridge"]).detach())
    return receipt


@torch.no_grad()
def metrics(head, cache, pairs):
    design = head.dictionary(cache["a"], cache["b"]); scores = head.readout(design)
    labels, predicted = pairs.labels, (scores > 0).long()
    component = design[:, :2] > 0
    logical = torch.stack((component[:, 0] & component[:, 1], component[:, 0] | component[:, 1],
                           component[:, 0] ^ component[:, 1]), -1)
    nonzero = (design[:, :2] != 0).all(-1)
    probabilities = scores.sigmoid()
    zero_query = torch.zeros(len(scores), dtype=torch.long)
    preserved = torch.equal(query_logits(scores, cache["logits_a"][-1], zero_query), cache["logits_a"][-1])
    rows = {}
    for i, rule in enumerate(RULES):
        rows[rule] = {"accuracy": float((predicted[:, i] == labels[:, i]).double().mean()),
                     "brier": float(2*(probabilities[:, i]-labels[:, i]).square().mean()),
                     "cross_entropy": float(nn.functional.binary_cross_entropy_with_logits(scores[:, i], labels[:, i].double())),
                     "source_accuracy": {str(s): float((predicted[pairs.a.source == s, i] == labels[pairs.a.source == s, i]).double().mean()) for s in pairs.a.source.unique().tolist()}}
    return {"rules": rows, "examples": len(scores), "old_logits_exact": preserved,
            "component_zero_margin_pairs": int((~nonzero).sum()),
            "nonzero_logical_disagreements": int((predicted[nonzero] != logical[nonzero]).sum()),
            "parent_accuracy_a": float((cache["logits_a"][-1].argmax(-1) == pairs.a.y).double().mean()),
            "parent_accuracy_b": float((cache["logits_b"][-1].argmax(-1) == pairs.b.y).double().mean())}, scores


@torch.no_grad()
def transfer_controls(parent, pairs, p):
    """Real forwards; each coordinate view is one parent's control, not a seed."""
    original = extract(parent, pairs, chunk=p["chunk"])
    fresh = RelationHead(parent.readout.state_dict()); fresh.load_state_dict(strict_program(parent.readout.state_dict()))
    expected = fresh(original["a"], original["b"])
    n, half = parent.config.neurons, parent.config.neurons//2
    order = torch.cat((torch.arange(half-1, -1, -1), torch.arange(n-1, half-1, -1)))
    permuted = deepcopy(parent); permuted.load_state_dict(permute_model_state(parent.state_dict(), order, n))
    signs = torch.where(torch.arange(parent.readout.in_features) % 2 == 0, -1., 1.)
    subjects = (("population_permutation", permuted, order),
                ("readout_signed_basis", ReadoutBasisView(parent, signs), None))
    records = {}
    for name, subject, state_order in subjects:
        values = extract(subject, pairs, chunk=p["chunk"], order=state_order, initial_parent=parent)
        head = RelationHead(subject.readout.state_dict()); head.load_state_dict(strict_program(subject.readout.state_dict()))
        scores = head(values["a"], values["b"])
        copied = fresh(values["a"], values["b"])
        records[name] = {"regenerated_program_sha256": tensor_digest(head.state_dict()),
            "equivalent": bool(torch.allclose(scores, expected, atol=p["transfer_atol"], rtol=p["transfer_rtol"])),
            "max_score_error": float((scores-expected).abs().max()),
            "prediction_disagreements": int(((scores > 0) != (expected > 0)).sum()),
            "copied_old_program_equivalent": bool(torch.allclose(copied, expected, atol=p["transfer_atol"], rtol=p["transfer_rtol"])),
            "copied_max_score_error": float((copied-expected).abs().max()),
            "old_parent_logits_equivalent": bool(torch.allclose(values["logits_a"], original["logits_a"], atol=p["transfer_atol"], rtol=p["transfer_rtol"]))}
    return {"independent_parent_count": 1, "views_are_independent_samples": False,
            "physical_sign_symmetry_claimed": False, "pairs": len(pairs.a.y), "controls": records}


def prepare(parent, parent_identity, output, p):
    torch.set_num_threads(1); validate_protocol(p); parent.eval()
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter(), time.process_time(); phases, methods = [], {}
    parent_digest = tensor_digest(parent.state_dict())
    if parent_identity["parent_id"] not in p["parent_ids"]:
        raise ValueError("undeclared parent")
    create_json(output/"STARTED.json", {"parent_identity": parent_identity, "protocol_sha256": identity(p)})
    with phase(phases, "data_generation"):
        training, development = make_pair_data("train", p), make_pair_data("dev", p)
    with phase(phases, "shared_feature_extraction"):
        train_cache = extract(parent, training, chunk=p["chunk"])
        dev_cache = extract(parent, development, chunk=p["chunk"])
    with phase(phases, "shared_projection_dictionary"):
        incumbent = RelationHead(parent.readout.state_dict())
        design = incumbent.dictionary(train_cache["a"], train_cache["b"])
    with phase(phases, "shared_feature_evidence_write"):
        for split, cache, pairs in (("TRAIN", train_cache, training), ("DEV", dev_cache, development)):
            np.savez_compressed(output/(split+"_FEATURES.npz"),
                **{k: v.numpy() for k, v in cache.items()}, labels=pairs.labels.numpy(), source=pairs.a.source.numpy())
    for method in METHODS:
        costs, status, error = [], "completed", None
        head = deepcopy(incumbent); details = {"labels_read": 0, "closures": 0, "solves": 0}
        try:
            with phase(costs, "program_generation_or_initialization"):
                if method in ("STRICT_WSP", "HYBRID"):
                    head.load_state_dict(strict_program(parent.readout.state_dict()))
            if method in ("BP", "ANALYTIC", "HYBRID"):
                with phase(costs, "supervised_update_including_optimizer_setup"):
                    fit_head(head, design, training.labels, method, p, receipt=details)
        except Exception as exc:
            status, error, head = "failed_kept_incumbent", repr(exc), deepcopy(incumbent)
        with phase(costs, "development_validation"):
            development_metrics, _ = metrics(head, dev_cache, development)
        with phase(costs, "candidate_write_reload_validate"):
            artifact = {"method": method, "protocol_sha256": identity(p), "parent_digest": parent_digest,
                        "parent_identity": parent_identity, "model_state": head.state_dict()}
            path = output/(method+".pt")
            with path.open("xb") as stream:
                torch.save(artifact, stream)
            loaded = torch.load(path, weights_only=True, map_location="cpu")
            if tensor_digest(loaded["model_state"]) != tensor_digest(head.state_dict()):
                raise ValueError("head serialization changed tensors")
        methods[method] = {"status": status, "error": error, "optimization": details,
                          "development": development_metrics, "cost": costs, "checkpoint_sha256": digest(path)}
    with phase(phases, "transfer_program_regeneration_and_real_forwards"):
        transfers = transfer_controls(parent, development.select(torch.arange(min(p["transfer_pairs"], len(development.a.y)))), p)
    if tensor_digest(parent.state_dict()) != parent_digest:
        raise ValueError("protected parent changed")
    result = {"protocol_sha256": identity(p), "parent_digest": parent_digest,
              "parent_identity": parent_identity, "train_digest": training.digest(), "dev_digest": development.digest(),
              "methods": methods, "transfers": transfers, "shared_cost": phases,
              "body_cpu_seconds": time.process_time()-cpu, "body_wall_seconds": time.perf_counter()-wall,
              "cost_scope": "body includes all preceding phases; final result/seal writes and caller parent load excluded; caller must record full worker",
              "discovery_cost": p["discovery_cost"], "test_constructed": False}
    create_json(output/"PREPARED.json", result)
    create_json(output/"SEAL.json", {"protocol_sha256": identity(p), "parent_digest": parent_digest,
        "parent_identity": parent_identity, "files": {name: digest(output/name) for name in ("STARTED.json", "PREPARED.json", "TRAIN_FEATURES.npz", "DEV_FEATURES.npz", *(m+".pt" for m in METHODS))}})
    return result


def validate_prepared(path, p):
    path = Path(path); seal = json.loads((path/"SEAL.json").read_text())
    if seal["protocol_sha256"] != identity(p):
        raise ValueError("candidate protocol mismatch")
    expected = {"STARTED.json", "PREPARED.json", "TRAIN_FEATURES.npz", "DEV_FEATURES.npz", *(m+".pt" for m in METHODS)}
    if set(seal["files"]) != expected or any(digest(path/name) != sha for name, sha in seal["files"].items()):
        raise ValueError("changed candidate roster or bytes")
    result = json.loads((path/"PREPARED.json").read_text()); original = None
    for method in METHODS:
        value = torch.load(path/(method+".pt"), weights_only=True, map_location="cpu")
        for key in ("protocol_sha256", "parent_digest", "parent_identity"):
            if value[key] != seal[key] or result[key] != seal[key]:
                raise ValueError("candidate identity mismatch")
        if value["method"] != method:
            raise ValueError("candidate method mismatch")
        if result["methods"][method]["checkpoint_sha256"] != seal["files"][method+".pt"]:
            raise ValueError("candidate result/checkpoint hash mismatch")
        state = value["model_state"]
        if set(state) != {"projection_weight", "projection_bias", "readout.weight", "readout.bias"}:
            raise ValueError("candidate schema mismatch")
        if state["projection_weight"].ndim != 2 or state["projection_weight"].shape[0] != 2 or state["projection_bias"].shape != (2,) or state["readout.weight"].shape != (3, 4) or state["readout.bias"].shape != (3,) or not all(bool(torch.isfinite(v).all()) for v in state.values()):
            raise ValueError("invalid candidate tensors")
        frozen = {k: v for k, v in state.items() if k.startswith("projection_")}
        if original is None:
            original = tensor_digest(frozen)
        elif tensor_digest(frozen) != original:
            raise ValueError("supervised candidate changed protected projection")
    return seal


def seal_all(paths, output, p):
    validate_protocol(p)
    entries = {}
    for path in paths:
        seal = validate_prepared(path, p); parent_id = seal["parent_identity"]["parent_id"]
        if parent_id in entries:
            raise ValueError("duplicate parent")
        entries[parent_id] = {"directory": str(Path(path).resolve()), "seal_sha256": digest(Path(path)/"SEAL.json")}
    if set(entries) != set(p["parent_ids"]):
        raise ValueError("all declared independent parents must seal before pair test")
    create_json(output, {"protocol_sha256": identity(p), "parents": entries})


def final_test(parent, output, p, global_seal):
    torch.set_num_threads(1); validate_protocol(p); parent.eval()
    wall, cpu = time.perf_counter(), time.process_time(); phases = []
    output = Path(output)
    with phase(phases, "global_candidate_preflight"):
        global_value = json.loads(Path(global_seal).read_text())
        if global_value["protocol_sha256"] != identity(p) or set(global_value["parents"]) != set(p["parent_ids"]):
            raise ValueError("global program seal mismatch")
        for parent_id, value in global_value["parents"].items():
            if digest(Path(value["directory"])/"SEAL.json") != value["seal_sha256"]:
                raise ValueError("global candidate seal changed")
            checked = validate_prepared(value["directory"], p)
            if checked["parent_identity"]["parent_id"] != parent_id:
                raise ValueError("global parent identity mismatch")
        own = validate_prepared(output, p)
        if Path(global_value["parents"][own["parent_identity"]["parent_id"]]["directory"]).resolve() != output.resolve():
            raise ValueError("own output is outside global sealed roster")
        if tensor_digest(parent.state_dict()) != own["parent_digest"]:
            raise ValueError("parent checkpoint changed")
    create_json(output/"FINAL_CLAIM.json", {"global_seal_sha256": digest(global_seal), "protocol_sha256": identity(p)})
    with phase(phases, "test_generation_and_shared_feature_extraction"):
        test = make_pair_data("test", p); cache = extract(parent, test, chunk=p["chunk"])
    results, raw = {}, {"labels": test.labels.numpy(), "component_labels_a": test.a.y.numpy(),
        "component_labels_b": test.b.y.numpy(), "source": test.a.source.numpy(), "features_a": cache["a"].numpy(),
        "features_b": cache["b"].numpy(), "parent_logits_a": cache["logits_a"].numpy(), "parent_logits_b": cache["logits_b"].numpy()}
    for method in METHODS:
        costs = []
        with phase(costs, "candidate_reload_evaluation"):
            value = torch.load(output/(method+".pt"), weights_only=True, map_location="cpu")
            head = RelationHead(parent.readout.state_dict()); head.load_state_dict(value["model_state"])
            result, scores = metrics(head, cache, test); raw[method+"_scores"] = scores.numpy()
        prepared = json.loads((output/"PREPARED.json").read_text())["methods"][method]
        results[method] = {"metrics": result, "cost": costs, "status": prepared["status"],
                           "optimization": prepared["optimization"]}
    with phase(phases, "prediction_evidence_write"):
        np.savez_compressed(output/"FINAL_PREDICTIONS.npz", **raw)
    result = {"protocol_sha256": identity(p), "parent_identity": own["parent_identity"],
              "test_digest": test.digest(), "test_ids_a": test.a.ids, "test_ids_b": test.b.ids,
              "methods": results, "shared_cost": phases, "body_cpu_seconds": time.process_time()-cpu,
              "body_wall_seconds": time.perf_counter()-wall, "raw_sha256": digest(output/"FINAL_PREDICTIONS.npz"),
              "cost_scope": "method cost plus common phases; caller import/load/shutdown and result write excluded; no unmeasured discovery speedup"}
    create_json(output/"FINAL_RESULTS.json", result)
    return result
