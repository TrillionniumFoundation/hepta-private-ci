"""Independent corruption controls for the unchanged inner restore and final guard."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import tempfile

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101 import execution as old
from ..support_retention_r16_20261101.compression import BlockLaw
from . import execution as new

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main():
    protocol = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    models = json.loads(gzip.decompress((ROOT / protocol["training_archive"]).read_bytes()))["calibration"]["models"]
    episode = make_episode(Law(), 2100992 * 10**9, "iid")
    rows = []
    with tempfile.TemporaryDirectory(prefix="hcsn-r21-independent-guard-") as temporary:
        for name, module in (("old", old), ("new", new)):
            for representation in ("full", "anchored"):
                cls = module.AnchoredPackedMemory if representation == "anchored" else module.BeliefMemory
                for corruption in ("returned_checkpoint_checksum", "restored_operation_counter"):
                    path = Path(temporary) / "state.json"
                    persist, descriptor, original_restore = module.persist, cls.__dict__["restore"], cls.restore
                    if corruption == "returned_checkpoint_checksum":
                        def damaged_persist(target, body):
                            saved = persist(target, body)
                            saved["memory"]["clock"] += .001
                            return saved
                        module.persist = damaged_persist
                    else:
                        def damaged_restore(cls_arg, law, payload):
                            restored = original_restore(law, payload)
                            restored.operations["observations"] += 1
                            return restored
                        cls.restore = classmethod(damaged_restore)
                    try:
                        try:
                            module.execute(BlockLaw.from_payload(models["hx"]["payload"]), episode, "r20",
                                           representation, path, KernelCache())
                        except (ValueError, RuntimeError) as error:
                            expected = "Owned state changed" if corruption == "restored_operation_counter" else "Checkpoint"
                            assert expected in str(error)
                            wire = path.read_bytes()
                            payload = json.loads(wire)
                            digest = payload.pop("sha256")
                            assert hashlib.sha256(canonical(payload)).hexdigest() == digest
                            rows.append(dict(version=name, representation=representation, corruption=corruption,
                                             rejected=str(error), wire_base64=base64.b64encode(wire).decode()))
                        else:
                            raise AssertionError("Changed restoration was accepted")
                    finally:
                        module.persist, cls.restore = persist, descriptor
    output = dict(passed=True, actual_guard_rejections=len(rows), cases=rows,
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  scope="Independent engineering injections only; exact current source classes and synchronous local persistence.")
    raw = canonical(output)
    (HERE / "INDEPENDENT_RESTORE_GUARDS.json.gz").write_bytes(gzip.compress(raw, mtime=0))
    print(json.dumps(dict(passed=True, actual_guard_rejections=len(rows), raw_sha256=hashlib.sha256(raw).hexdigest()), sort_keys=True))


if __name__ == "__main__":
    main()
