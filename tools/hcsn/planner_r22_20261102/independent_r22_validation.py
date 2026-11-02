"""Independent deterministic boundary, ownership and unchanged-I/O contract audit."""
import argparse
import ast
import copy
import gzip
import hashlib
import inspect
import json
from pathlib import Path
import time

import numpy as np

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.planner import BeliefMemory as OldFull
from ..checkpoint_fastpath_r21_20261101 import execution as old_execution
from ..checkpoint_fastpath_r21_20261101.admission import restore_owned
from ..support_retention_r16_20261101 import compression as old
from . import execution as new_execution
from . import memory as new

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def reseal(payload):
    payload = copy.deepcopy(payload)
    payload.pop("sha256", None)
    try:
        payload["sha256"] = sha(canonical(payload))
    except (ValueError, TypeError):
        # Such inputs are rejected by the identical inherited canonical encoder.
        payload["sha256"] = "unencodable-negative-control"
    return payload


def outcome(operation):
    try:
        return "accepted", operation()
    except (ValueError, TypeError, OverflowError, FloatingPointError, IndexError, KeyError) as error:
        return type(error).__name__, None


def arrays(width):
    cases = []
    for tolerance in (1e-11, 2e-11):
        for sign in (-1., 1.):
            middle = 1. + sign*tolerance
            for index, value in enumerate((np.nextafter(middle, -np.inf), middle,
                                           np.nextafter(middle, np.inf))):
                row = np.zeros(width); row[0] = value
                cases.append((f"mass_{tolerance}_{sign}_{index}", row))
    for name, value in (("negative_limit_below", -np.nextafter(1e-13, np.inf)),
                        ("negative_limit_equal", -1e-13),
                        ("negative_limit_above", -np.nextafter(1e-13, 0.)),
                        ("negative_subnormal", -np.nextafter(0., 1.)),
                        ("negative_zero", -0.), ("nan", np.nan),
                        ("positive_inf", np.inf), ("negative_inf", -np.inf)):
        row = np.zeros(width); row[0], row[1] = 1.-value, value
        cases.append((name, row))
    cases += [("all_zero", np.zeros(width)), ("sum_overflow", np.full(width, 1e308)),
              ("ordinary_uniform", np.full(width, 1./width))]
    for dtype in (np.float32, np.float64, np.int64, np.bool_):
        row = np.zeros(width, dtype=dtype); row[0] = 1
        cases.append(("dtype_"+np.dtype(dtype).name, row))
    for name, dtype in (("numeric_string", str), ("numeric_object", object)):
        row = np.zeros(width); row[0] = 1.
        cases.append((name, row.astype(dtype)))
    row = np.zeros(width); row[0] = 1.
    cases.extend((("scalar", np.array(1.)), ("wrong_width", row[:-1]),
                  ("empty_last_axis", np.zeros((2, 0))),
                  ("empty_batch", np.zeros((0, width))),
                  ("empty_middle", np.zeros((2, 0, width)))))
    return cases


def function_ast(function):
    import textwrap
    return ast.parse(textwrap.dedent(inspect.getsource(function))).body[0]


class ReplaceMassPredicate(ast.NodeTransformer):
    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "normalized_rows":
            return ast.copy_location(ast.Constant(value="unchanged_mass_predicate"), node)
        if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "np" and node.func.attr == "allclose"
                and node.args and isinstance(node.args[0], ast.Call)
                and isinstance(node.args[0].func, ast.Attribute) and node.args[0].func.attr == "sum"):
            return ast.copy_location(ast.Constant(value="unchanged_mass_predicate"), node)
        return self.generic_visit(node)


