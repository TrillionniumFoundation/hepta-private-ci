# v4 trajectory entry contract audit

Source: `4ed40f768e466b3e526e25e9ac4da8f43cffecd8`, tree `04f4ce70b6b79c0158efd4874386534efdf26034`, draft #3609; parent #3607 `cb97779e6f4ff361b5c1988523cb4dea87974ad4`.

## Finding

No fresh-episode entry vulnerability was established. `execute` is a low-level trajectory simulator whose implementation charges only the suffix after caller-supplied state. The repository call sites found are tests in test_portfolio.py and test_reallocation.py; no external untrusted adapter or verified checkpoint importer was found. `full_outcome_audit`, `evaluate`, and `evaluate_dependence` explicitly require step-zero roots. State shape checks do not authenticate history.

The supplied counterexample was reproduced on the exact parent: activation cost 5, max_units_per_step 1, risk_aversion 0, cost_shadow_price 0, seed 0; fresh state `(levels=(0,2,2,2), remaining=10)` costs 10, while step 1/mask 1 costs 5 with first control cost 1. The latter state is also reached by a real `advance` from remaining 16 after action `(1,0,0,0)`, shock 0, charged 6. Full prefix-plus-suffix cost is 11; reporting suffix 5 as total episode cost would be a misuse. `baseline.txt` retains the concrete records.

Change: document caller-owned continuation provenance and invocation-only cost scope in execute docstring and README; add three regressions for the counterexample, paid successor accounting, and full-episode audit guards. No new boolean, credential/provenance fiction, or restriction on legal paid successors. Portfolio executable AST equals the parent's after removing only execute's docstring, preserving conditional_ce and #3607 state protections. Three remote files were byte-verified against reviewed local files.

## Validation

Linux x86_64, Python 3.12.14, Ruff 0.15.13; standard-library tests, no dependency changes. On exact final source, full v4 69 tests passed; scoped Ruff, compileall, whitespace checks passed; just fmt reported no Rust files requiring formatting. Independent full three-file review found no blocker, independently ran three added tests, and recorded source hashes in the accompanying manifest. Review diff SHA-256: `e76d6f3fe744c8193087ea93bc009f014e0fc21040dfc7531752f170b4f3539a`.

```sh
python -m unittest discover -s experiments/multimodal_output_portfolio/v4 -v
/workspace/verification-3567/pyenv/bin/python -m ruff check experiments/multimodal_output_portfolio/v4/portfolio.py experiments/multimodal_output_portfolio/v4/test_execute_boundary.py
python -m compileall -q experiments/multimodal_output_portfolio/v4
/workspace/cargo/bin/just fmt
git diff --check
```

All commands ran from the source repository root. `exact-head-tests.txt` contains the final run. Original contract review and reproduction remain separate from the final review.

Hosted [finite-portfolio CI run 40033269012](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40033269012) passed. Job 120686474463 actual logs verify checkout and `verified-source-head=4ed40f768e466b3e526e25e9ac4da8f43cffecd8`, 69 tests passed and compileall completed successfully. Complete logs are preserved in `hosted-ci.log`. Parent CI was not transferred. Broad architecture/blocking-ci/v8-canary checks were still queued at this observation; no rerun was requested.

## Limits

This is a documented trust/accounting boundary, not an authenticated resume implementation or proven security fix. A fabricated nonzero step remains accepted by the low-level helper; callers must not use it to admit untrusted fresh episodes or attest earlier payment. Seeded suffix execution does not restore prior RNG state. Costs are modeled integers, not physical energy/latency/independent observations. No Rust/native-runtime/full-workspace/other-platform acceptance or scientific/model qualification is inferred. No provider calls, new credentials, merges, deployment, or gate weakening. Preserve DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO.
