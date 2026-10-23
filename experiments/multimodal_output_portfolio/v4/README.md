# HEPTA dynamic modality allocation v4

Current outcome: complete development and independent replay passed. The first
registered confirmation stopped at the capacity preflight before model execution.
See [RESULTS.md](RESULTS.md) and [BLOCKER_LEDGER.json](BLOCKER_LEDGER.json);
formal mechanism acceptance and confirmatory superiority remain unestablished.

## Implemented problem and scope

This stage studies a finite inference-control problem using the three frozen v3
NDU checkpoints. It introduces four distinct latent states, one for each output
modality. The text encoder's eight-class semantic condition `q` stays fixed;
`q` is not a vector of modality resource shares. After observing the current
four latents, the controller selects `EMIT` or one of
`REFINE_text`, `REFINE_audio`, `REFINE_image`, and `REFINE_video`. A refinement
executes the inherited learned network on the selected state only. Emission
executes all four learned decoders and seals the stream.

There is **no new weight training in v4**. Encoders, the conditional anchor map,
refiner and decoders are frozen. The stochastic restoration task has an
artificial known clean anchor, mandatory external disturbances, four registered
initial disturbance patterns and a known three-branch innovation law. Innovations
are sampled only after committing the selected action. The clean reference
removes the disturbances and directly decodes the known anchor; this bypass is
outside the mandatory-disturbance problem and exposes its restricted scope.

The four generated tensors represent synthetic text, audio, image and video
targets. This is not natural multimodal foundation-model training, natural
semantic generation, temporal video modelling, a diffusion-model comparison,
or a demonstrated solution of a general controlled NDU/FBSDE. The separate
`../natural_io/` interface experiments do not change this scope.

The mathematical contract, including the broader unimplemented proposal, is in
[THEORY.md](THEORY.md). [protocol.json](protocol.json) fixes the scientific
parameters and interpretation. The preregistration commit is
`f10589f3df5d2da88b2b5d92e3686441ce982461`; the protocol SHA256 is
`4f90f435e3ce419a09f42412af1fc6fe3515f3c198e5e8555115b1996c1aab0b`.
The final implementation freeze will be recorded in the run's
`source-manifest.json`; this README does not declare a confirmation result.

## Policies, real execution and cost

All arms use the same frozen weights and online hard cap. The registered arms
have different information and commitment rules:

| Arm | Decision rule |
| --- | --- |
| `dynamic` | Recompute the best feasible modality action using the full two-step entropic continuation value after each observed update. |
| `initial_feedback_committed_open_loop` | Given the complete initial latent state, evaluate all 21 sequences of zero, one or two modality refinements, including repetition, then bind the best sequence at INIT. |
| `myopic` | Compare emission with one refinement followed by emission; after execution, observe the new state and apply that one-step rule again. Its full realized policy value is reported separately from its decision scores. |
| `clean_no_disturbance_reference` | Run the same encoder and anchor, omit disturbances and emit immediately. This is a diagnostic reference. |

The objective combines the unchanged joint four-output reconstruction and
contradiction loss with actual online Linear MAC cost, using an entropic
certainty equivalent. There is no bonus for choosing a modality, using more
steps or producing a nonzero update. Dynamic control includes the fixed plans
in its finite policy class; dominance in that enumerated model alone is not
evidence of a scalable method or generalization advantage.

[allocation_control.py](allocation_control.py) builds every registered state
and candidate output before evaluation worlds are sampled. It executes real
neural forwards for the full tree, including candidates that no online policy
will select. Online lookup uses the actually observed condition, four latents
and causal history. It receives no evaluator truth, hidden future sample or
initial-pattern identifier. This exhaustive compiler is not a learned scalable
controller; the search grows exponentially with the horizon and branch count.

[allocation_model.py](allocation_model.py) meters actual `nn.Linear` forwards.
The complete online profile is fixed, with a global maximum of two refinements:

| Operation | Dense Linear MAC |
| --- | ---: |
| Text encoder plus conditional anchor, charged once at INIT | 3,584 |
| One selected modality refinement | 8,704 |
| Text / audio / image / video decoder | 6,656 / 69,632 / 53,248 / 200,704 |
| Complete four-output emission | 330,240 |
| Per-trajectory hard cap | 351,232 |

Each refinement must preserve the full emission reserve. The shared INIT cost
is reconciled by Python and Rust once; it is not added again outside the native
total. Planning, encoder-contract checks and online forwards have separate
ledgers. The report includes the complete shared planning cost and its
amortization for one and 1,024 worlds, not only selected online actions.
Independent audit/replay and development costs remain separate and are not
claimed to be included in the formal run subtotal.

