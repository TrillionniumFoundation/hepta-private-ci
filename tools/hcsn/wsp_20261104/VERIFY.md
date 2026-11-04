# Independent acceptance and reproduction

Run each new experiment in a new output directory. The retained results,
protocols and candidate identities must not be overwritten by a rerun. The
research directory is named by its UTC date; report prose also records the
America/New_York date explicitly.

## 1. Verify the published package

From this directory, a standard-library-only check verifies every public file's
SHA-256, size and membership:

```sh
python verify_public_package.py
```

With the NumPy/SciPy versions recorded by `joint/requirements.txt` and its
environment receipt, the deeper check verifies retained numerical results,
reconstructs the finite transition tables, checks the Belief repair and exact
infeasibility certificates, verifies all 625 direct-value candidate records and
their selection/gating statistics, verifies the analytic bypass and its disclosed
overlap, checks the final 49-parameter compilation and matched-objective solver
records, and runs the capacity-bound synthetic boundary tests:

```sh
python verify_public_package.py --deep
```

These commands perform no new policy search, language-model generation or
private trading-data evaluation. Passing them verifies the shipped evidence;
it does not change a failed task-value qualification into a pass.

## 2. Reproduce the public policy experiments

Follow `joint/README.md` to recover the original inputs from the pinned public
repository archive. `acquire_inputs.py` supports an existing local checkout,
an already downloaded archive, or the pinned public HTTPS parts. It verifies all 3,550 archive members and
refuses divergent identities. Use `strict_replay.py` for the explicit-reference
numeric execution. The original full training is separate from this head-edit
experiment and is not silently charged as zero.

For the second, exploratory experiment, follow `exploratory_belief/README.md`.
Use `prepare_frozen_continuation.py` to reconstruct the five exact old candidates
before running `evaluate_followup.py`; this removes a dependency on old timing
fields or platform-specific re-solving. The original and exploratory protocols
remain separate. B-only rejection, raw candidates and gated fallbacks all remain
visible in the retained result files.

The third experiment is the separately frozen direct task-value grid in
`ndu_value_grid/`. It edits only three continuation biases of the previous C,
retains every candidate and gates against that same C. Follow its README to run
the driver into a new directory with the exact original inputs and old-head
snapshot. The record verifier does not execute that driver or generate worlds:

```sh
python ndu_value_grid/verify_value_grid.py --study-root joint \
  --old-heads exploratory_belief/OLD_CONTINUATION_HEADS.json.gz
```

The original VAL set was reused after its earlier role in choosing C. The 320
new test worlds were generated only after all five new choices and VAL decisions
were frozen. Neither reused validation nor repeated exploratory contrasts are
described as externally preregistered confirmatory evidence.

The exact fit71 verifier needs no original runtime. If rebuilding its evidence,
pass the relocated constructor directory explicitly as `--source-dir` pointing
to this package's `joint/` directory; the frozen build helper's historical default
refers to its original delivery directory. Do not silently change the frozen
constructor or coefficients to fit a result.

For a rebuild, select a new directory explicitly:

```sh
python exploratory_belief/exact_certificate/exact_box_certificate.py build \
  --source-dir /absolute/path/to/wsp_20261104/joint \
  --directory /absolute/path/to/new-certificate-output
```

The analytic Belief bypass is a separate execution-graph control in
`analytic_belief/`, with zero new checkpoint weight edits. Its two record checks
are included in `--deep`, and can also be run directly:

```sh
python analytic_belief/verify_analytic_belief.py --study-root joint \
  --old-heads exploratory_belief/OLD_CONTINUATION_HEADS.json.gz
python analytic_belief/verify_seed_overlap.py --study-root joint
```

The second check passes **with disclosed reuse**: 64 of the 320 schedules match
an earlier study's other fit. It verifies the overlap receipt; it does not assert
that the other schedules are globally unseen. Keep the complete denominator and
read the raw positive effects together with the failed aggregate gated
qualification and `SEED_OVERLAP_ERRATUM.md`.

The final `analytic_belief_compile/` experiment changes the actual 49-parameter
Belief row in the existing execution graph. Its fitting targets are the original
TRAIN rows' own-model analytic probabilities, not Oracle posterior labels. It
compares a fixed direct solution with projected gradient descent reaching the
same declared numerical Frank–Wolfe gap tolerance. The two retained-record
checks are included in `--deep`:

```sh
python analytic_belief_compile/verify_belief_compile_records.py \
  --study-root joint --analytic-root analytic_belief
python analytic_belief_compile/verify_belief_solver_records.py \
  --study-root joint --analytic-root analytic_belief
```

These checks verify the stored problem, solver residuals and exact stored-weight
norms, published parameter recipes and recorded serialization evidence, paired
gates, statistics and chronology. They do
not perform another fit, model forward or test-world generation. The experiment
checked all 320 generated schedules against its 1,616 registered unique historical
schedules before any test score. Unavailable formal-confirmation content and
unknown external histories remain outside that statement. Follow the package
README to reproduce the frozen experiment into a new output directory; do not
overwrite its original run or use its test observations to tune a replacement.

## 3. Reproduce the runtime and MIT experiments

`QUALIFICATION.json` identifies the companion runtime commit and test evidence.
Use that exact commit, its documented toolchain, and the commands in
`docs/native-weight-guard.md`. The explicit PyTorch integration test requires an
existing Python environment and is intentionally excluded from ordinary ignored
test selection; it was separately executed for this delivery.

The MIT bundle's `acquire.py` obtains hash-pinned public source inputs, including
the original environment implementation. `verify.py` checks the retained results;
`audit_and_replay.py` performs fresh MinAtar episodes. Its Qwen array audit and
export checks are distinct from complete generated-answer evaluation. Consult
the companion `qwen_feasibility/` record for the remaining generation blockers.

`native/README.md` supplies the actual-head MCP driver commands. Public Hepta
numeric input is bundled under `joint/fixtures/`. Fixed-row native acceptance is
not a whole-policy task evaluation.

## 4. Conditional access for the actual Trader data

The exact Current100k fixture contains private feature rows, labels and weights.
It is excluded from both public repositories. An authorized independent reviewer
must supply the file matching `pocket4/private_input_manifest.json` before
recomputing its real-data audit, capacity certificate or native replay.

The public capacity implementation and synthetic boundary tests are independently
reviewable without that file. They cannot independently reproduce the private
data's numerical bound. This access condition is an explicit unclosed part of
public independent acceptance.

The source-ledger diagnostic patch is provided and separately checked, but it is
not deployed. The original unknown outcome and denominator are unchanged. No
reviewer should use a shorter ledger, guessed zero-fill or an immature future
window to mark the prospective experiment complete.
