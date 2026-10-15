"""V8 endpoint residuals over an unchanged, already trained V6 BridgeReader.

Slots read only projected public fact tokens. The broken control changes value
payload correspondence, not scores, using a fixed public-content permutation.
"""
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F

from bridge_reader import BridgeReader, build_reader, reader_identity
from token_reader import _attention, _normalize


ARMS = ("bridge", "endpoint", "broken", "local")


def public_value_permutation(facts, token_mask):
    """Cycle valid facts in raw-token SHA256 order; never rank learned features.

    Equal hashes use the input fact index as a tie break, so no unconditional
    permutation-equivariance claim is made for hash ties. Padding is excluded.
    Zero/one valid facts have identity indices; cross-fact masks suppress output.
    """
    if (facts.ndim != 4 or token_mask.shape != facts.shape[:-1] or token_mask.dtype != torch.bool
            or facts.device.type != "cpu" or token_mask.device.type != "cpu" or facts.dtype != torch.float32):
        raise ValueError("aligned public CPU fact tokens and boolean mask required")
    batch, count = facts.shape[:2]
    indices = torch.arange(count, dtype=torch.long).expand(batch, count).clone()
    for row in range(batch):
        ordered = []
        for fact in range(count):
            value = facts[row, fact][token_mask[row, fact]].detach().contiguous()
            if not len(value):
                continue
            digest = hashlib.sha256(str((str(value.dtype), tuple(value.shape))).encode())
            digest.update(value.numpy().tobytes())
            ordered.append((digest.digest(), fact))
        order = [fact for _, fact in sorted(ordered)]
        if len(order) > 1:
            for position, fact in enumerate(order):
                indices[row, fact] = order[(position + 1) % len(order)]
    return indices


class EndpointBranch(nn.Module):
    """Two learned endpoints and a shared directed value-to-key entity metric."""

    def __init__(self, hidden_dim, *, broken=False):
        super().__init__()
        self.input = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.match = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.slot_queries = nn.Parameter(torch.empty(2, hidden_dim))
        nn.init.normal_(self.slot_queries, std=1 / math.sqrt(hidden_dim))
        nn.init.zeros_(self.output.weight)
        self.broken = broken

    def endpoints(self, evidence, token_mask):
        """Evidence is post-projection LayerNorm, with no question/candidate path."""
        tokens = F.gelu(self.input(evidence))
        scores = torch.einsum("bfth,sh->bfst", tokens, self.slot_queries) / math.sqrt(tokens.shape[-1])
        weights = _attention(scores, token_mask.unsqueeze(-2).expand_as(scores))
        slots = torch.einsum("bfst,bfth->bfsh", weights, tokens)
        return slots[:, :, 0], slots[:, :, 1]

    def forward(self, evidence, token_mask, value_permutation):
        batch, count, _, hidden = evidence.shape
        if batch * count * count > 64_000_000:
            raise ValueError("endpoint cross-fact tensor limit exceeded; reduce batch size")
        if (value_permutation.shape != (batch, count) or value_permutation.dtype != torch.long
                or value_permutation.device.type != "cpu"):
            raise ValueError("aligned public value permutation required")
        keys, values = self.endpoints(evidence, token_mask)
        query = F.normalize(self.match(values), dim=-1, eps=1e-8)
        key = F.normalize(self.match(keys), dim=-1, eps=1e-8)
        scores = torch.matmul(query, key.transpose(-1, -2)) * math.sqrt(hidden)
        present = token_mask.any(-1)
        cross_fact = present.unsqueeze(-1) & present.unsqueeze(-2)
        cross_fact = cross_fact & ~torch.eye(count, dtype=torch.bool).unsqueeze(0)
        weights = _attention(scores, cross_fact)
        # The real arm executes the same public ranking and gather as the control.
        identity = torch.arange(count, dtype=torch.long).expand(batch, count)
        selected = value_permutation if self.broken else identity
        payload = torch.gather(values, 1, selected.unsqueeze(-1).expand(batch, count, hidden))
        message = self.output(torch.matmul(weights, self.value(payload)))
        return message * present.unsqueeze(-1).to(message.dtype)


