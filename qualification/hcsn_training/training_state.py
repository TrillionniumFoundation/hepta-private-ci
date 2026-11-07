"""Bind a coarse training block to its admitted clock and complete tensor state.

V2 requests carry the exact Rust clock DTO. Its canonical digest must match the
outer anchor in every already validated interval plan. The dispatcher must obtain
that anchor independently from its owner; a self-consistent request is not an
authorization credential. Saved candidate binding metadata is predecessor
provenance, not the newly admitted candidate's model identity.

The returned snapshot is detached only at this explicit completed-block boundary.
Every optimizer iteration and the final forward reuse it unchanged; tensors
inside an unfolded block remain in the shared autograd graph.
"""

import hashlib

import torch
from .joint_graph import integer, sha256, tensor_digest, time_profile_digest

_ZERO_DIGEST = "0"*64
_IDENTITY_FIELDS = {"profile_digest", "clock_epoch", "scope_digest", "model_digest",
                    "generation", "writer_epoch"}
_CLOCK_FIELDS = _IDENTITY_FIELDS | {"schema_version", "last_micros", "sequence",
                                    "state_digest", "predecessor_digest"}
_CANDIDATE_METADATA = {"optimizer", "binding", "last_end_micros"}


def state_digest(state):
    """Hash every cell slot with the native bridge's existing canonical names."""
    if (not isinstance(state, (tuple, list)) or not 1 <= len(state) <= 16
            or any(not isinstance(cell, (tuple, list)) or not cell
                   or any(not isinstance(value, torch.Tensor) for value in cell) for cell in state)):
        raise ValueError("complete nonempty logical cell tensor state required")
    return tensor_digest({f"cell_{i}_slot_{j}": value
                          for i, cell in enumerate(state) for j, value in enumerate(cell)})


def clock_checkpoint_digest(checkpoint):
    """Validate and hash Rust HcsnClockCheckpointV1's encoded DTO, not its JSON."""
    if (not isinstance(checkpoint, dict) or set(checkpoint) != _CLOCK_FIELDS
            or type(checkpoint["schema_version"]) is not int or checkpoint["schema_version"] != 1):
        raise ValueError("unknown Rust clock checkpoint schema/fields")
    digests = []
    for name in ("profile_digest", "clock_epoch", "scope_digest", "model_digest", "state_digest"):
        digests.append(bytes.fromhex(sha256(checkpoint[name])))
    predecessor = checkpoint["predecessor_digest"]
    if predecessor != _ZERO_DIGEST:
        sha256(predecessor)
    digests.append(bytes.fromhex(predecessor))
    values = (integer(checkpoint["generation"]), integer(checkpoint["writer_epoch"]),
              integer(checkpoint["last_micros"], 0), integer(checkpoint["sequence"], 0))
    if (values[-1] == 0) != (predecessor == _ZERO_DIGEST):
        raise ValueError("clock sequence and predecessor disagree")
    encoded = b"hepta.neuron.hcsn-clock-checkpoint.v1"+b"".join(digests)
    return hashlib.sha256(encoded+b"".join(value.to_bytes(8, "big") for value in values)).hexdigest()


def resolve_training_initialization(model, request, saved_state, saved_metadata, inputs):
    """Return an isolated initial snapshot after model/plan/resource admission.

    The caller has loaded the exact base checkpoint bytes and validated the
    complete A or B interval schedule. Both graph backends expose initial_state
    and validate_state. V1 remains model-only fresh training; it cannot resume or
    discard a candidate's stored state. V2 explicitly selects fresh or resume.
    """
    if not isinstance(request, dict) or not isinstance(saved_metadata, dict):
        raise ValueError("training request and checkpoint metadata required")
    version = request.get("schema_version")
    if type(version) is not int or version not in (1, 2):
        raise ValueError("unknown training initialization schema")
    carries_state = saved_state is not None or bool(_CANDIDATE_METADATA & saved_metadata.keys())
    if version == 1:
        if "initialization" in request or carries_state:
            raise ValueError("legacy training requires a model-only fresh checkpoint")
        state = model.initial_state(inputs)
    else:
        initialization = request.get("initialization")
        if (not isinstance(initialization, dict) or set(initialization) != {"mode", "clock_checkpoint"}
                or initialization["mode"] not in ("fresh", "resume")):
            raise ValueError("explicit fresh/resume initialization and Rust clock required")
        clock = initialization["clock_checkpoint"]
        anchor = clock_checkpoint_digest(clock)
        binding = request.get("binding")
        if not isinstance(binding, dict) or set(binding) != _IDENTITY_FIELDS:
            raise ValueError("complete training clock identity required")
        for name in ("generation", "writer_epoch"):
            integer(binding[name])
        for name in _IDENTITY_FIELDS - {"generation", "writer_epoch"}:
            sha256(binding[name])
        if (any(clock[name] != binding[name] for name in _IDENTITY_FIELDS)
                or clock["profile_digest"] != time_profile_digest(request["time_profile"])):
            raise ValueError("clock checkpoint differs from admitted training identity/profile")
        plans = request.get("intervals")
        if (not isinstance(plans, list) or not 1 <= len(plans) <= 256
                or any(not isinstance(plan, dict) or plan.get("checkpoint_before") != anchor
                       or plan.get("profile_digest") != clock["profile_digest"] for plan in plans)
                or integer(plans[0].get("start_micros"), 0) != clock["last_micros"]
                or clock["sequence"] == 2**64-1):
            raise ValueError("training intervals do not start from the admitted clock anchor")
        if initialization["mode"] == "fresh":
            if carries_state or clock["sequence"] != 0:
                raise ValueError("fresh training requires a model-only checkpoint and initial clock")
            state = model.initial_state(inputs)
        else:
            if (saved_state is None or not _CANDIDATE_METADATA <= saved_metadata.keys()
                    or integer(saved_metadata["last_end_micros"], 0) != clock["last_micros"]):
                raise ValueError("resume requires complete saved state at the admitted starting time")
            state = saved_state
    model.validate_state(state, inputs.shape[0], inputs.dtype, inputs.device)
    if version == 2 and state_digest(state) != clock["state_digest"]:
        raise ValueError("initial tensor state does not match the admitted clock state digest")
    return tuple(tuple(value.detach().clone() for value in cell) for cell in state)
