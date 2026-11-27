# S81 resource migration V2: controls and observed resource failures

**HOLD. No V2 plan has been frozen. Formal task fits and task optimizer updates are zero.** This directory preserves the actual failed resource qualification and the separate hardware diagnostics. It does not publish a successful GPU qualification or claim task benefit.

The source in `../../resource_migration_v2/` is an independently identified, prospective freezer and verifier for the fixed S81 mechanism study. Its five files preserve all 42 source pins of the [original frozen V1 plan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/e5dc735b316888eab617b05f5c365f905992e63b/qualification/hcsn_regenerative/studies/s81-20261107/plan.json). A valid new plan would need all 47 pins and its own complete actual execution evidence. The resource amendment is retained as its original pre-execution registration; the later outcome in `RESOURCE_EXECUTION_STATUS.json` does not rewrite it.

## Why this branch exists

V1 passed its numerical qualification and was published before formal task training. Its first formal provider request was then rejected during the ownership preflight, before any SaveKernel call. The original ledger remains HALTED with 20 reserved and zero ever-claimed fits. It is not cleared, recovered or counted as executed here. The independent V2 proposal used another configured account only after that account's complete owned inventory passed the original guard.

V2's actual first qualification reached provider COMPLETE but failed its initial capability check: the process had a CPU-only Torch distribution and did not establish CUDA. All following 11 qualification stages were skipped, including the registered 400-update non-task probe. The frozen-plan entry point was then exercised with the actual failed native receipt and all returned artifact bytes; it rejected them and produced no plan.

Separate, bounded hardware-only diagnostics subsequently failed to establish a usable NVIDIA runtime on either checked alternative account. These diagnostics inspect device/driver visibility and installed-package metadata; they do not import Torch, train a model, read task data or supply numerical qualification credit. Observations about a later diagnostic container do not retroactively describe the first failed qualification container, and they do not establish a platform-wide cause or a count of physical host GPUs.

The second account's diagnostic also exposed a notebook-name normalization mismatch: the original request contained a doubled hyphen, whereas the sole SaveKernel response named a single-hyphen notebook. The original adapter receipt remains UNKNOWN. A separate read-only audit verified the returned object's authenticated owner, exact kernel/version, source and artifact identity; it did not resubmit the request or change the original ledger. Choosing a compatible request stem in a future registration would address that naming defect, but would not repair the observed lack of a usable GPU.

## What the new controls verify

The freezer requires the exact native producer, request, source and immutable artifact bytes; a successful, no-skip twelve-stage execution; all eight scientific qualification slots; the actual S81 operator bundle; and all original numerical and execution gates. It compares the proposed plan against the original plan and permits only explicitly declared resource, identity and fresh-evidence differences. Original model code, arms, data, seeds, statistical thresholds and budgets remain fixed.

The registered scientific budget remains ten arms, two tasks, four independent training seeds and two learning rates: 160 fits with 400 optimizer updates each. The 81-state representation and 2,890 trainable parameters are unchanged. Statistical selection groups remain separate from provider jobs, and the twenty-comparison family and .01 MSE useful-difference threshold are unchanged. These are registered requirements, not executed quantities in V2.

`CONTROL_TEST_RESULT.json` records 14 actual control-only tests with zero failures, errors or skips. `INDEPENDENT_CONTROL_REVIEW.json` is the separate source and provenance review, including its precise limits. Neither record is a GPU qualification, a mathematical rerun, an actual plan freeze or training evidence.

To run the control-only suite from the repository root:

```bash
python -B -m unittest qualification.hcsn_regenerative.resource_migration_v2.test_resource_migration
```

## Evidence and decision limits

`RESOURCE_EXECUTION_STATUS.json` binds the actual attempts and raw audit evidence by SHA256 and separates provider, adapter, diagnostic and scientific status. Original receipts, failed outcomes, skipped stages, naming uncertainty and costs remain retained. Raw private operator evidence is not copied into this public directory.

There is no `plan.json` or qualification ZIP in this publication. Any future compute route requires its own prospectively identified resource policy, actual complete numerical qualification and verified plan publication before task training. This branch does not authorize an existing owner's restart or an unknown request's replay.

The original frozen 170-run campaign and the separately completed Hepta × NDU study remain separate. V2 contributes no completion credit to either. Physical energy and provider charges that were not measured remain unknown; nested wall times are not added. External task benefit, old-capability retention and complete cost gates remain unestablished, so expansion remains HOLD.
