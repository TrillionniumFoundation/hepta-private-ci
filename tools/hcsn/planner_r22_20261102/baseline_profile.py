"""Development-only instrumented wall profile of the complete R21 durable actor."""

import argparse
import cProfile
import gzip
import hashlib
import json
import os
from pathlib import Path
import pstats
import subprocess
import sys
import tempfile
import time

from ..addressed_decision_r15_20261101.law import Law
from ..addressed_decision_r15_20261101.world import make_episode
from ..checkpoint_fastpath_r21_20261101.execution import execute
from ..planner_fastpath_r18_20261101.planner import KernelCache
from ..planner_r20_20261101.campaign import save, semantic
from ..support_retention_r16_20261101.compression import BlockLaw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def worker(output):
    protocol = json.loads((HERE / "PROFILE_PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "PROFILE_SOURCE_MANIFEST.json").read_text())
    for name, digest in manifest["files"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"Changed profile input: {name}")
    archive = ROOT / f"tools/hcsn/addressed_decision_r15_20261101/run_01/training/{protocol['fit']}.json.gz"
    models = json.loads(gzip.decompress(archive.read_bytes()))["calibration"]["models"]
    owner = Law()
    worlds = [make_episode(owner, protocol["namespace"] * 10**9 + i, ("iid", "ood")[i % 2])
              for i in range(protocol["worlds"])]
    profiler, records = cProfile.Profile(), []
    with tempfile.TemporaryDirectory(prefix="r22-profile-") as directory:
        for model in protocol["models"]:
            for representation in protocol["representations"]:
                for variant in protocol["variants"]:
                    law, cache = BlockLaw.from_payload(models[model]["payload"]), KernelCache()
                    for episode in worlds:
                        profiler.enable()
                        row = execute(law, episode, variant, representation,
                                      Path(directory) / "state.json", cache)
                        profiler.disable()
                        records.append(dict(model=model, representation=representation, variant=variant,
                            seed=episode.seed, semantic_sha256=hashlib.sha256(json.dumps(semantic(row),
                            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                            instrumented_cpu_seconds=row["cpu_seconds"],
                            instrumented_wall_seconds=row["wall_seconds"],
                            instrumented_persist_restore_cpu_seconds=row["checkpoint_io_cpu_seconds"]))
    rows = []
    for (filename, line, function), (primitive, calls, own, cumulative, callers) in pstats.Stats(profiler).stats.items():
        rows.append(dict(file=filename, line=line, function=function, primitive_calls=primitive,
                         total_calls=calls, instrumented_own_wall_seconds=own,
                         instrumented_cumulative_wall_seconds=cumulative))
    rows.sort(key=lambda r: r["instrumented_cumulative_wall_seconds"], reverse=True)
    save(output / "PROFILE.json", dict(functions=rows, records=records,
         scope="cProfileinstrumentedwallclockonly, completeunchangedR21actorincluding6durablecommits. Notbaselinecostorperformanceadvantageevidence; nestedcumulativetimesnotadditive."))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.output)
    else:
        if args.output.exists():
            raise FileExistsError(args.output)
        start = time.perf_counter()
        child = subprocess.Popen([sys.executable, "-m", __spec__.name, "--worker", "--output", str(args.output)])
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        save(args.output / "PROCESS_RECEIPT.json", dict(exit_code=code,
             complete_child_cpu_seconds=usage.ru_utime + usage.ru_stime,
             wall_seconds=time.perf_counter() - start, linux_max_rss_kib=usage.ru_maxrss,
             scope="Wholedevelopmentprofilechildimports,allattempts,output. Profiler/actorclocksnested,notaddedagain."))
        raise SystemExit(code)
