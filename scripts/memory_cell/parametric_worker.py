"""Fresh-process parameter-only reader: no facts, gold, retrieval or answer lexicon."""

import hashlib
import json
from pathlib import Path
import sys

import torch
from peft import get_peft_model_state_dict, set_peft_model_state_dict

from parametric_model import SourceMemoryCell, adapter_digest
from tensor_contract import strict_json

MAX_REQUEST_BYTES = 128 * 1024


def run(request):
    required = {
        "model",
        "snapshot",
        "manifest_sha256",
        "scope",
        "allowed_roots",
        "questions",
        "rank",
        "seed",
        "control",
    }
    if set(request) != required or request["control"] not in (
        "adapter",
        "base",
        "shuffled",
    ):
        raise ValueError("closed parameter-only request schema")
    if (
        not isinstance(request["allowed_roots"], list)
        or len(request["allowed_roots"]) > 128
        or not isinstance(request["questions"], list)
        or not 1 <= len(request["questions"]) <= 128
    ):
        raise ValueError("bounded roots and queries required")
    torch.set_num_threads(2)
    cell = SourceMemoryCell(
        Path(request["model"]), rank=request["rank"], seed=request["seed"]
    )
    cell.load(
        Path(request["snapshot"]),
        expected_manifest_sha256=request["manifest_sha256"],
        scope=request["scope"],
        allowed_roots=set(request["allowed_roots"]),
        revoked=set(),
    )
    admitted_adapter = adapter_digest(cell.reader.model)
    if request["control"] == "shuffled":
        # Explicit negative control, never accepted by a snapshot owner.
        state = get_peft_model_state_dict(cell.reader.model)
        rng = torch.Generator().manual_seed(91473)
        state = {
            name: value.flatten()[torch.randperm(value.numel(), generator=rng)].reshape(
                value.shape
            )
            for name, value in state.items()
        }
        set_peft_model_state_dict(cell.reader.model, state)
        cell.reader.model.requires_grad_(False)
        # This process only emits a deliberately corrupted negative-control read;
        # it cannot save, train, or activate the perturbed state as a candidate.
        cell._expected_adapter = adapter_digest(cell.reader.model)
    actual = hashlib.sha256()
    for name, value in sorted(get_peft_model_state_dict(cell.reader.model).items()):
        actual.update(name.encode())
        actual.update(value.detach().cpu().contiguous().numpy().tobytes())
    rows = cell.generate(request["questions"], enabled=request["control"] != "base")
    effective_state = dict(
        base_identity=cell.reader.identity,
        adapter_enabled=request["control"] != "base",
        active_adapter_sha256=adapter_digest(cell.reader.model)
        if request["control"] != "base"
        else None,
    )
    return dict(
        schema="hepta.parametric-memory.read-journal.v1",
        control=request["control"],
        request_sha256=hashlib.sha256(
            json.dumps(request, sort_keys=True).encode()
        ).hexdigest(),
        actual_adapter_tensor_sha256=actual.hexdigest(),
        rows=rows,
        admitted_adapter_state_sha256=admitted_adapter,
        consumed_adapter_state_sha256=adapter_digest(cell.reader.model),
        effective_state_sha256=hashlib.sha256(
            json.dumps(effective_state, sort_keys=True).encode()
        ).hexdigest(),
        fact_input=False,
        retrieval_input=False,
        answer_lexicon_input=False,
        production_accepted=False,
    )


if __name__ == "__main__":
    payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if not 0 < len(payload) <= MAX_REQUEST_BYTES:
        raise ValueError("request byte bound")
    print(json.dumps(run(strict_json(payload)), sort_keys=True))