def run():
    rows, static = [], []
    started = time.process_time()
    manifest_path = HERE/"SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    publication = json.loads((HERE/"PUBLICATION.json").read_text())
    protocol = json.loads((HERE/"INDEPENDENT_PROTOCOL.json").read_text())
    assert np.__version__ == protocol["numpy_version"]
    for name, expected in protocol["numpy_python_predicates_sha256"].items():
        assert sha(inspect.getsource(getattr(np, name)).encode()) == expected
    assert publication["manifest_sha256"] == sha(manifest_path.read_bytes())
    for path, expected in manifest["files"].items():
        assert sha((ROOT/path).read_bytes()) == expected, path
    static.append("all_declared_frozen_dependency_hashes_match")
    oldlaw, newlaw = old.BlockLaw(), new.BlockLaw()
    assert oldlaw.identity == newlaw.identity
    assert all(getattr(old, name) is getattr(new, name) for name in ("COLLECT", "SPREAD", "GROUP"))
    for name in ("persist", "load", "restore_owned"):
        assert getattr(old_execution, name) is getattr(new_execution, name)
        static.append("same_function_object_"+name)
    assert ast.dump(function_ast(old_execution.execute)) == ast.dump(function_ast(new_execution.execute))
    static.append("execute_body_AST_identical")
    for old_class, new_class in ((old.PackedBeliefMemory, new.PackedBeliefMemory),
                                 (old.AnchoredPackedMemory, new.AnchoredPackedMemory)):
        for name, value in vars(old_class).items():
            if inspect.isfunction(value) or isinstance(value, (classmethod, property)):
                a = value.__func__ if isinstance(value, classmethod) else value.fget if isinstance(value, property) else value
                b = vars(new_class)[name]
                b = b.__func__ if isinstance(b, classmethod) else b.fget if isinstance(b, property) else b
                assert ast.dump(function_ast(a)) == ast.dump(function_ast(b))
                static.append(old_class.__name__+"_"+name+"_AST_identical")
    for first, second in ((old._probability, new._probability), (Law._belief, new.BlockLaw._belief),
                          (OldFull.restore, new.BeliefMemory.restore)):
        a = ReplaceMassPredicate().visit(function_ast(first))
        b = ReplaceMassPredicate().visit(function_ast(second))
        assert ast.dump(a) == ast.dump(b)
        static.append(first.__qualname__+"_only_mass_predicate_changed")
    for width in (8, 40):
        for name, source in arrays(width):
            variants = [("original", source)]
            if source.ndim == 1 and source.shape == (width,):
                variants += [("batch", np.tile(source, (4, 1))),
                             ("tensor", np.tile(source, (2, 3, 1))),
                             ("fortran", np.asfortranarray(np.tile(source, (4, 1))))]
                storage = np.zeros(width*2, dtype=source.dtype); storage[::2] = source
                variants.append(("noncontiguous", storage[::2]))
            for layout, value in variants:
                value.setflags(write=False)
                before = value.tobytes()
                functions = [("probability", lambda p: old._probability(p, width),
                              lambda p: new._probability(p, width))]
                if width == 40:
                    functions.append(("belief", oldlaw._belief, newlaw._belief))
                with np.errstate(over="ignore", invalid="ignore"):
                    for contract, first, second in functions:
                        a, av = outcome(lambda: first(value))
                        b, bv = outcome(lambda: second(value))
                        assert a == b and before == value.tobytes()
                        if a == "accepted":
                            assert av.dtype == bv.dtype == np.float64
                            assert av.shape == bv.shape and av.tobytes() == bv.tobytes()
                            assert np.shares_memory(av, value) == np.shares_memory(bv, value)
                            assert av.flags.writeable == bv.flags.writeable
                        rows.append({"section": contract, "name": name, "layout": layout,
                                     "input_shape": list(value.shape), "input_dtype": str(value.dtype),
                                     "input_sha256": sha(before), "outcome": a})
    # Actual inherited restore paths, not only a re-expression of the new helper.
    for label, old_type, new_type, width, projection in (
            ("full", OldFull, new.BeliefMemory, 40, "full"),
            ("packed", old.PackedBeliefMemory, new.PackedBeliefMemory, 8, "block"),
            ("anchored", old.AnchoredPackedMemory, new.AnchoredPackedMemory, 8, "block")):
        base = old_type(oldlaw, [0, 1, 2, 3], projection).checkpoint()
        state_key = "beliefs" if width == 40 else "packed"
        payloads = [("valid", copy.deepcopy(base))]
        for name, source in arrays(width):
            p = copy.deepcopy(base)
            p[state_key] = (np.tile(source, (4, 1)).tolist() if source.ndim == 1
                            and source.shape == (width,) else source.tolist())
            payloads.append((name, p))
        for name, value in (("clock_negative", -1.), ("clock_nan", float("nan")),
                            ("clock_inf", float("inf")), ("clock_bad_string", "bad"),
                            ("clock_numeric_string", "0"), ("clock_bool", False)):
            p = copy.deepcopy(base); p["clock"] = value; payloads.append((name, p))
        for name, value in (("counter_bool", True), ("counter_list", [4]),
                            ("counter_float", 4.), ("counter_negative", -1),
                            ("counter_huge_int", 2**200), ("counter_dict", {"v": 4})):
            p = copy.deepcopy(base); p["operations"]["writes"] = value; payloads.append((name, p))
        for name in ("counter_missing", "counter_extra", "counter_null", "wrong_model",
                     "wrong_schema", "extra_legacy_field"):
            p = copy.deepcopy(base)
            if name == "counter_missing": p["operations"].pop("writes")
            if name == "counter_extra": p["operations"]["extra"] = 0
            if name == "counter_null": p["operations"] = None
            if name == "wrong_model": p["model"] = "wrong"
            if name == "wrong_schema": p["schema"] = "unsupported"
            if name == "extra_legacy_field": p["unconsumed_legacy_field"] = [1, 2]
            payloads.append((name, p))
        for field in (state_key, "clock", "model", "schema"):
            p = copy.deepcopy(base); p.pop(field); payloads.append(("missing_"+field, p))
        if label == "full":
            for field, value in (("projection", []), ("projection", "mean"), ("method", []), ("method", "unknown")):
                p = copy.deepcopy(base); p[field] = value; payloads.append((field+"_"+str(value), p))
        if label == "anchored":
            for value in ([-1., 0., 0., 0.], [1., 0., 0., 0.], [0.]*3, [float("nan")]*4):
                p = copy.deepcopy(base); p["anchor_times"] = value; payloads.append(("invalid_anchor", p))
        for name, raw in payloads:
            p = reseal(raw)
            a, av = outcome(lambda: restore_owned(old_type, oldlaw, p, expected_projection=projection))
            b, bv = outcome(lambda: restore_owned(new_type, newlaw, p, expected_projection=projection))
            assert a == b
            if a == "accepted":
                assert av.checkpoint() == bv.checkpoint()
                saved_a, saved_b = av.checkpoint(), bv.checkpoint()
                p["operations"]["writes"] += 1
                if state_key in p and p[state_key] and isinstance(p[state_key][0], list):
                    p[state_key][0][0] = 9.
                assert av.checkpoint() == saved_a and bv.checkpoint() == saved_b
            rows.append({"section": "restore_"+label, "name": name, "outcome": a})
        damaged = copy.deepcopy(base); damaged["sha256"] = "0"*64
        for memory_type, law in ((old_type, oldlaw), (new_type, newlaw)):
            assert outcome(lambda: restore_owned(memory_type, law, damaged, expected_projection=projection))[0] == "ValueError"
        rows.append({"section": "restore_"+label, "name": "wrong_checksum", "outcome": "ValueError"})
    for group in (0, 7):
        p = np.zeros(8); p[group] = np.nextafter(0., 1.); p[(group+1)%8] = 1.
        with np.errstate(under="ignore"):
            assert outcome(lambda: old.unpack(p))[0] == outcome(lambda: new.unpack(p))[0] == "ValueError"
        rows.append({"section": "support", "name": "positive_subnormal_"+str(group), "outcome": "ValueError"})
    identities = {}
    for module in (new, new_execution, old, old_execution):
        path = Path(module.__file__)
        identities[path.relative_to(ROOT).as_posix()] = sha(path.read_bytes())
    return {"passed": True, "cases": rows, "case_count": len(rows), "static_contracts": static,
            "source_sha256": identities, "numpy_version": np.__version__,
            "frozen_manifest_sha256": sha(manifest_path.read_bytes()),
            "publication_source_commit": publication.get("source_commit", publication.get("commit_sha")),
            "numpy_isclose_source_sha256": sha(inspect.getsource(np.isclose).encode()),
            "body_cpu_seconds": time.process_time()-started,
            "scope": "Deterministic threshold/type/ownership/I-O-equivalence evidence; no resource-gain or full model-adoption inference."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    with args.output.open("xb") as stream:
        stream.write(gzip.compress(json.dumps(result, sort_keys=True, allow_nan=False).encode(), mtime=0))
    summary = {key: value for key, value in result.items() if key != "cases"}
    summary["raw_sha256"] = sha(args.output.read_bytes())
    summary["checker_sha256"] = sha(Path(__file__).read_bytes())
    with args.output.with_suffix(".summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps({"passed": True, "cases": result["case_count"], "static_contracts": len(result["static_contracts"])}, sort_keys=True))


if __name__ == "__main__":
    main()