class EndpointReader(BridgeReader):
    """Retain the old FactBridge; add the independent endpoint path once in prepare."""

    def __init__(self, input_dim=384, hidden_dim=32, max_hops=8, *, arm="endpoint",
                 residual_seed=0, endpoint_seed=0):
        if arm not in ("endpoint", "broken"):
            raise ValueError("endpoint or broken branch required")
        super().__init__(input_dim, hidden_dim, max_hops=max_hops, residual_seed=residual_seed)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(endpoint_seed)
            self.endpoint_branch = EndpointBranch(hidden_dim, broken=arm == "broken")
        self.endpoint_arm = arm

    def prepare(self, facts, question, candidate, fact_mask, question_mask, candidate_mask):
        prepared = super().prepare(facts, question, candidate, fact_mask, question_mask, candidate_mask)
        # This second small projection is intentional and must be actually charged.
        # It does not reuse the question/candidate-conditioned relation tensors.
        evidence = F.layer_norm(self.project(_normalize(facts)), (self.hidden_dim,))
        permutation = public_value_permutation(facts, fact_mask)
        message = self.endpoint_branch(evidence, fact_mask, permutation)
        relations = prepared["relations"] + message.unsqueeze(-2) * fact_mask.unsqueeze(-1).to(message.dtype)
        return {**prepared, "relations": relations, "token_keys": self.token_key(relations)}


class EndpointLocal(nn.Module):
    """Four square matrices and affine LayerNorm, confined to one Head hidden row."""

    def __init__(self, hidden_dim):
        super().__init__()
        self.input = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.hidden1 = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.hidden2 = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.norm = nn.LayerNorm(hidden_dim)
        nn.init.zeros_(self.output.weight)

    def forward(self, value):
        hidden = F.gelu(self.input(self.norm(value)))
        hidden = F.gelu(self.hidden1(hidden))
        return self.output(F.gelu(self.hidden2(hidden)))


class EndpointLocalHead(nn.Sequential):
    """Preserve old Head tensor names while adding the candidate-local control."""

    def __init__(self, original, hidden_dim):
        super().__init__(*original)
        self.endpoint_local = EndpointLocal(hidden_dim)

    def forward(self, value):
        hidden = self[1](self[0](value))
        return self[2](hidden + self.endpoint_local(hidden))


class EndpointLocalReader(BridgeReader):
    def __init__(self, input_dim=384, hidden_dim=32, max_hops=8, *, residual_seed=0, endpoint_seed=0):
        super().__init__(input_dim, hidden_dim, max_hops=max_hops, residual_seed=residual_seed)
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(endpoint_seed)
            self.head = EndpointLocalHead(self.head, hidden_dim)
        self.endpoint_arm = "local"


def build_endpoint_reader(arm, seed):
    """Construct the four registered 384→32 variants without consuming caller RNG."""
    if arm not in ARMS or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("registered endpoint arm and bounded integer seed required")
    if arm == "bridge":
        model = build_reader("bridge", seed)
        model.endpoint_arm = arm
        return model
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        kwargs = dict(residual_seed=seed ^ 0x6B12, endpoint_seed=seed ^ 0xE873)
        model = (EndpointLocalReader(**kwargs) if arm == "local"
                 else EndpointReader(arm=arm, **kwargs))
    return model


def load_bridge_warmup(bridge_model, arm, *, seed):
    """Copy every frozen V6 tensor exactly, preserving the original model object."""
    identity = reader_identity(bridge_model)
    if (identity["arm"] != "bridge" or bridge_model.training
            or any(p.requires_grad for p in bridge_model.parameters())
            or (bridge_model.input_dim, bridge_model.hidden_dim, bridge_model.max_hops) != (384, 32, 8)):
        raise ValueError("registered frozen V6 bridge warmup required")
    model = build_endpoint_reader(arm, seed)
    source = bridge_model.state_dict()
    if any(value.dtype != torch.float32 or value.device.type != "cpu" or not torch.isfinite(value).all()
           for value in source.values()):
        raise ValueError("finite CPU FP32 bridge tensors required for byte-preserving copy")
    result = model.load_state_dict(source, strict=False)
    expected = set(model.state_dict()) - set(source)
    if result.unexpected_keys or set(result.missing_keys) != expected:
        raise ValueError("old bridge state keys do not match the endpoint common core")
    if any(not torch.equal(model.state_dict()[name], value) for name, value in source.items()):
        raise ValueError("an existing bridge tensor changed during initialization")
    model.training_source_groups = tuple(getattr(bridge_model, "training_source_groups", ()))
    return model.eval().requires_grad_(False)


