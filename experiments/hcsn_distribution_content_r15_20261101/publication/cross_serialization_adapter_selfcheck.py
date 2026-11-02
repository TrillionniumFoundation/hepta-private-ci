"""Bounded artificial checks for the cross JSON adapter; no formal data reads."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import pickle
import subprocess
import sys
from types import SimpleNamespace

import numpy as np

from experiments.hcsn_distribution_content_r15_20261101.publication import cross_serialization_adapter as adapter


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(output):
    output.mkdir(parents=True, exist_ok=False)
    checks = []

    def record(name, passed, **details):
        checks.append(dict(name=name, passed=bool(passed), **details))
        if not passed:
            raise AssertionError(name)

    cross = importlib.import_module(adapter.CROSS_MODULE)
    before, online_before = dict(vars(cross)), dict(vars(cross.online_confirm))
    source_hashes = {name:sha(cross.SOURCE.parent/name) for name in adapter.FROZEN_SOURCES}
    record("frozen_source_bytes", source_hashes == adapter.FROZEN_SOURCES)

    # A synthetic 512-object, 12-step full metadata row reproduces the actual
    # NumPy tolerance type without loading a model, a checkpoint, or a dataset.
    count, horizon = 512, 12
    reads = np.resize(np.array([0, 1, horizon], dtype=np.int64), count)
    labels = np.arange(count, dtype=np.int64) % 3
    elapsed = reads.astype(np.float32)
    fee = (0.0025*reads + 0.0005*elapsed).astype(np.float32)
    arrays = dict(labels=labels, prediction=labels.copy(), read_count=reads,
                  dt=np.ones((count, horizon), dtype=np.float32),
                  elapsed=elapsed, fee=fee, utility=np.float32(1)-fee)
    arithmetic = cross.validate_arrays(arrays, class_count=3)
    origins = {mode:dict(checkpoint_path=f"synthetic/{mode}/selected.pt",
                        checkpoint_sha256="1"*64,
                        summary_path=f"synthetic/{mode}/SUMMARY.json",
                        summary_sha256="2"*64) for mode in ("light", "value")}
    chunks = []
    for start in range(0, count, 32):
        block = reads[start:start+32]
        chunks.append(dict(start=start, end=start+len(block), cpu_seconds=.01,
            wall_seconds=.02, actual_reads=int(block.sum()),
            processed_prefix_tokens=int((block*(block+1)//2).sum()),
            model_calls=int(block.max()), controller_batch_calls=int(block.max())+1,
            initial_readout_calls=1))
    execution = dict(objects=count, batch_size=32, chunks=chunks,
        actor_cpu_seconds=.25, actor_wall_seconds=.5,
        **{name:sum(item[name] for item in chunks) for name in
           ("actual_reads", "processed_prefix_tokens", "model_calls",
            "controller_batch_calls", "initial_readout_calls")},
        scope="Artificial fixture only")
    row = dict(task="recall", seed=15131, family="ordinary_distribution",
        train_mode="light", exec_mode="value", cell="LV", domain="iid",
        path="synthetic/ordinary_distribution_iid_LV.npz", sha256="3"*64,
        model_hash="4"*64, controller_hash="5"*64, data_sha256="6"*64,
        sources=origins, inherited_LL_path="synthetic/ordinary_distribution_iid_light.npz",
        inherited_LL_sha256="7"*64, inherited_VV_controller_hash="5"*64,
        arithmetic_checks=arithmetic, execution=execution)
    tolerance = arithmetic["elapsed"]["tolerance"]
    original_error = None
    try:
        before["write"](output/"original_writer_partial.json", row)
    except TypeError as error:
        original_error = str(error)
    record("original_full_row_reproduces_numpy_scalar_failure",
           isinstance(tolerance, np.float32) and original_error is not None,
           scalar_type=type(tolerance).__name__, error=original_error)

    installed = adapter.install()
    changed = sorted(key for key in set(before) | set(vars(cross))
                     if before.get(key) is not vars(cross).get(key))
    record("only_cross_writer_and_child_route_replaced",
           installed is cross and changed == ["MODULE", "write"]
           and all(online_before.get(key) is value for key,value in vars(cross.online_confirm).items())
           and len(online_before) == len(vars(cross.online_confirm)), changed_globals=changed)

    row_before = pickle.dumps(row, protocol=5)
    array_before = {key:value.tobytes() for key,value in arrays.items()}
    cross.write(output/"full_row.json", row)
    expected = pickle.loads(row_before)
    expected["arithmetic_checks"]["elapsed"]["tolerance"] = float(tolerance)
    observed = json.loads((output/"full_row.json").read_text())
    record("full_row_roundtrip_preserves_all_fields_and_values", observed == expected)
    record("input_row_and_arrays_unchanged",
           row_before == pickle.dumps(row, protocol=5)
           and all(array_before[key] == value.tobytes() for key,value in arrays.items()))

    scalars = [np.float16(.5), np.float32(.1), np.float64(.3),
               np.int8(-2), np.int64(2**54+3), np.uint64(2**63+1), np.bool_(True)]
    cross.write(output/"numpy_scalars.json", scalars)
    record("numpy_float_integer_boolean_item_values_preserved",
           json.loads((output/"numpy_scalars.json").read_text()) == [item.item() for item in scalars])
    primitives = dict(none=None, booleans=[False, True], integer=2**63+1,
                      values=[-0., .1, 1e-15], text="原始 primitive", nested={"x":[1,2,3]})
    before["write"](output/"primitive_original.json", primitives)
    cross.write(output/"primitive_adapter.json", primitives)
    record("native_primitives_have_identical_serialized_bytes",
           (output/"primitive_original.json").read_bytes() == (output/"primitive_adapter.json").read_bytes())

    nonfinite = [float("nan"), float("inf"), np.float32("nan"), np.float32("inf"), np.float64("-inf")]
    rejected = []
    for index,value in enumerate(nonfinite):
        try:
            cross.write(output/f"rejected_nonfinite_{index}.json", {"value":value})
        except ValueError:
            rejected.append(index)
    record("allow_nan_false_rejects_native_and_numpy_nonfinite", rejected == list(range(len(nonfinite))))
    unsupported = [np.array([1.,2.]), np.complex64(1+2j), complex(1,2)]
    if type(np.longdouble(1).item()) not in (float, int, bool):
        unsupported.append(np.longdouble(1))
    rejected = []
    for index,value in enumerate(unsupported):
        try:
            cross.write(output/f"rejected_type_{index}.json", {"value":value})
        except TypeError:
            rejected.append(index)
    record("arrays_complex_and_non_native_item_results_rejected", rejected == list(range(len(unsupported))))
    prior = (output/"full_row.json").read_bytes()
    refused = False
    try:
        cross.write(output/"full_row.json", {"overwrite":True})
    except FileExistsError:
        refused = True
    record("exclusive_create_preserves_existing_file", refused and prior == (output/"full_row.json").read_bytes())

    # Exercise the unchanged launch function with artificial prerequisites and
    # process receipts. No scientific worker is started by this fixture.
    saved = (cross.registered, cross.prerequisites, cross.subprocess.Popen, cross.os.wait4)
    commands = []

    def fake_popen(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(pid=900000+len(commands), returncode=None)

    try:
        cross.registered = lambda root: ({"tasks":["recall","binding"], "seeds":[15131]}, {})
        cross.prerequisites = lambda root: None
        cross.subprocess.Popen = fake_popen
        cross.os.wait4 = lambda pid, flags: (pid, 0, SimpleNamespace(ru_utime=.125, ru_stime=.025, ru_maxrss=100))
        total = cross.launch(output/"artificial_launch", workers=2)
    finally:
        cross.registered, cross.prerequisites, cross.subprocess.Popen, cross.os.wait4 = saved
    expected_commands = [[sys.executable,"-m",adapter.MODULE,"group","--output",str(output/"artificial_launch"),
                          "--task",task,"--seed","15131"] for task in ("recall","binding")]
    record("frozen_launch_routes_every_child_to_adapter", commands == expected_commands and total["failed"] == 0,
           commands=commands, artificial_process_receipts=True)

    child_source = '''import json,sys\nfrom pathlib import Path\nimport numpy as np\nfrom experiments.hcsn_distribution_content_r15_20261101.publication import cross_serialization_adapter as a\nc=a.install()\nc.write(Path(sys.argv[1]), {"float":np.float32(.1),"integer":np.int64(7),"boolean":np.bool_(True),"module":c.MODULE,"source":str(c.SOURCE)})\n'''
    (output/"child_install_fixture.py").write_text(child_source)
    child = subprocess.run([sys.executable,str(output/"child_install_fixture.py"),str(output/"child_output.json")],
                           capture_output=True, text=True, timeout=30)
    help_result = subprocess.run([sys.executable,"-m",adapter.MODULE,"--help"],
                                 capture_output=True, text=True, timeout=30)
    child_row = json.loads((output/"child_output.json").read_text()) if child.returncode == 0 else {}
    record("fresh_child_installs_same_writer_and_original_source",
           child.returncode == 0 and child_row == dict(float=float(np.float32(.1)),integer=7,boolean=True,
               module=adapter.MODULE,source=str(cross.SOURCE))
           and help_result.returncode == 0 and "{register,group,launch,index,development}" in help_result.stdout,
           child_exit_code=child.returncode, module_help_exit_code=help_result.returncode)
    record("all_scientific_functions_and_source_bytes_remain_unchanged",
           all(before[key] is vars(cross)[key] for key in before if key not in ("write","MODULE"))
           and source_hashes == {name:sha(cross.SOURCE.parent/name) for name in source_hashes})

    result = dict(schema="hcsn.r15.cross-serialization-adapter.selfcheck.v1",
        utc=datetime.now(timezone.utc).isoformat(), source_sha256=sha(Path(adapter.__file__)),
        fixture_source_sha256=sha(Path(__file__)), frozen_source_sha256=source_hashes,
        confirmation_data_accessed=False, models_executed=False, formal_files_modified=False,
        checks=checks, checks_count=len(checks), passed=all(item["passed"] for item in checks),
        scope="Artificial full metadata row, scalar/write contracts, immutable science function identity, frozen launcher command routing, fresh child import. Expected failed JSON fragments are retained.",
        artifacts={str(path.relative_to(output)):dict(bytes=path.stat().st_size,sha256=sha(path))
                   for path in sorted(output.rglob("*")) if path.is_file()})
    adapter.write(output/"SELFCHECK.json", result)
    print(json.dumps(dict(passed=result["passed"],checks=result["checks_count"],source_sha256=result["source_sha256"])))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    check(parser.parse_args().output.resolve())
