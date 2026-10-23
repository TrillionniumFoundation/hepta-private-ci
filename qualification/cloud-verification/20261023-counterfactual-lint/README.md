# Counterfactual audit lint closure

Base #3612 exact `b168b8d05959b4e9a4956fc3122364f2b59cc1fe`. Draft #3613 exact source `bfe1bf6369055b614e06d15a7b05f15df695898c`, tree `38c660fdc264ade32805574ad4f304ddc32586c3`. Remote source bytes match independent review; exact-source local rerun passed all 76 tests, scoped Ruff, compileall, whitespace and formatting applicability checks. Only counterfactual_audit.py changes: remove unused portfolio.actions import (F401), replace the local dynamic_policy lambda assignment with an equivalent nested function (E731). No global waiver, audit assertion deletion, experiment conclusion change or unrelated module edit. Search/history inspection found no reusable existing fix for this combination.

Raw AST necessarily differs. After only removing that unused import and normalizing that lambda assignment to a named function with identical arguments and return expression, the complete ASTs match. Complete paired_nominal_shift return dictionaries match the exact baseline for risk coefficients 0, 0.5, and 1e-8. Existing full tests include adverse shift outcomes, numerical extremes, nominal fresh-state admission and legitimate paid continuation. No assertions or tests were removed.

Local full v4: 76 passed. Scoped Ruff now passes with both recorded failures closed. Compileall and whitespace checks pass; just fmt reports no Rust files needing formatting. Independent review and its executed tests are attached. Original Ruff failure is preserved. Linux x86_64, Python 3.12.14, Ruff 0.15.13; no dependency change.

Commands from source root:

```sh
/workspace/verification-3567/pyenv/bin/python -m ruff check experiments/multimodal_output_portfolio/v4/counterfactual_audit.py
python -m unittest discover -s experiments/multimodal_output_portfolio/v4 -v
python -m compileall -q experiments/multimodal_output_portfolio/v4
/workspace/cargo/bin/just fmt
git diff --check
```

The accompanying semantic-check log records the restricted AST normalization and full-output comparison. Hosted finite-portfolio run 40039697579/job 120707603916 passed. Actual logs verify `bfe1bf6369055b614e06d15a7b05f15df695898c`, 76 tests passed and compileall succeeded; full receipt is hosted-ci.log. Parent CI was not transferred. Broad checks remain queued at observation; no reruns were requested.

This is finite source maintenance, not physical-cost, model-performance, native-runtime or scientific qualification. Preserve DRAFT / SHADOW_ONLY / DENY_ALL / HOLD_NO_GO. No provider calls, new credentials, merge, deployment, or gate relaxation. Whole repository/Rust/platform tests are outside this one-file change.
