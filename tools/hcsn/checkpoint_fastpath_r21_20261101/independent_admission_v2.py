"""Independent typed admission, alias isolation and actual caller-route controls."""
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import time

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory
from ..addressed_decision_r15_20261101.world import make_episode
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..support_retention_r16_20261101.compression import AnchoredPackedMemory, BlockLaw, PackedBeliefMemory
from .admission import restore_owned
from . import execution

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signed(value):
    body = dict(value); body.pop("sha256", None)
    return dict(body, sha256=hashlib.sha256(canonical(body)).hexdigest())


def main():
    started = time.process_time()
    protocol = json.loads((HERE / "ADMISSION_V2_PROTOCOL.json").read_text())
    development = json.loads((HERE / "DEVELOPMENT_PROTOCOL.json").read_text())
    models = json.loads(gzip.decompress((ROOT / development["training_archive"]).read_bytes()))["calibration"]["models"]
    episode = make_episode(Law(), protocol["namespace"] * 10**9, "ood")
    rows = []
    configurations = [("full", BeliefMemory, "full"), ("block", PackedBeliefMemory, "block"),
                      ("anchored", AnchoredPackedMemory, "block")]
    with tempfile.TemporaryDirectory(prefix="hcsn-r21-admission-v2-") as temporary:
        for representation, cls, projection in configurations:
            law = BlockLaw.from_payload(models["hx"]["payload"])
            original = cls(law, [0, 1, 2, 3], projection)
            base = original.checkpoint()
            restored = restore_owned(cls, law, copy.deepcopy(base), expected_projection=projection)
            assert restored.checkpoint() == base
            external = copy.deepcopy(base)
            restored = restore_owned(cls, law, external, expected_projection=projection)
            field = "beliefs" if representation == "full" else "packed"
            external[field][0][0] += .01; external["operations"]["writes"] += 3
            if "anchor_times" in external: external["anchor_times"][0] += .02
            assert restored.checkpoint() == base
            snapshot = restored.checkpoint(); before = canonical(snapshot)
            restored.__dict__[field][0, 0] += .01; restored.operations["writes"] += 3
            if "anchor_times" in restored.__dict__: restored.anchor_times[0] += .02
            assert canonical(snapshot) == before
            actor_before = canonical(restored.checkpoint())
            snapshot[field][0][0] += .02; snapshot["operations"]["writes"] += 5
            assert canonical(restored.checkpoint()) == actor_before
            rows.append(dict(case="normal_detachment", representation=representation, passed=True))

            def rejected(payload, expected, name, delegations, *, expected_projection=projection):
                calls = []
                class Spy:
                    @classmethod
                    def restore(cls_arg, actual_law, actual_payload):
                        calls.append(1)
                        return cls.restore(actual_law, actual_payload)
                try:
                    restore_owned(Spy, law, payload, expected_projection=expected_projection)
                except ValueError as error:
                    assert expected in str(error) and len(calls) == delegations
                    rows.append(dict(case=name, representation=representation, rejected=str(error),
                                     inherited_restore_calls=len(calls), operations_repr=repr(payload.get("operations")), passed=True))
                else:
                    raise AssertionError(name)

            bad_values = {"bool":True, "list":[4], "dict":{"n":4}, "float":4.0,
                          "nan":float("nan"), "negative":-1}
            for name, value in bad_values.items():
                payload = copy.deepcopy(base); payload["operations"]["writes"] = value
                if name != "nan": payload = signed(payload)
                rejected(payload, "counter schema", name, 0)
            for name in ("missing_key", "extra_key", "list_map", "null_map"):
                payload = copy.deepcopy(base)
                if name == "missing_key": payload["operations"].pop("writes")
                elif name == "extra_key": payload["operations"]["other"] = 0
                elif name == "list_map": payload["operations"] = []
                else: payload["operations"] = None
                rejected(signed(payload), "counter schema", name, 0)
            payload = copy.deepcopy(base); payload["schema"] = "unknown"
            rejected(signed(payload), "counter schema", "unknown_schema", 0)
            if representation == "full":
                for name, key, value in [("projection_list", "projection", []), ("projection_mismatch", "projection", "factorized"),
                                         ("method_list", "method", []), ("method_unknown", "method", "unknown")]:
                    payload = copy.deepcopy(base); payload[key] = value
                    rejected(signed(payload), "propagation metadata", name, 0)
            else:
                rejected(copy.deepcopy(base), "block projection", "packed_projection_mismatch", 0, expected_projection="full")
            payload = copy.deepcopy(base); payload["sha256"] = "0"*64
            rejected(payload, "Checkpoint", "inner_checksum", 1)
            payload = copy.deepcopy(base); payload[field][0][0] = -1
            rejected(signed(payload), "", "negative_probability", 1)
            payload = copy.deepcopy(base); payload["clock"] = -.01
            rejected(signed(payload), "", "negative_clock", 1)

            for case in ("post_restore_guard", "postpersist_preflight", "cold_resume_preflight"):
                path = Path(temporary)/(representation+"-"+case+".json")
                original_persist, descriptor, original_restore = execution.persist, cls.__dict__["restore"], cls.restore
                calls = []
                if case == "cold_resume_preflight":
                    execution.execute(law, episode, "r20", representation, path, KernelCache(), stop_after_query=0)
                    payload = json.loads(path.read_bytes())
                    payload["memory"]["operations"]["writes"] = [4]
                    payload["memory"] = signed(payload["memory"])
                    path.write_bytes(canonical(signed(payload)))
                if case == "postpersist_preflight":
                    def bad_return(target, body):
                        saved = original_persist(target, body)
                        saved["memory"]["operations"]["writes"] = [4]
                        saved["memory"] = signed(saved["memory"])
                        return signed(saved)
                    execution.persist = bad_return
                def intercepted_restore(cls_arg, actual_law, payload):
                    calls.append(1)
                    result = original_restore(actual_law, payload)
                    if case == "post_restore_guard": result.operations["observations"] += 1
                    return result
                cls.restore = classmethod(intercepted_restore)
                output = path.with_name(path.stem+"-resume.json") if case == "cold_resume_preflight" else path
                try:
                    try:
                        execution.execute(law, episode, "r20", representation, output, KernelCache(),
                                          resume_path=path if case == "cold_resume_preflight" else None)
                    except (ValueError, RuntimeError) as error:
                        if case == "post_restore_guard":
                            assert "Owned state changed" in str(error) and len(calls) == 1
                        else:
                            assert "counter schema" in str(error) and calls == []
                        if case == "cold_resume_preflight": assert not output.exists()
                        rows.append(dict(case=case, representation=representation, rejected=str(error), passed=True,
                                         inherited_restore_calls=len(calls), wire_base64=base64.b64encode(path.read_bytes()).decode()))
                    else:
                        raise AssertionError(case)
                finally:
                    cls.restore, execution.persist = descriptor, original_persist
    assert len(rows) == protocol["expected_cases"]
    result = dict(passed=True, cases=len(rows), records=rows, parent_cpu_seconds=time.process_time()-started,
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  classification="Independent bounded correctness engineering after source freeze; no timing/adoption inference.")
    raw = canonical(result)
    (HERE/"INDEPENDENT_ADMISSION_V2.json.gz").write_bytes(gzip.compress(raw,mtime=0))
    print(json.dumps(dict(passed=True,cases=len(rows),raw_sha256=hashlib.sha256(raw).hexdigest()),sort_keys=True))


if __name__ == "__main__":
    main()
