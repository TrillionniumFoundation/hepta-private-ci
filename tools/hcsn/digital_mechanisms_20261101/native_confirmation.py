"""New native trajectories from frozen fitted physical parameters, no task data.

This is a prospective fitted-parameter CTMC execution experiment, not a replay
of renewal_checks. Prior evidence tested native source d37e251... . Repository
formatting changed only its fs import layout to 64df3f...; that historical result
retains its original source identity. This program compiles the current frozen
source and records its own binary, trajectories, costs, and process identities.
"""
import time

_IMPORT_CPU_START = time.process_time()

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import struct
import subprocess

from .models import MechanismPolicy
from .renewal import export_native, generator
from .run_study import digest, read_json, source_hashes, write_json
from .training import candidates

HERE = Path(__file__).resolve().parent
ARM = "first_passage_bank__structured_on"
SEED_BASE = 870000000000
# start_state, symbol, reliability, external_cut_time, end_time. These are
# prospective execution cases, not selected on learned outcomes or event counts.
CASES = ((7, 0, .5, .375, 3.), (0, 1, .65, .5, 6.),
         (14, -1, .85, .75, 3.), (15, 1, .95, 1.25, 6.),
         (16, -1, .55, 1.5, 6.), (7, 1, .85, 2.25, 9.),
         (15, 0, .5, .25, 3.), (16, -1, .95, 3.125, 9.))
PRIOR_TESTED_NATIVE = "d37e25193c318a34f6e79a025b0661c23147a9af840bfcc3bfaa7cfc33cb80ef"
POST_FORMAT_NATIVE = "64df3f47465ba0d66451830e8cc845339b8dd67fedd64727b14fab5ca988f2fc"


