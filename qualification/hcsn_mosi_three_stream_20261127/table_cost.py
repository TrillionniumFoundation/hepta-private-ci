"""Measure a fresh offline He–Xiong price-grid construction and verify all stored coefficients."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def work(a):
    start = time.perf_counter()
    cpu = time.process_time()
    import numpy as np
    sys.path[:0] = [str(a.grid_source), str(a.law_source)]
    import lawtable
    readied = time.perf_counter()
    gridcpu = time.process_time()
    with tempfile.TemporaryDirectory() as tmp:
        lawtable.ROOT = Path(tmp)
        lawtable.build()
        built = time.perf_counter()
        builtcpu = time.process_time()
        path = Path(tmp) / 'law.npz'
        with np.load(path) as one, np.load(a.reference) as two:
            assert set(one.files) == set(two.files)
            errors = {k: float(np.max(np.abs(one[k]-two[k]))) for k in one}
            assert max(errors.values()) == 0, errors
            sizes = {k: int(one[k].size) for k in one}
        return {'dependency_import_wall_s': readied-start, 'grid_build_write_check_wall_s': built-readied,
                'grid_build_write_check_cpu_s': builtcpu-gridcpu, 'total_process_cpu_s':time.process_time()-cpu,
                'size_scalars':sizes,'max_abs_vs_archived': errors,
                'reference_sha256':sha(a.reference),'reconstructed_sha256':sha(path),
                'approximation_audit':json.loads((Path(tmp)/'law_audit.json').read_bytes())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('grid_source','law_source','reference','out'):
        parser.add_argument(key,type=Path)
    parser.add_argument('--child',action='store_true')
    args = parser.parse_args()
    if args.child:
        print(json.dumps(work(args)))
    else:
        runs = []
        for _ in range(5):
            t = time.perf_counter()
            proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], '--child'], check=True, capture_output=True,text=True)
            values = json.loads(proc.stdout)
            values['process_end_to_end_wall_s'] = time.perf_counter()-t
            runs.append(values)
        args.out.write_text(json.dumps({'scope':'fresh interpreter and complete one-time table generation, five independent repeats; downstream predictions reused an already distributed table; upstream multimodal feature extraction is unmeasured',
          'core':sorted(os.sched_getaffinity(0)), 'grid_source_sha256':sha(args.grid_source/'lawtable.py'),
          'financial_law_source_sha256':sha(args.law_source/'he_xiong.py'),'runs':runs},indent=1)+'\n')
