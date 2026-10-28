# Pair the original Hepta lane with the reviewed Chain CI corrections

This successor starts directly from the published Hepta source
`2bfceaa3226611a72f43d24e67d13e30091c7449`. It preserves that source and its
original failure observations. It does not claim hosted or model-owner acceptance.

## Exact paired source

| Identity | SHA |
| --- | --- |
| Chain source | `ac469237422d43805845e8b9a6839ad14e1028e7` |
| Chain base | `57c1ed545d067937cbd7aaa7570d5f22123265e6` |
| Actual GitHub PR 506 prospective merge | `47727c4f8335427710b4f3608768b4e9cc7c2a64` |
| Source, actual merge and canonical merge tree | `aa000d8883cbffdf0ac4fbfb57b63394693c99c6` |

The retained [native pair receipt](chain506-ci-repaired-native-pair.json) records
the actual fetched GitHub object, ordered `[base, source]` parents, canonical
merge-tree equality and exclusion of the isolated blocked M06 implementation.
The coordinator also checked the PR tuple before and after fetching. These
identity checks are not an execution or security acceptance receipt.

## Original failure and exact correction

In original [run 40491440610](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40491440610),
all four Linux lanes failed step 28. Each ran the original 86 Python reader and
rejection tests: 83 passed and three failed because fixed mock expectations
still described four native executions while the original runner had five.
Model preparation, FinalUse and holdout steps 49–52 were skipped in all four
Linux lanes. The two Windows ledger jobs succeeded; they do not establish a
Linux model result. Complete decoded logs and their source-bound hashes are
retained separately with the Chain work-package evidence.

The paired Chain corrections reproduce those three failures, then repair only
the fixed expectations. All original 86 tests subsequently pass locally. The
runner's five selectors, nonzero/ignored/zero-match refusals and native budgets
remain unchanged. The same Chain source supplies the reviewed Host wrapper and
refreshes eight missing paths using the original embedded-source generator.

This Hepta workflow changes only the two Chain pin lines and the single original
from-zero subprocess invocation. After the original `cd ../chain`, it runs:

```sh
python3 scripts/ci/run_from_zero_host.py -- python3 scripts/ci/run_from_zero_native.py --out "$RUNNER_TEMP/pon-pair/chain-from-zero-native"
```

The original `RUSTUP_TOOLCHAIN=1.95.0`, working directory and output path remain
unchanged. The wrapper preserves that explicit toolchain selection and uses
the original root-owned `trnmponpublic.slice`: 25% CPU, 2 GiB memory, zero swap
and 256 tasks. Only this subprocess enters that parent; the remaining protocol
and model steps are unchanged. The entire original Python subprocess, including
its build, runs there. Original 60/900/90-second child limits, native deadlines,
the 60-minute job limit, exact test selectors and zero-retry policy are retained.

The wrapper refuses unavailable, preexisting or changed Host context. Readiness
observations cannot grant chainwork, task acceptance, model installation or
production authority. The A03 campaign's separate 4-CPU/16-GiB contract is not
substituted or widened by this change.

## Validation boundary

[Local static validation](local-static-validation.json) checks the complete
workflow delta against its published parent and runs the existing nine SmolLM
Python wiring/refusal controls. The retained output is
[the original test log](local-smollm-static.log). No Hepta Rust, Cargo, Bazel,
FinalUse or model-owner execution was run locally. All actual hosted outcomes,
including failures, skipped steps and timeouts, remain required evidence.

The earlier controlled Cell experiment remains a measured `NO_UPDATE` result.
This successor does not promote it to the original Hepta native install path,
independent future-task efficacy, open-network availability or WAN acceptance.
