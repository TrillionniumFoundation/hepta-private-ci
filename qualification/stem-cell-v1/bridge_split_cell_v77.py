"""V7.7 experimental frozen-V6-Bridge shared trunk with split gated task Heads.

This is research-only. The routing evidence is supplied by an upstream source
owner; this module does not authenticate an issuer or authorize production use.
No pretrained Granite Encoder weights are instantiated by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import random
import re
import threading
import time
import weakref

import torch
from torch import nn
from torch.nn import functional as F

SCHEMA = "hepta.bridge.cell-split.v77.shadow.v1"
ROUTE_SCHEMA = "hepta.bridge.cell-split.route.v1"
OLD_TASK = "binding-v4"
NEW_TASK = "natural-multirc"
PARAMETERS_PER_CELL = 1700
ORIGINAL_BRIDGE_PARAMETERS = 42562
# Cross-Cell synchronization MUST be per shared physical Reader, not per Cell.
_LOCKS = weakref.WeakKeyDictionary()
_LOCKS_GUARD = threading.Lock()

def _shared_reader_lock(parent):
    with _LOCKS_GUARD:
        if parent not in _LOCKS:
            _LOCKS[parent] = threading.RLock()
        return _LOCKS[parent]
HEX = re.compile(r"[0-9a-f]{64}\Z")


def require(condition, description):
    if not condition:
        raise ValueError(description)


def _hex(value):
    require(type(value) is str and HEX.fullmatch(value) is not None,
            "lowercase 64-character SHA256 identity required")
    return value


def digest_parameters(model):
    """The original V6 training_parameter_sha256 algorithm; bounded CPU FP32."""
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        require(tensor.dtype == torch.float32 and tensor.device.type == "cpu"
                and bool(torch.isfinite(tensor).all()), "finite original CPU FP32 tensor required")
        digest.update(name.encode())
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(tensor.detach().contiguous().numpy().tobytes())
    return digest.hexdigest()


def feature_digest(features):
    require(type(features) is tuple and len(features) == 6,
            "exact six original frozen Reader feature arguments required")
    result = hashlib.sha256()
    first = features[0]
    require(type(first) is torch.Tensor and first.ndim == 4 and
            1 <= first.shape[0] <= 32 and first.shape[-1] == 384,
            "bounded 384D original frozen Reader input required")
    for i, item in enumerate(features):
        require(type(item) is torch.Tensor and item.device.type == "cpu"
                and item.shape[0] == first.shape[0] and item.dtype ==
                (torch.bool if i >= 3 else torch.float32),
                "typed and aligned original Reader tensor required")
        require(item.numel() <= 32 * 32 * 128 * 384,
                "feature tensor allocation bound exceeded")
        require(i >= 3 or bool(torch.isfinite(item).all()),
                "nonfinite Reader feature input denied")
        result.update(str(i).encode())
        result.update(str(tuple(item.shape)).encode())
        result.update(str(item.dtype).encode())
        result.update(item.detach().contiguous().numpy().tobytes())
    require(features[1].ndim == features[2].ndim == 3 and
            features[3].shape == features[0].shape[:-1] and
            features[4].shape == features[1].shape[:-1] and
            features[5].shape == features[2].shape[:-1],
            "exact feature / mask geometry required")
    return result.hexdigest()


@dataclass(frozen=True)
class RouteEvidence:
    """Untrusted evidence identity, not a signature or task authorization."""
    task_family: str
    case_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    feature_sha256: str
    frozen_model_sha256: str
    encoder_sha256: str
    preprocess_sha256: str
    principal_sha256: str
    generation: int = 1
    source_scope: str = "train"
    schema: str = ROUTE_SCHEMA
    production_authorized: bool = False

    def validate(self, *, size, model_sha, features_sha):
        require(type(self) is RouteEvidence and self.schema == ROUTE_SCHEMA
                and self.task_family in (OLD_TASK, NEW_TASK)
                and self.source_scope in ("train", "train_internal_tune", "synthetic_unseen_source")
                and self.production_authorized is False
                and type(self.generation) is int and 1 <= self.generation <= 2**32,
                "registered research-only task route/scope/generation required")
        for value in (self.feature_sha256, self.frozen_model_sha256,
                      self.encoder_sha256, self.preprocess_sha256,
                      self.principal_sha256):
            _hex(value)
        require(self.feature_sha256 == features_sha and
                self.frozen_model_sha256 == model_sha,
                "routed feature input or original frozen model digest differs")
        require(type(self.case_ids) is tuple and len(self.case_ids) == size and
                len(set(self.case_ids)) == size and all(type(x) is str and
                0 < len(x.encode("utf-8")) <= 512 for x in self.case_ids),
                "nonempty unique bounded route case identities required")
        require(type(self.source_hashes) is tuple and len(self.source_hashes) == size,
                "one original source identity per routed case required")
        for source in self.source_hashes:
            _hex(source)
        return self


class GatedNewHead(nn.Module):
    """Exactly 1,700 FP32 parameters; no fresh copy of old V6 Reader.

    New-task logits = frozen old logits + sigmoid(gate) * correction.
    Correction starts exactly zero. Old route bypasses this Head entirely.
    """

    def __init__(self, seed):
        super().__init__()
        require(type(seed) is int and 0 <= seed < 2**32,
                "bounded deterministic candidate Cell seed required")
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(seed)
            self.input = nn.Linear(97, 16)
            self.gate = nn.Linear(97, 1)
            self.output = nn.Linear(16, 2)
            nn.init.zeros_(self.output.weight)
            nn.init.zeros_(self.output.bias)
        require(sum(p.numel() for p in self.parameters()) == PARAMETERS_PER_CELL,
                "exact lightweight gated Cell Head geometry required")

    def forward(self, frozen_state, old_logits):
        require(type(frozen_state) is torch.Tensor and
                frozen_state.dtype == torch.float32 and
                frozen_state.device.type == "cpu" and
                frozen_state.ndim == 2 and frozen_state.shape[1] == 97 and
                type(old_logits) is torch.Tensor and
                old_logits.shape == (frozen_state.shape[0], 2) and
                old_logits.dtype == torch.float32 and
                old_logits.device.type == "cpu" and
                bool(torch.isfinite(frozen_state).all()) and
                bool(torch.isfinite(old_logits).all()),
                "bounded finite original V6 frozen Reader features required")
        update = self.output(F.gelu(self.input(frozen_state)))
        mix = torch.sigmoid(self.gate(frozen_state))
        return old_logits + mix * update


class SplitBridgeCell(nn.Module):
    """Multiple instances may hold the SAME physical frozen parent Reader.

    The Parent object is frozen in place but never copied. Training optimizer
    must be constructed from `cell.new_head.parameters()`, NEVER `parameters()`.
    """
    def __init__(self, parent, *, expected_parent_sha256, new_head_seed):
        super().__init__()
        from bridge_reader import BridgeReader
        require(type(parent) is BridgeReader and
                parent.reader_arm == "bridge" and
                parent.input_dim == 384 and parent.hidden_dim == 32 and
                sum(p.numel() for p in parent.parameters()) == ORIGINAL_BRIDGE_PARAMETERS,
                "exact original registered V6 BridgeReader required")
        digest = digest_parameters(parent)
        require(digest == _hex(expected_parent_sha256),
                "original V6 frozen model checkpoint digest mismatch")
        self.parent = parent  # deliberate single physical shared reference
        self.parent.eval().requires_grad_(False)
        self.new_head = GatedNewHead(new_head_seed)
        self.original_sha256 = digest
        self.candidate_fitted = False
        self._forward_lock = _shared_reader_lock(parent)  # all Cells share same hook lock
        self.parent_forward_calls = 0
        self.parent_tensor_bytes = sum(p.numel()*p.element_size() for p in parent.parameters())
        self.head_tensor_bytes = sum(p.numel()*p.element_size() for p in self.new_head.parameters())

    def train(self, mode=True):
        super().train(mode)
        # PyTorch module recursion must never set the shared frozen original to train mode.
        self.parent.eval()
        return self

    def check_frozen(self):
        require(self.parent.training is False and
                all(not p.requires_grad and p.grad is None for p in self.parent.parameters())
                and digest_parameters(self.parent) == self.original_sha256,
                "shared old Cell parameters, gradients or frozen execution mutated")

    def extract(self, six_features, *, steps=3):
        """Obtain 97D pre-Head state via scoped forward hook on original V6.

        The logits are from the original `parent.forward`, unchanged. No new
        features/labels are passed into the parent beyond its six public tensors.
        """
        require(type(steps) is int and 1 <= steps <= 8,
                "bounded original causal Reader hops required")
        self.check_frozen()
        feature_digest(six_features)
        latest = []
        def capture(_layer, inputs):
            require(len(inputs) == 1 and inputs[0].ndim == 2 and
                    inputs[0].shape == (six_features[0].shape[0], 97),
                    "original last-hop pre-Head state geometry changed")
            latest[:] = [inputs[0].detach().clone()]
        with self._forward_lock:
            hook = self.parent.head[0].register_forward_pre_hook(capture)
            try:
                with torch.no_grad():
                    original_logits = self.parent(*six_features, steps=steps)
            finally:
                hook.remove()
        require(len(latest) == 1 and original_logits.shape ==
                (six_features[0].shape[0], 2) and
                bool(torch.isfinite(original_logits).all()),
                "original frozen Reader logit/head extraction failed")
        self.parent_forward_calls += 1
        return latest[0], original_logits.detach().clone()

    def route(self, six_features, evidence: RouteEvidence, *, steps=3):
        identity = feature_digest(six_features)
        evidence.validate(size=six_features[0].shape[0],
                          model_sha=self.original_sha256, features_sha=identity)
        state, original = self.extract(six_features, steps=steps)
        if evidence.task_family == OLD_TASK:
            # EXACT historical old route: no reference to new Head, no gate arithmetic.
            return original
        return self.new_head(state, original)


@dataclass(frozen=True)
class FrozenNewTaskCache:
    """Already-computed public 97D Reader features; never includes labels."""
    hidden: torch.Tensor
    original_logits: torch.Tensor
    case_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    frozen_model_sha256: str
    public_features_sha256: str
    source_scope: str = "train"
    encoded_reader_calls: int = 0
    input_batch_sha256s: tuple[str, ...] = ()

    def validate(self):
        require(type(self.hidden) is torch.Tensor and
                self.hidden.dtype == torch.float32 and self.hidden.device.type == "cpu"
                and self.hidden.ndim == 2 and self.hidden.shape[1] == 97 and
                1 <= self.hidden.shape[0] <= 8192 and
                type(self.original_logits) is torch.Tensor and
                self.original_logits.dtype == torch.float32 and
                self.original_logits.device.type == "cpu" and
                self.original_logits.shape == (self.hidden.shape[0],2) and
                not self.hidden.requires_grad and not self.original_logits.requires_grad and
                bool(torch.isfinite(self.hidden).all()) and
                bool(torch.isfinite(self.original_logits).all()),
                "complete bounded label-free frozen Reader cache required")
        require(self.source_scope == "train" and
                type(self.case_ids) is tuple and
                len(self.case_ids) == len(set(self.case_ids)) == len(self.hidden) and
                all(type(x) is str and 0<len(x.encode())<=512 for x in self.case_ids)
                and type(self.source_hashes) is tuple and
                len(self.source_hashes) == len(self.hidden),
                "train-only unique source case cache required")
        require(type(self.encoded_reader_calls) is int and self.encoded_reader_calls >= 0,
                "bounded actual frozen Reader precomputation call count required")
        require(type(self.input_batch_sha256s) is tuple and len(self.input_batch_sha256s)>0,
                "original input feature batch byte digests required")
        for x in (self.frozen_model_sha256,self.public_features_sha256,
                  *self.source_hashes,*self.input_batch_sha256s):
            _hex(x)
        require(self.public_features_sha256 == _sealed_cache_sha(
                self.frozen_model_sha256,self.case_ids,self.source_hashes,
                self.input_batch_sha256s,self.hidden,self.original_logits),
                "cached 97D Reader hidden/logit tensor bytes no longer match sealed identity")
        return self


def _sealed_cache_sha(parent_sha,case_ids,source_hashes,input_hashes,hidden,original_logits):
    """Bind actual cached tensor bytes, not merely the original row roster."""
    digest=hashlib.sha256()
    digest.update(json.dumps(dict(parent=parent_sha,ids=list(case_ids),
        source_hashes=list(source_hashes),input_sha256=list(input_hashes)),
        sort_keys=True,separators=(",", ":")).encode())
    for tag,tensor in (("hidden",hidden),("original_logits",original_logits)):
        digest.update(tag.encode())
        digest.update(str(tuple(tensor.shape)).encode())
        digest.update(str(tensor.dtype).encode())
        digest.update(tensor.detach().contiguous().numpy().tobytes())
    return digest.hexdigest()


def collect_new_task_cache(cell, batches, *, forbidden_old_sources=()):
    """Real frozen V6 Reader extraction, bounded label-free new-task features.

    Each batch is `(six public feature tensors, RouteEvidence)`. Source/route
    digests must be provided by a separate upstream source owner. Do not train
    on the V6 binding cohort or on validation/future-test case identities.
    """
    require(type(cell) is SplitBridgeCell and type(batches) in (tuple, list)
            and 1 <= len(batches) <= 1024,
            "bounded real original Reader feature batch schedule required")
    denied=set(forbidden_old_sources)
    for source in denied:
        _hex(source)
    hiddens, baselines, ids, groups, source_bytes = [], [], [], [], []
    before=cell.parent_forward_calls
    for pair in batches:
        require(type(pair) is tuple and len(pair) == 2,
                "registered feature batch plus route identity required")
        public, binding=pair
        require(type(binding) is RouteEvidence and binding.task_family==NEW_TASK and
                binding.source_scope=="train" and binding.source_hashes and
                not set(binding.source_hashes).intersection(denied),
                "new-task TRAIN-only source disjoint from old Binding sources required")
        digest=feature_digest(public)
        binding.validate(size=public[0].shape[0],model_sha=cell.original_sha256,
                         features_sha=digest)
        latent, old_logits=cell.extract(public)
        hiddens.append(latent)
        baselines.append(old_logits)
        ids.extend(binding.case_ids)
        groups.extend(binding.source_hashes)
        source_bytes.append(digest)
    require(len(ids)==len(set(ids)) and len(ids)<=8192,
            "unique bounded new-task case identities required across batches")
    hidden=torch.cat(hiddens)
    original_logits=torch.cat(baselines)
    roster_sha=_sealed_cache_sha(cell.original_sha256,tuple(ids),tuple(groups),
                                 tuple(source_bytes),hidden,original_logits)
    result=FrozenNewTaskCache(hidden,original_logits,tuple(ids),
           tuple(groups),cell.original_sha256,roster_sha,
           encoded_reader_calls=cell.parent_forward_calls-before,
           input_batch_sha256s=tuple(source_bytes))
    return result.validate()


def _size_bytes(tensors):
    return sum(x.numel()*x.element_size() for x in tensors)


def fit_new_task_head(cell, cache, labels, *, updates=150, batch_size=16,
                      seed=41, learning_rate=0.01, max_train_cpu_ns=60_000_000_000):
    """Train ONLY the new 1,700-param Head on cached public original features.

    Labels enter only this training method, never parent Reader or route.
    No validation/holdout tuning or fresh/production task promotion is implied.
    """
    before_wall, before_cpu = time.perf_counter_ns(), time.process_time_ns()
    require(type(cell) is SplitBridgeCell and cell.candidate_fitted is False,
            "untrained registered Cell candidate required")
    cache.validate()
    cell.check_frozen()
    require(cache.frozen_model_sha256 == cell.original_sha256,
            "cached public Reader inputs not bound to actual frozen parent")
    require(type(labels) is torch.Tensor and labels.shape ==
            (cache.hidden.shape[0],) and labels.dtype == torch.long and
            labels.device.type == "cpu" and not labels.requires_grad and
            bool(((labels == 0) | (labels == 1)).all()),
            "aligned binary train-only labels required")
    require(type(updates) is int and 1 <= updates <= 5000 and
            type(batch_size) is int and 1 <= batch_size <= len(labels) and
            type(seed) is int and 0 <= seed < 2**32 and
            type(learning_rate) is float and 0 < learning_rate <= 0.1 and
            type(max_train_cpu_ns) is int and max_train_cpu_ns > 0,
            "bounded fixed training budget required")
    cell.new_head.train()
    optimizer = torch.optim.Adam(cell.new_head.parameters(),
                                 lr=learning_rate, foreach=False)
    params = list(cell.new_head.parameters())
    require(len(params) == 6 and sum(p.numel() for p in params)==PARAMETERS_PER_CELL and
            not any(id(p) in {id(v) for v in cell.parent.parameters()} for p in params),
            "strictly disjoint 1,700-parameter optimizer ownership required")
    schedule = random.Random(f"hepta-v77/{seed}")
    initial = digest_parameters(cell.parent)
    accepted = 0
    last_loss = None
    for logical in range(updates):
        if time.process_time_ns()-before_cpu >= max_train_cpu_ns:
            raise RuntimeError("fixed-budget candidate fit exceeded measured CPU budget")
        selected = schedule.sample(range(len(labels)), batch_size)
        idx = torch.tensor(selected, dtype=torch.long)
        optimizer.zero_grad(set_to_none=True)
        logits = cell.new_head(cache.hidden[idx], cache.original_logits[idx])
        loss = F.cross_entropy(logits, labels[idx])
        require(bool(torch.isfinite(loss)), "nonfinite new-task training loss")
        loss.backward()
        require(all(p.grad is not None and bool(torch.isfinite(p.grad).all())
                    for p in params), "all six new Cell Head parameters must receive finite gradients")
        optimizer.step()
        require(all(bool(torch.isfinite(p).all()) for p in params),
                "nonfinite trained new Cell Head candidate")
        accepted += 1
        last_loss = float(loss.detach().item())
    cell.check_frozen()
    require(digest_parameters(cell.parent)==initial,
            "original old Bridge weights mutated during new Head training")
    opt_bytes=_size_bytes(s for state in optimizer.state.values()
                          for s in state.values() if isinstance(s,torch.Tensor))
    cell.new_head.eval().requires_grad_(False)
    cell.candidate_fitted = True
    final_logits = cell.new_head(cache.hidden,cache.original_logits)
    require(bool(torch.isfinite(final_logits).all()),
            "finite candidate train-only inference required")
    with torch.no_grad():
        baseline_correct = int((cache.original_logits.argmax(-1) == labels).sum().item())
        trained_correct = int((final_logits.argmax(-1) == labels).sum().item())
    return dict(schema=SCHEMA, status="trained_candidate_only",
                source_role="new_task_train_only",
                parent_sha256=cell.original_sha256,
                train_row_count=len(labels),
                unique_source_groups=len(set(cache.source_hashes)),
                train_source_roster_sha256=hashlib.sha256(json.dumps(
                    sorted(set(cache.source_hashes)),separators=(",",":")).encode()).hexdigest(),
                cache_public_sha256=cache.public_features_sha256,
                new_head_sha256=digest_parameters(cell.new_head),
                parent_parameter_count=ORIGINAL_BRIDGE_PARAMETERS,
                new_head_parameter_count=PARAMETERS_PER_CELL,
                new_head_parameter_bytes=cell.head_tensor_bytes,
                shared_parent_parameter_bytes=cell.parent_tensor_bytes,
                label_count=len(labels),
                train_only_before_correct=baseline_correct,
                train_only_after_correct=trained_correct,
                train_only_last_batch_cross_entropy=last_loss,
                logical_optimizer_updates=updates, accepted_optimizer_updates=accepted,
                optimizer_tensor_bytes=opt_bytes,
                feature_cache_bytes=_size_bytes((cache.hidden,cache.original_logits)),
                actual_frozen_reader_calls_to_build_cache=cache.encoded_reader_calls,
                optimizer_seed=seed, batch_size=batch_size, learning_rate=learning_rate,
                original_trunk_training_updates=0,
                original_trunk_gradients_created=False,
                original_old_route_exactly_unchanged=True,
                repeated_encoder_forwards_during_head_training=0,
                reused_encoder_and_reader_feature_work_not_free=True,
                training_cpu_ns=time.process_time_ns()-before_cpu,
                training_wall_ns=time.perf_counter_ns()-before_wall,
                source_disjoint_future_verified=False,
                old_task_semantic_retention_verified=False,
                pretrained_granite_executed_here=False,
                equal_total_lifecycle_compute_verified=False,
                task_route_issuer_authenticated=False,
                NDU_policy_admitted=False, cell_split_production_authorized=False,
                model_selected=False, production_authorized=False)


def physical_weight_budget(cells):
    """Storage of ONE shared V6 parent and N disjoint 1,700-param Heads.
    No activations, optimizer, Python objects, decode towers or caches included.
    """
    require(type(cells) is int and 1 <= cells <= 4096,
            "bounded experimental physical head cohort size required")
    shared=ORIGINAL_BRIDGE_PARAMETERS*4
    per_head=PARAMETERS_PER_CELL*4
    return dict(cells=cells, shared_reader_bytes=shared,
                each_head_bytes=per_head,
                physical_parameter_bytes=shared+cells*per_head,
                dense_replica_baseline_bytes=cells*shared,
                strictly_weight_only=True,
                pretrained_encoder_not_included=True,
                train_optimizer_cache_activations_not_included=True)
