# ui.native branch-protection contract

This file records the required repository-administration settings for the
canonical branch `work/ui-native-qualified-integration-20260928`. It is a
reviewable contract, not evidence that GitHub has already enabled the settings.

## Required settings

- Require a pull request before merging.
- Require at least two approvals, including the `ui-platform` CODEOWNER and one
  independent security/release reviewer.
- Dismiss stale approvals when the head changes.
- Require review of the most recent push.
- Require conversation resolution.
- Require the branch to be up to date before merging.
- Require status check `ui.native / qualification result`.
- Require signed commits when organization policy and bot identity support it.
- Block force pushes and branch deletion.
- Do not allow administrators or automation to bypass required checks for
  product-source changes.
- Do not grant the qualification workflow write permission.

## Merge identity

The qualification workflow checks the exact candidate head and a deterministic
working-tree merge in this order:

1. exact canonical base SHA;
2. exact candidate head SHA.

A new base, head, workflow, lock file or source byte invalidates prior evidence.
The PR may merge only when GitHub reports the required aggregate check for the
current head and current base.

## Administrative closure

Repository administrators must enable these settings through GitHub branch or
ruleset administration and attach the resulting ruleset identity to
`QUALIFICATION_MANIFEST.json`. Until that evidence exists, branch protection is
an open qualification item and all release flags remain false.
