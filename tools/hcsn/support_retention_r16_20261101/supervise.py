"""Linux parent metering of complete confirmation processes, including imports."""

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time

from .study import HERE, ROOT, save, verify


def launch(seed, domain):
    stem = HERE / "results" / f"process_{seed}_{domain}"
    environment = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    command = [sys.executable, "-m", "tools.hcsn.support_retention_r16_20261101.study",
               "--seed", str(seed), "--domain", domain]
    start = time.perf_counter()
    with stem.with_suffix(".stdout.log").open("xb") as output, stem.with_suffix(".stderr.log").open("xb") as error:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=output, stderr=error)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    try:
        verified, verification_error = bool(verify()), None
    except Exception as exc:
        verified, verification_error = False, f"{type(exc).__name__}: {exc}"
    receipt = dict(fit=seed, domain=domain, exit_code=process.returncode,
                   command=command, cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
                   cpu_total_seconds=usage.ru_utime + usage.ru_stime,
                   wall_seconds=time.perf_counter() - start, max_rss_linux_kib=usage.ru_maxrss,
                   source_verified_after_exit=verified, verification_error=verification_error)
    save(stem.with_suffix(".json"), receipt)
    print(json.dumps(receipt), flush=True)
    return receipt


def main(workers):
    if sys.platform != "linux" or not hasattr(os, "wait4"):
        raise RuntimeError("This complete-process metering recipe explicitly requires Linux wait4")
    verify()
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    start, cpu = time.perf_counter(), time.process_time()
    jobs = [(seed, domain) for seed in protocol["fits"] for domain in protocol["domains"]]
    save(HERE / "results/LAUNCH.json", dict(workers=workers, jobs=jobs, protocol=protocol))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(launch, *job) for job in jobs]
        results = []
        for job, future in zip(jobs, futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(dict(fit=job[0], domain=job[1], exit_code=None,
                    cpu_total_seconds=None, source_verified_after_exit=False,
                    supervisor_error=f"{type(exc).__name__}: {exc}"))
    save(HERE / "results/PROCESS_SUMMARY.json", dict(workers=workers, processes=results,
        all_exited_zero=all(item["exit_code"] == 0 and item["source_verified_after_exit"] for item in results),
        all_child_costs_measured=all(item["cpu_total_seconds"] is not None for item in results),
        complete_child_cpu_seconds=sum(item["cpu_total_seconds"] for item in results if item["cpu_total_seconds"] is not None),
        supervisor_internal_cpu_seconds=time.process_time() - cpu,
        supervisor_wall_seconds=time.perf_counter() - start))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    main(parser.parse_args().workers)