def endpoint_identity(model):
    """Validate exact architecture/state shapes separately from tensor digests."""
    arm = getattr(model, "endpoint_arm", "bridge" if type(model) is BridgeReader else None)
    expected_class = {"bridge": BridgeReader, "endpoint": EndpointReader,
                      "broken": EndpointReader, "local": EndpointLocalReader}.get(arm)
    if type(model) is not expected_class or model.interaction != "token" or model.reader_arm != "bridge":
        raise ValueError("registered endpoint class and matching arm identity required")
    if arm in ("endpoint", "broken") and model.endpoint_branch.broken != (arm == "broken"):
        raise ValueError("endpoint payload rule differs from declared arm")
    hidden, inputs = model.hidden_dim, model.input_dim
    shapes = {"project.weight": (hidden, inputs), "query.weight": (hidden, hidden * 4), "query.bias": (hidden,),
        "relation.weight": (hidden, hidden * 8), "relation.bias": (hidden,), "token_score.weight": (1, hidden),
        "token_key.weight": (hidden, hidden), "fact_score.weight": (1, hidden), "fact_key.weight": (hidden, hidden),
        "state_query.weight": (hidden, hidden * 2), "proposal.weight": (hidden, hidden * 3 + 4),
        "proposal.bias": (hidden,), "update_gate.weight": (hidden, hidden * 3 + 4), "update_gate.bias": (hidden,),
        "head.0.weight": (hidden, hidden * 3 + 1), "head.0.bias": (hidden,), "head.2.weight": (2, hidden),
        "head.2.bias": (2,)}
    shapes.update({"fact_bridge." + name + ".weight": (hidden, hidden)
                   for name in ("query", "key", "value", "output")})
    if arm in ("endpoint", "broken"):
        shapes.update({"endpoint_branch." + name + ".weight": (hidden, hidden)
                       for name in ("input", "match", "value", "output")})
        shapes["endpoint_branch.slot_queries"] = (2, hidden)
    elif arm == "local":
        shapes.update({"head.endpoint_local." + name + ".weight": (hidden, hidden)
                       for name in ("input", "hidden1", "hidden2", "output")})
        shapes.update({"head.endpoint_local.norm." + name: (hidden,) for name in ("weight", "bias")})
    if {name: tuple(value.shape) for name, value in model.state_dict().items()} != shapes:
        raise ValueError("registered endpoint state tensor names and shapes required")
    common = inputs * hidden + 29 * hidden ** 2 + 18 * hidden + 2
    added = 0 if arm == "bridge" else 4 * hidden ** 2 + 2 * hidden
    if sum(p.numel() for p in model.parameters()) != common + added:
        raise ValueError("registered endpoint parameter count required")
    return dict(schema="hepta.endpoint-reader.v8", arm=arm, input_dim=inputs, hidden_dim=hidden,
        max_hops=model.max_hops, max_facts=model.max_facts, max_tokens=model.max_tokens,
        parameter_count=common + added, common_parameter_count=common, added_parameter_count=added,
        old_fact_bridge_retained=True, public_feature_arguments=6, state_transition="TokenReader-v4",
        residual_location={"bridge": "none", "endpoint": "parallel_endpoint_prepare",
                           "broken": "parallel_endpoint_prepare", "local": "local_head_hidden"}[arm],
        endpoint_input="LayerNorm_h(project(LayerNorm_input(raw_fact_tokens)))" if arm in ("endpoint", "broken") else None,
        shared_entity_match_projection=arm in ("endpoint", "broken"), self_key_index_edges=False,
        broken_self_payload_possible=arm == "broken", fact_axis_unit="caller_supplied_fact_or_token_chunk",
        slot_semantics="learned_latent_endpoints_not_certified_entity_parser",
        broken_payload_only=arm == "broken", public_value_order="raw_valid_token_SHA256_then_input_index",
        hash_tie_limit="index_tie_break_no_unconditional_equivariance_claim",
        zero_or_one_valid_fact_message="zero_for_endpoint_and_broken",
        pure_binding_causal_identification=False, same_parameter_count_is_same_compute=False)
