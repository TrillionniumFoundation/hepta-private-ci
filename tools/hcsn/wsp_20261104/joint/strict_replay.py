"""Strict-FP repeat of the already fixed checked replay.

The execution path (explicit reduction reference, solvers and all decisions)
uses raise-on-overflow/invalid/divide. checked_replay only ignores exception
flags for the diagnostic BLAS result that it compares with the reference;
that BLAS result is never used for decisions in this replay.
"""
from pathlib import Path
import json,runpy,sys
import numpy as np
with np.errstate(over='raise',invalid='raise',divide='raise'):
    runpy.run_path(str(Path(__file__).with_name('checked_replay.py')),run_name='__main__')
Path(sys.argv[2],'strict_fp.json').write_text(json.dumps({'over':'raise','invalid':'raise','divide':'raise','execution_path':'explicit reductions + original solver + original fixed protocol','diagnostic_blas_flags':'ignored only inside comparison; BLAS output is independently checked and never used for decisions','completed_without_exception':True},indent=2)+'\n')
