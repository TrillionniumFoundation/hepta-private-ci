"""Pre-qualification codec/oracle/deployment parity on historical validation."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

import torch

from ...v6.data import SourceCorpus, make_batch, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import read_bundle, write_bundle
from ...v6.plan_training import ControlledSnapshot, PLANS
from ...repair_20261026.joint.train import deploy
from .data import fresh_corpus, historical_corpus
from .oracle import original_oracle
from .protocol import PROTOCOL as P, write_json
from .run import reference_observer


def verify(assets, output):
    assets, output = Path(assets), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    historical = historical_corpus(assets)
    new = fresh_corpus(assets, historical)
    previous = {h for s in historical.splits.values() for h in s.pixel_hashes}
    if any(previous & set(s.pixel_hashes) for s in new.splits.values()):
        raise AssertionError("Fresh source exclusion failed")
    # Fresh identities may be inspected; no fresh model outputs are computed.
    small = SourceCorpus({"test": historical.splits["validation"]}, {"scope": "historical validation only"})
    saved = deepcopy(P)
    P.update(seeds=[17], test_pairs=2, conditions=["clean"])
    try:
        reward = reference_observer(assets, "reward")
        rows = original_oracle(assets, small, reward, output)
        original = ControlledSnapshot.load(assets / "ndu-runs/full-002/seed-17-terminal_entropic_ndu.pt")
        model, gate = original._base._model, original._gate
        before = parameter_hash(model), parameter_hash(gate)
        batch = make_batch(small, "test", 2, P["evaluation_seed"], corruption="clean", offset=0)
        rng = torch.Generator().manual_seed(17 * 100003)
        with torch.inference_mode():
            generated, choices = deploy(model, gate, batch.observation, torch.randn(2, model.hidden, generator=rng))
            registered = original.decode(original.encode(batch.observation, noise_seed=17 * 100003))
        if not torch.equal(generated.image_logits, registered.image_logits) or not torch.equal(generated.token_ids, registered.token_ids):
            raise AssertionError("Actual deployment differs from original registered wrapper")
        for index, row in enumerate(rows):
            paths = write_bundle(output / "deployed" / str(index), render_tokens(generated.token_ids[index]),
                                 generated.image_logits[index].sigmoid())
            _, _, hashes = read_bundle(paths)
            candidate = next(c for c in row["candidates"] if tuple(c["plan"]) == PLANS[int(choices[index])])
            if hashes["image"] != candidate["artifacts"]["image_sha256"] or hashes["text"] != candidate["artifacts"]["text_sha256"]:
                raise AssertionError("Original chosen-plan bytes differ from its oracle candidate")
            if candidate["audit"]["utility"] > row["utility"] + 1e-12:
                raise AssertionError("Oracle is not an upper bound")
        if before != (parameter_hash(model), parameter_hash(gate)):
            raise AssertionError("Read-only evaluation mutated original weights")
        result = {"passed": True, "source_scope": "historical validation", "new_test_outputs_computed": False,
                  "original_wrapper_bitwise_parity": True, "chosen_plan_codec_hash_parity": True,
                  "oracle_candidate_bundles": 32, "fresh_sources_outside_historical_corpus": True}
        write_json(output / "VERIFICATION.json", result)
        print(json.dumps(result))
    finally:
        P.clear()
        P.update(saved)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(args.assets, args.output)