These counts exclude nonlinear arithmetic, hashing, controller arithmetic,
serialization and IPC. Planning/phase/full-run CPU and wall measurements and
native RPC/CPU/lifetime measurements accompany the MAC counts. Native lifetime
includes waiting for Python; it must not be interpreted as native compute time.
The bridge obtains CPU usage for its own child PID using `wait4`.

The separate `ndu-modality-portfolio` Rust binary compares all five supplied
candidate scores in canonical order, applies the registered feasibility and
commitment masks, charges the selected operation, and waits for execution ACKs.
It binds versions, budgets, four ordered latent hashes and all four output
hashes. The neural operations and Bellman values are computed by Python. This
research bridge does not integrate production `NeuronRuntime` dispatch,
authenticate a malicious caller's execution, solve Bellman equations in Rust,
or provide a production security attestation. Independent array replay is
needed to check that acknowledged hashes came from the recorded neural work.

## Required assets and environment

Use a compatible Linux host with Python 3.12, NumPy 1.26.4 and
`torch==2.5.1+cpu`; the runner rejects a different registered runtime and sets
four Torch threads. The recorded native executable is Linux x86-64. The bridge
uses POSIX process/pipe APIs; this recipe does not claim Windows support.

`--source-run` points to a directory containing the following **original v3**
checkpoints. Each file has 2,692,980 bytes; the paths and digests are pinned in
the protocol.

| Relative checkpoint path | SHA256 |
| --- | --- |
| `seed-17/ndu-model.pt` | `40af186981d3d102362be76886f383aacdbad1d8992a9262f33760c991814082` |
| `seed-29/ndu-model.pt` | `2f0a3e6e8b77cdcd6bbf7a88387f15cb2e71b38a8a066f3b96ce42b064ff3c8c` |
| `seed-43/ndu-model.pt` | `cf0e27759a76a0f90ed37aaf04823d9540a1ad9ab99e8180b5d741e075ec9ddc` |

The runner checks each checkpoint's byte length and SHA256 before loading.
`AllocationModel` rechecks the hash, loads with `torch.load(...,
weights_only=True, map_location="cpu")`, uses strict state-dictionary loading,
checks the recorded tensor-state hashes and freezes all parameters. Substituting
another checkpoint requires a new scientific specification, not an edited hash
check. Keep the inherited v3 evidence and these exact weights with the replay.

The original native executable SHA256 is
`a945120403d1206fb62153e764575a1423e092262aa42833bee2c2df69856687`.
[evidence/native_build_final.json](evidence/native_build_final.json) binds its
five new Rust source files, direct shared Rust sources and Cargo/toolchain
configuration. Its source commit binds bytes built before that commit was
created; it does not assert that the commit already existed as HEAD at build
time. The dependency manifest is not an attestation of every transitive binary
dependency.

## A. Re-execute the original frozen source and original binary

Use the implementation commit recorded by the original run, its original build
receipt and original executable. A new checkout should be detached at that
commit. Replace the absolute paths below with the extracted evidence locations;
the output directory must not exist. Keep the original evidence directory
unchanged.

```bash
export NDU_V4_ORIGINAL=/absolute/path/original-v4-run
export NDU_V4_SOURCE_RUN=/absolute/path/original-v3-checkpoints
export NDU_V4_BINARY=/absolute/path/original-native/ndu-modality-portfolio
export NDU_V4_FIXTURE=/absolute/path/original-four-action-fixture
export NDU_V4_REPLAY=/absolute/path/new-v4-replay
export NDU_V4_COMMIT="$(python -c 'import json,os; from pathlib import Path; print(json.loads((Path(os.environ["NDU_V4_ORIGINAL"])/"source-manifest.json").read_text())["implementation_commit"])')"
git worktree add --detach /absolute/path/v4-replay-checkout "$NDU_V4_COMMIT"
cd /absolute/path/v4-replay-checkout
chmod u+x "$NDU_V4_BINARY"

python experiments/multimodal_output_portfolio/v4/run.py \
  --source-run "$NDU_V4_SOURCE_RUN" \
  --native-binary "$NDU_V4_BINARY" \
  --output "$NDU_V4_REPLAY"
```

No rebuild is needed for this route. Both full and `--development` runs check
the binary against their committed build receipt and check the receipt's source
and dependency hashes. Do not bypass these checks when a different build fails
to match. Re-executing the registered worlds reproduces the experiment; it does
not create independent scientific confirmation.

