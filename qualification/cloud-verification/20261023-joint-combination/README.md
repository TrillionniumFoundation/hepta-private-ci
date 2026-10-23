# v4 nominal-state combination audit

Base #3609 `4ed40f768e466b3e526e25e9ac4da8f43cffecd8`; donor #3608 `25194eb730bd64fbfcf0275cefbf033c7dae0770`; shared ancestor #3607 `cb97779e6f4ff361b5c1988523cb4dea87974ad4`. Repository searches and recent open PR inspection found no existing combined draft. This source branch excludes native/media changes. Published draft #3612 source `b168b8d05959b4e9a4956fc3122364f2b59cc1fe`, tree `785997f524e837287906560c95d05f671ef7d435`. All four remote source files were byte-verified and exact-source full v4 rerun passed 76 tests; source worktree clean. Independent review diff SHA-256 `41b3a2574681e4b8258cd82da8b8ca3522f0a66fe2e044fbfe900a3746e14fc6`.

## Contract and reproduction

JointState declares `generation: State`; that nominal type owns level/budget/step/mask admission. Ordinary immutable namedtuples did not pass its constructor but were accepted structurally. On the exact base, activation cost 5 / zero risk gives initial charge 6 and total modeled cost 10 for a valid State, versus charge 1 and total 5 for a step-zero namedtuple carrying active_mask=1. This differs from #3609's legitimate paid step-1 continuation. The original records are preserved in baseline.txt.

The donor preimage matches the combination base. Reuse its JointState isinstance check and four regression tests; donor tests are byte-identical. Adjacent fresh-only evaluate/evaluate_dependence and full_outcome_audit also accepted structural roots (including a structural outer JointState), with the same 10-to-5 counterexample. Add short-circuit nominal checks at these three fresh audit boundaries and three tests. Ordinary subclasses inheriting admission, hypothetical prior values, and paid successors remain accepted. execute and its continuation contract are unchanged.

Against the exact base production files, the seven new regression methods fail with five failed subtests and seven errors; the complete negative log is retained. On the combination all 76 v4 tests pass. portfolio.py, existing numerical tests, root-custody tests, README and execute-boundary tests were checked byte-for-byte unchanged from #3609. This is nominal API admission, not protection against arbitrary Python mutation, hostile subclasses, forged isinstance behavior or authenticated checkpoint provenance.

## Verification commands

Linux x86_64, Python 3.12.14, Ruff 0.15.13; no dependency change or external supplier call. From source repository root:

```sh
python -m unittest discover -s experiments/multimodal_output_portfolio/v4 -v
/workspace/verification-3567/pyenv/bin/python -m ruff check experiments/multimodal_output_portfolio/v4/joint_evidence_generation.py experiments/multimodal_output_portfolio/v4/test_joint_generation_admission.py experiments/multimodal_output_portfolio/v4/test_fresh_audit_admission.py
/workspace/verification-3567/pyenv/bin/python -m ruff check experiments/multimodal_output_portfolio/v4/counterfactual_audit.py
python -m compileall -q experiments/multimodal_output_portfolio/v4
/workspace/cargo/bin/just fmt
git diff --check
```

The first scoped Ruff command passes. Counterfactual Ruff fails with two existing diagnostics: unused `actions` import (F401), assigned `dynamic_policy` lambda (E731). Exact baseline and final logs confirm these unchanged failures; no lint waiver or unrelated fix was introduced. Compileall/whitespace pass; fmt reports no changed Rust files requiring formatting. Independent complete four-file review and hashes are included. Published-source rerun and hosted exact-source logs are recorded separately; sibling CI results are never added together as combination acceptance.

## Scope limits

Four source files only: two production files and two regression files. This closes identified nominal fresh-state admission gaps, not real physical spending, model effectiveness, source independence, native execution or scientific qualification. No new trust boolean, required-gate change, provider connection, credentials, merge or deployment. Preserve DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. Full repository/Rust/platform validation is not performed. Existing lint debt and broad CI status must remain explicit.
