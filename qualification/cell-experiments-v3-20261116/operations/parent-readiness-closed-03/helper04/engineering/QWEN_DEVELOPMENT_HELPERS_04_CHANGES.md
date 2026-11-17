# helpers04: explicit RAM workspace

The DATA-bound helpers03 package is preserved, unchanged and unused. The
readiness owner subsequently observed that `/data` had no blocks available to
the runtime account. Root selected the following new workspace explicitly:

`/dev/shm/hepta-cell-experiments-v3-20261116-0c078a`

The only Python source change from helpers03 is the value of `WORKSPACE_ROOT`
in `qwen_development_io_v3.py`. All other Python files are byte-identical to03.
The original runtime remains exactly:

`/home/qian-qi/hepta-cell-experiments-v3-20261116-0c078a`

## Binding and deployment

The existing `--artifact-root` argument is the explicitly fixed RAM workspace.
Source, prior readiness, output and frozen inputs must be strict absolute
descendants without symlink components. `FREEZE.json` records `workspace_root`
and `runtime_root`. The original interpreter, `venv` prefix, installed versions,
full installed-distribution mapping and recovery evidence hashes remain bound
to the HOME runtime root. The frozen model and adapter resolvers use
`artifact_root` as before. For a strictly one-constant code change, the existing
path-rejection messages still contain the word DATA; the enforced path is the
RAM `WORKSPACE_ROOT` above, and the frozen fields record that exact path.

The sole readiness owner prepares the actual RAM workspace and model files.
Before any real run, its preflight must observe at least 10 GiB `MemAvailable`
and at least 8 GiB tmpfs space available to the runtime account. These are
deployment requirements, not measurements claimed by this package.

Later deployment must copy the original `QWEN_SOURCE_02.json` without edits to
`WORKSPACE_ROOT/operations/QWEN_SOURCE_02.json`, SHA-256
`f4baf14dfb07513ade469adf6877ce6cd15ac98fbcc0e390854fcf24c85ae2be`.
The original source archive remains SHA-256
`38a6f8bbc8a602befcd45ebd919bbcb2eca12d9f105798b29d72b2eb051c42d7`.

## Unchanged behavior and verification

The helpers03 CUDA lifecycle repair is retained: collect Python garbage and
empty already-freed CUDA allocations before the initial evaluation device
check. The 4 GiB free-device-memory threshold is unchanged.

The greater-than-zero same-parent actual A business-success gate is unchanged.
No zero-baseline exploratory policy is implemented. All six arms, four fits,
64 steps per fit, model and data identities, generation and training settings,
budgets, source119/core64, and B/C/adoption/circuit restrictions are unchanged.

The 13 engineering tests passed once on the exact helpers03 hashes recorded in
the included original test receipt. They were not rerun on helpers04 solely for
this constant change. Verification of04 consists of exact source diffs, parsed
AST comparison proving that the workspace constant is the only source change,
hash checks of the unchanged source119/core64 and prior helper packages, and
byte checks of this archive. This is not a claim of actual RAM preflight or GPU
validation. Root owns the final repository `just fmt` gate; no tests are to be
rerun after that final formatting step.

No uploads, remote writes, model loading, training, tokenization or authored
reference execution were performed while creating this package. New research
protocol design, if accepted later, must receive a separate identity and must
not rewrite the original helpers01/02/03/04 gates or outcomes.