For a development attempt, add `--development` and choose a different new output
directory. This uses study seed 5, the seed-17 checkpoint and the smaller
registered world count. Development may record dirty source bytes and preserves
copies of them; confirmation requires every manifest source byte to match its
Git commit. Do not commit, change HEAD or modify runtime/auditor sources while a
run is active: the final source manifest must equal the initial manifest.

The runner estimates complete evidence plus archive headroom before starting.
Do not omit candidate tensors or outputs to fit a smaller disk. In the hosted
execution environment used for this work, `/dev/shm/hepta-v4` is visible across
escalated commands only; default sandbox commands see a different filesystem
view. This is an environment-specific storage fact, not a model requirement.

When the archive will be built on another filesystem, add
`--archive-headroom-dir /absolute/path/existing-archive-directory`. The directory
must already exist. The runner compares actual filesystem device IDs (`st_dev`),
not path names. With two different devices, the evidence filesystem and archive
filesystem must each have at least the full uncompressed payload estimate plus
64 MiB free. With the same device, or when the option is omitted, the original
requirement remains twice the payload estimate plus 128 MiB on that device.
Two directories on one device cannot count the same free space twice. The
total reservation is unchanged, and `storage.json` records both locations,
devices, observed free bytes and requirements. This is a preflight check, not
an allocation of disk space. Build the complete archive directly in the chosen
archive directory; do not first create a second archive on the evidence device.

## B. Rebuild under a new receipt and reproduction commit

A new compiler, build path or environment can produce different executable
bytes. Use a separate branch/worktree from the same frozen implementation, keep
the scientific protocol and native source/dependency bytes unchanged, and write
a truthful new build receipt in that worktree. Preserve the original receipt at
its original commit and with the original evidence. This recipe performs a
build; it does not claim that old test results describe the new executable.

```bash
git worktree add -b reproduction/ndu-v4-local /absolute/path/v4-local-build \
  "$NDU_V4_COMMIT"
cd /absolute/path/v4-local-build
export NDU_V4_BUILD=/absolute/path/v4-new-native-target

python - <<'PY'
import hashlib, json, os, platform, subprocess, time
from pathlib import Path
repo = Path.cwd()
path = repo / 'experiments/multimodal_output_portfolio/v4/evidence/native_build_final.json'
original_bytes = path.read_bytes()
original = json.loads(original_bytes)
sha = lambda data: hashlib.sha256(data).hexdigest()
for section in ('source_sha256', 'dependency_source_sha256'):
    actual = {name: sha((repo / name).read_bytes()) for name in original[section]}
    if actual != original[section]:
        raise RuntimeError('registered native source/dependency drift: ' + section)
source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
target = Path(os.environ['NDU_V4_BUILD']).resolve()
command = ['cargo', 'build', '--locked', '-p', 'codex-hepta-ndu',
           '--bin', 'ndu-modality-portfolio', '--target-dir', str(target)]
started = time.perf_counter()
completed = subprocess.run(command, cwd=repo / 'codex-rs', check=True)
build_wall = time.perf_counter() - started
binary = target / 'debug/ndu-modality-portfolio'
receipt = {
    'schema': 'hepta-v4-native-reproduction-build-v1',
    'parent_recorded_build_receipt_sha256': sha(original_bytes),
    'native_source_commit': source_commit,
    'preregistration_commit': original['preregistration_commit'],
    'source_sha256': original['source_sha256'],
    'dependency_source_sha256': original['dependency_source_sha256'],
    'binary': {'path': str(binary), 'sha256': sha(binary.read_bytes()),
               'bytes': binary.stat().st_size},
    'command': command, 'command_cwd': str(repo / 'codex-rs'),
    'exit_code': completed.returncode, 'build_wall_seconds': build_wall,
    'platform': platform.platform(),
    'versions': {tool: subprocess.check_output([tool, '--version'],
                cwd=repo / 'codex-rs', text=True).strip() for tool in ('rustc', 'cargo')},
    'tests_executed_by_this_build_step': False,
    'scope': 'New local reproduction build; no original-binary or production attestation claim.'
}
path.write_text(json.dumps(receipt, indent=2) + '\n')
PY

git add experiments/multimodal_output_portfolio/v4/evidence/native_build_final.json
git commit -m "Record native build for independent v4 reproduction"
```

