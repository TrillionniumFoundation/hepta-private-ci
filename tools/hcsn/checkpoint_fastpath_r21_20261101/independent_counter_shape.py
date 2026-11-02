"""Record the inherited mutable-counter boundary of the alias-isolation proof."""
import gzip
import hashlib
import json
from pathlib import Path

from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..support_retention_r16_20261101.compression import AnchoredPackedMemory, BlockLaw, PackedBeliefMemory

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main():
    protocol = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    models = json.loads(gzip.decompress((ROOT / protocol["training_archive"]).read_bytes()))["calibration"]["models"]
    records = []
    for name, cls, projection in [("full", BeliefMemory, "full"), ("block", PackedBeliefMemory, "block"),
                                  ("anchored", AnchoredPackedMemory, "block")]:
        law = BlockLaw.from_payload(models["hx"]["payload"])
        actor = cls(law, [0, 1, 2, 3], projection)
        payload = actor.checkpoint()
        payload.pop("sha256")
        payload["operations"]["writes"] = [4]
        payload["sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
        restored = cls.restore(law, payload)
        snapshot = restored.checkpoint()
        before = list(restored.operations["writes"])
        snapshot["operations"]["writes"].append(99)
        after = restored.operations["writes"]
        assert after == [4, 99]
        records.append(dict(memory=name, malformed_counter_checkpoint_accepted=True,
                            before=before, after=after, snapshot_aliases_actor=True))
    output = dict(observed=True, cases=records,
                  classification="Inherited malformed-state validation gap in frozen R15/R16 restore, not introduced by snapshot caching.",
                  proof_boundary="Normal internally generated counters are integer scalars and isolated. All-accepted-input alias isolation or structural immutability is not claimed.",
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE / "INDEPENDENT_COUNTER_SHAPE_LIMIT.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps(output,sort_keys=True))


if __name__ == "__main__":
    main()