def _child_cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def _invoke(command, folder, name):
    wall, cpu = time.perf_counter(), _child_cpu()
    process = subprocess.Popen(list(map(str, command)), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    receipt = dict(command=list(map(str, command)), pid=process.pid, returncode=process.returncode,
                   wall_seconds=time.perf_counter()-wall, child_cpu_seconds=_child_cpu()-cpu)
    for label, payload in (("stdout", stdout), ("stderr", stderr)):
        path = folder/f"{name}.{label}"
        with path.open("xb") as stream:
            stream.write(payload)
        receipt[label] = dict(file=path.name, sha256=digest(path), bytes=len(payload))
    write_json(folder/f"{name}.process.json", receipt)
    return receipt, stdout, stderr


def _checkpoint_summary(path):
    fields = path.read_text().splitlines()[0].split()
    number = lambda text: struct.unpack("<d", struct.pack("<Q", int(text, 16)))[0]
    return dict(time=number(fields[4]), state=int(fields[5]), rng_state=int(fields[6]),
                pending_time=number(fields[7]), pending_destination=int(fields[8]),
                lower_events=int(fields[9]), upper_events=int(fields[10]), total_jumps=int(fields[11]))


def run(training, freeze_path, output, rustc):
    training, freeze_path, output = map(Path, (training, freeze_path, output))
    wall, cpu, child = time.perf_counter(), time.process_time(), _child_cpu()
    freeze, protocol = read_json(freeze_path), read_json(HERE/"protocol.json")
    sources, freeze_digest = source_hashes(), digest(freeze_path)
    fits = protocol["fits"]
    expected_models = {f"{fit}/{c['id']}" for fit in fits for c in candidates()}
    commit = freeze.get("verified_remote_commit", "")
    if (not 2 <= len(fits) <= 16 or len(fits) != len(set(fits)) or freeze["fits"] != fits
            or freeze["protocol"] != protocol or freeze["source_sha256"] != sources
            or set(freeze["models_sha256"]) != expected_models
            or len(commit) != 40 or set(commit)-set("0123456789abcdef")):
        raise ValueError("complete published formal model freeze and unchanged registered source/protocol required")
    # Read only selected model artifacts. No TRAIN/validation or IID/OOD cohort
    # is generated or opened; completeness is bound by the published freeze.
    fitted = {}
    for fit in fits:
        path = training/f"fit_{fit}"/"models"/f"{ARM}.json"
        if digest(path) != freeze["models_sha256"][f"{fit}/{ARM}"]:
            raise ValueError("selected fitted model changed after freeze")
        artifact = read_json(path)
        policy = MechanismPolicy.from_export(artifact)
        if (policy.fit != fit or policy.family != "first_passage_bank" or
                policy.terminal_mode != "structured" or policy.drive_mode != "sustained"):
            raise ValueError("unexpected fitted mechanism identity")
        physical = {key: float(value.detach()) for key, value in policy.cell.physical().items()}
        fitted[fit] = dict(physical=physical, model_sha256=digest(path), model_path=str(path))
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"STARTED.json", dict(schema="digital-fitted-native-renewal-start-v1",
               utc=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
               model_freeze_sha256=freeze_digest, verified_model_commit=commit,
               fits=fits, cases=CASES, seed_base=SEED_BASE, task_confirmation_accessed=False))
    try:
        native = HERE/"renewal_native.rs"
        binary = output/"renewal_native"
        compiler, compiler_out, _ = _invoke([rustc, "--version"], output, "compiler")
        build, _, build_errors = _invoke([rustc, "--edition=2024", "-O", "-C", "strip=symbols",
                                         native, "-o", binary], output, "build")
        if compiler["returncode"] or build["returncode"]:
            raise RuntimeError("native compilation failed: "+build_errors.decode(errors="replace"))
        binary_digest, results = digest(binary), []
        for fit in fits:
            folder = output/f"fit_{fit}"
            folder.mkdir()
            write_json(folder/"MODEL.json", fitted[fit])
            for index, (start, symbol, reliability, cut, end) in enumerate(CASES):
                case = folder/f"case_{index}"
                case.mkdir()
                seed = SEED_BASE+int(fit)*1000+index
                record = dict(fit=fit, case=index, seed=seed, initial_state=start,
                              input_assumption=dict(symbol=symbol, reliability=reliability, held_constant=True),
                              cut=cut, end=end, model_sha256=fitted[fit]["model_sha256"], passed=False)
                try:
                    q, _ = generator(fitted[fit]["physical"], symbol, reliability)
                    model = case/"generator.txt"
                    record["generator_fnv64"] = export_native(model, q)
                    record["generator_sha256"] = digest(model)
                    commands = (("whole", ["new", model, seed, end, case/"whole.checkpoint", case/"whole.events", start]),
                                ("cut", ["new", model, seed, cut, case/"cut.checkpoint", case/"cut.events", start]),
                                ("resume", ["resume", model, case/"cut.checkpoint", end, case/"resume.checkpoint", case/"resume.events"]))
                    processes = []
                    for name, command in commands:
                        receipt, stdout, stderr = _invoke([binary, *command], case, name)
                        processes.append(receipt)
                        if receipt["returncode"]:
                            raise RuntimeError(f"{name} failed: "+stderr.decode(errors="replace"))
                        json.loads(stdout)  # Require an actual native summary, not empty success.
                    whole = (case/"whole.checkpoint").read_bytes()
                    resumed = (case/"resume.checkpoint").read_bytes()
                    if (whole != resumed or (case/"whole.events").read_bytes() !=
                            (case/"cut.events").read_bytes()+(case/"resume.events").read_bytes()
                            or (case/"whole.stdout").read_bytes() != (case/"resume.stdout").read_bytes()):
                        raise AssertionError("actual new-process continuation differs from uninterrupted execution")
                    if len({p["pid"] for p in processes}) != 3:
                        raise AssertionError("three distinct native process identities required")
                    record.update(passed=True, process_ids=[p["pid"] for p in processes],
                                  cut_state=_checkpoint_summary(case/"cut.checkpoint"),
                                  final_state=_checkpoint_summary(case/"whole.checkpoint"),
                                  final_checkpoint_sha256=digest(case/"whole.checkpoint"),
                                  event_trace_sha256=digest(case/"whole.events"),
                                  event_trace=[json.loads(line) for line in (case/"whole.events").read_text().splitlines()])
                except Exception as error:
                    record["error"] = dict(type=type(error).__name__, message=str(error))
                write_json(case/"RESULT.json", record)
                results.append(record)
        if source_hashes() != sources or digest(freeze_path) != freeze_digest:
            raise ValueError("source or model freeze changed during native experiment")
        for fit in fits:
            if digest(fitted[fit]["model_path"]) != fitted[fit]["model_sha256"]:
                raise ValueError("fitted model changed during native experiment")
        files = {str(p.relative_to(output)): dict(bytes=p.stat().st_size, sha256=digest(p))
                 for p in sorted(output.rglob("*")) if p.is_file()}
        result = dict(schema="digital-fitted-native-renewal-confirmation-v1", passed=all(r["passed"] for r in results),
                      source_sha256=sources, model_freeze_sha256=freeze_digest, verified_model_commit=commit,
                      compiler=compiler_out.decode().strip(), binary_sha256=binary_digest,
                      native_source_sha256=digest(native), fits=fits, cases=results, artifact_files=files,
                      expected_trajectory_cases=8*len(fits), completed_cases=len(results),
                      passed_cases=sum(r["passed"] for r in results),
                      prior_evidence=dict(native_source_sha256=PRIOR_TESTED_NATIVE,
                                          formatting_successor_sha256=POST_FORMAT_NATIVE,
                                          change="fs import layout only; old verification remains bound to old source",
                                          old_suite_rerun=False),
                      scientific_scope="New finite-CTMC trajectories parameterized by frozen fitted cell physics; not image-law task efficacy",
                      task_confirmation_accessed=False, production_owner_integrated=False, production_activation=False,
                      cost=dict(module_import_cpu_seconds=_IMPORT_CPU_SECONDS,
                                experiment_python_cpu_seconds=time.process_time()-cpu,
                                actual_subprocess_cpu_seconds=_child_cpu()-child,
                                wall_seconds=time.perf_counter()-wall,
                                subprocess_scope="compiler version, compilation, and every native attempt; failures included"))
        write_json(output/"FINISHED.json", result)
        return result
    except Exception as error:
        write_json(output/"FAILED.json", dict(type=type(error).__name__, message=str(error),
                   source_sha256=sources, model_freeze_sha256=freeze_digest,
                   experiment_python_cpu_seconds=time.process_time()-cpu,
                   actual_subprocess_cpu_seconds=_child_cpu()-child, wall_seconds=time.perf_counter()-wall))
        raise


_IMPORT_CPU_SECONDS = time.process_time()-_IMPORT_CPU_START

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--training", required=True, type=Path)
    parser.add_argument("--freeze", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rustc", default="rustc")
    args = parser.parse_args()
    outcome = run(args.training, args.freeze, args.output, args.rustc)
    print(json.dumps({key: outcome[key] for key in ("passed", "completed_cases", "passed_cases", "binary_sha256", "cost")}, sort_keys=True))
    raise SystemExit(0 if outcome["passed"] else 2)