Use `"$NDU_V4_BUILD/debug/ndu-modality-portfolio"` as the runner's binary and a
new output directory. The runner records the new commit; do not relabel it as
the original source freeze. A new binary also needs a new four-action fixture
for independent audit, using the existing fixture script and a new directory:

```bash
python experiments/multimodal_output_portfolio/v4/bridge_development.py \
  --binary "$NDU_V4_BUILD/debug/ndu-modality-portfolio" \
  --checkpoint "$NDU_V4_SOURCE_RUN/seed-17/ndu-model.pt" \
  --checkpoint-sha256 40af186981d3d102362be76886f383aacdbad1d8992a9262f33760c991814082 \
  --output /absolute/path/new-v4-four-action-fixture
```

Do not reuse an old fixture as evidence that a different binary executed its
neural/ACK lifecycle. Additional validation, when performed, needs its own actual
commands and outcomes. Rust tests use the repository wrapper, scoped to this
binary: `just test --locked -p codex-hepta-ndu --bin ndu-modality-portfolio` from
`codex-rs`. Never substitute a build-only receipt for executed tests.

## Independent audit and interpretation

The coordinator verifies source/binary/checkpoint provenance, independently
replays the finite neural tree and online trajectories, checks the native
transcript, and recomputes statistics. Its output must be a new file outside the
run directory; auditing must not rewrite the producer's evidence.

```bash
python experiments/multimodal_output_portfolio/v4/evidence/audit_confirmation.py \
  --repo "$PWD" \
  --run "$NDU_V4_REPLAY" \
  --source-run "$NDU_V4_SOURCE_RUN" \
  --native-binary "$NDU_V4_BINARY" \
  --bridge-fixture "$NDU_V4_FIXTURE" \
  --output /absolute/path/new-v4-independent-review.json
```

For route B, substitute its new binary and fixture paths. A development audit
also requires `--allow-development`; it remains nonconfirmatory. A coordinator
exit status of zero means provenance and numerical/evidence checks passed.
Mechanism acceptance and statistical superiority are separate Boolean fields;
valid negative scientific results can pass the evidence audit. Violations of
source hashes, execution, policy or budget contracts fail the audit.

The primary comparison is dynamic versus the strongest enumerated initial-state
committed plan. Myopic is a separate descriptive comparison. Confidence
intervals pair arms within each registered condition/initial-pattern stratum
and condition on the three fixed checkpoints; checkpoints are not resampled.
Fresh nuisance and innovation draws revisit known semantics and known finite
support. They do not test new classes, new disturbance support, natural data or
the distribution of training runs. Conditional root certainty equivalents are
averaged; this is not one certainty equivalent over a mixture of checkpoints.

## Preserved evidence and failures

| Output | Interpretation |
| --- | --- |
| `run-receipt.json`, `runtime-start.json` | Attempt status, runtime and full metered work; `completed` alone does not assert scientific acceptance. |
| `source-manifest.json`, `source-end.json`, `protocol.json` | Committed source-byte binding, start/end equality and exact scientific contract. |
| `seed-*/checkpoint.json`, `encoder-contract.json` | Pinned inherited model and executed clean-condition encoder checks. |
| `seed-*/tree.npz`, `policy.npz`, `planning.json` | Actual full candidate states/outputs, compiled values/plans and complete search cost. |
| `seed-*/worlds.npz` | Registered raw inputs and external evaluation metadata. |
| `seed-*/<arm>/outputs.npz`, `latents.npz`, `control.npz`, `traces.jsonl.gz` | Actual emissions, observed latent history, costs and native-bound actions. `observed_count` distinguishes executed states from unused storage slots. |
| `seed-*/<arm>/scores.npz`, `summary.json` | External scoring after emission and causal execution summary. |
| `native-transcript.tsv.gz`, `native-receipt.json` | Exact request/response stream, sealed-session counts, binary hash and native timing. |
| `model-work.json`, `report.json`, `artifacts.json` | Phase ledgers, registered comparisons and immutable artifact hashes. |

Every attempt uses a new directory; an existing destination is rejected before
it is changed. Once a new attempt starts, exceptions retain available raw
outputs, partial states, logs, tracebacks and hashes. Storage preflight provides
headroom but cannot make forced process termination or storage failure
transactional. Preserve failed directories and assign a new attempt name;
do not delete unfavorable results, overwrite an attempt or continue an interrupted
run as if it had completed. Scientific changes require a recorded amendment
before a new confirmation; implementation fixes do not authorize retuning the
registered gates after inspecting results.
