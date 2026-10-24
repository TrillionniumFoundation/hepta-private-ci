# Restore existing native presentation runner-context correction

Parent: #3662 `c0da06846a4d01dfc939a88ecc3c6df877606eac`, tree `98970c1ac4024a4c61f2428b150c4204e70e1574`.

## Proven source defect, not a guessed hosted diagnosis

The workflow puts `runner.temp` in `jobs.native-presentation.env.CARGO_TARGET_DIR` (original line387). GitHub's official context-availability table excludes `runner` from job-level env, while allowing it for step env/run. Official actionlint1.7.12 independently rejects exactly that expression (exit1); the fixed workflow returns exit0. External shellcheck/pyflakes integrations were disabled, so this is workflow schema/expression validation, not their lint coverage.

This same workflow blob `1c73dec75f5bfec113b7c2fb9df0759bd5cbcc94` occurs at #3619 `332d8b448758ad45e516a208d940f2358f888e32`, #3649 `0ec18791d970190578b55234036f3a30dc7d560b` and `103bb2011629d12c658b7004d3a4a163a548df02`, and this parent. Native test additions did not introduce the defect. The earlier #3617 source has no such workflow, not a successful baseline for it.

An exact existing correction was found in #3499: source `87b38cc0509a3050d5c03d433de6a1da79b4018f`, evidence head `299ae385c8991f5de50fa6f94d8d406278c50b37`. This patch reuses its initializer line and original binding step, not the donor's unrelated file changes. #3153 has the same class of correction for a different workflow.

## Minimal behavior-preserving change

Remove the invalid job-env expression and use the existing source-binding step to append CARGO_TARGET_DIR to GITHUB_ENV using the real RUNNER_TEMP. The value remains `<runner temp>/native-presentation-target`. The step does not consume that variable; all consumers occur later, after GitHub applies GITHUB_ENV. No new job/step, reusable workflow call, trigger, matrix, permissions, secret/environment access, runner, dependency, timeout, cancellation or directory permission changes. Directory creation and target path behavior remain unchanged. No XDG settings were touched.

## Local validation

- Before actionlint: exit1, one illegal-runner-context expression diagnostic.
- After actionlint: exit0, with the same flags/tool.
- Parsed YAML comparison: exactly two scalar changes; three jobs and pull_request-only trigger unchanged, no job-level reusable workflow references.
- Bash syntax checks for all30 run scripts passed.
- Complete original source-binding script executed in a fresh Git fixture with spaces in RUNNER_TEMP/GITHUB_ENV. Exported path, following-step consumer, HEAD/tree and original-lock hash evidence all match. It does not create the Cargo target directory earlier than before.
- Existing source/merge regression target output retained separately; see its exact exit/log.
- No Rust or UI product build performed for this workflow-only correction.

## Hosted failure evidence boundary

The monitor previously observed exact-head UI push failures with no jobs: #3652 run40065631978, #3653 run40065957644, #3654 run40066747769 and #3662 run40069990679. The source only declares pull_request, not push; admission-time validation failure is compatible with this pattern, but source inspection cannot prove why GitHub recorded those events or establish the unique server-side cause. No service annotation was obtained. A normal workflow-history collection query was rejected by the connector, so no earlier successful hosted baseline is claimed. Denied check-suite/check-runs routes were never retried or bypassed.

This repair closes the independently demonstrated static-expression defect only. New exact-head hosted runs must actually create jobs and pass their intended checks before the historical zero-job admission blocker or product validation can be marked closed. Existing queued runs were not rerun/cancelled. Draft only, no merge/deployment.

## Sources and reproducibility

- GitHub official contexts: https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability
- Environment deployment:false is explicitly valid, not a proposed removal: https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/deploy-to-environment
- Existing donor: https://github.com/TrillionniumFoundation/hepta-private-ci/pull/3499
- Official actionlint release: https://github.com/rhysd/actionlint/releases/tag/v1.7.12
- Linux amd64 release archive SHA256 verified against release API digest: `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`.

Commands: actionlint -shellcheck= -pyflakes= BEFORE_OR_AFTER_WORKFLOW; python3 verify_workflow.py before.yml FIXED_WORKFLOW; from the exact repo, python3 -m unittest discover -s scripts -p test_ui_product_foundation_ci.py -v. Python3/PyYAML6.0.3, Bash and Git are used by the local checker. PyYAML's YAML1.1 representation of on is explicitly handled; actionlint supplies workflow-specific expression validation. The checker is an evidence driver, not a newly installed CI gate.
