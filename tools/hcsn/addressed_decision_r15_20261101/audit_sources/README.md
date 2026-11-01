# Historical independent audit implementations

These files preserve the implementations used to produce the independent audit
evidence. They were archived after the audit, without changing the frozen
experiment, fitted models, raw records or published audit results.

| File | Origin | SHA-256 |
| --- | --- | --- |
| `independent_execution_audit.py` | Exact recovered source of the executed inline audit | `6544e0d5bfd7bc203ecae50eda9b9052d4e54c145b7b1cb4d5374be846d3f8ac` |
| `independent_statistics_audit.py` | Exact copy of the successful independent statistics audit script | `48b84dd03d95add33f0ddd1b1f63367dd089360faf970eb780e96a99c30f496d` |
| `reconstruct_progress.py` | Exact independent reconstruction command retained in the execution audit JSON | `e31d9d5b15538874f70ca0c07ffe8b5b035df0ae518e8fcc0cc9ce58b30f8f2f` |

The first script uses its own world/token/filter/checkpoint verification, while
importing the frozen `Law` loader and memoryless-generator constructor. It does
not invoke the original execution owner or planner. The statistics audit imports
no project functions. Their limits are stated in the resulting reports.

The historical scripts deliberately reject existing output files. The execution
script requires Linux/POSIX `fork` and `wait4`, restored owner evidence and the
reconstructed `run_02/progress` directory. It creates the JSON report, not the
separately authored Markdown report; the human-readable reconstruction command in
the published JSON was added as presentation metadata afterwards. The statistics
script retains its original absolute study path. Neither historical source is a
portable command-line application.

Use a disposable checkout and the path adaptation in [REPRODUCE.md](../REPRODUCE.md).
Do not rerun them against the preserved original result directory. Scientific
checks and conclusions should reproduce; process timing, timestamps, and later
presentation metadata are not byte-identical replay targets. Archiving and
syntax-checking these sources did not execute another scientific audit.
