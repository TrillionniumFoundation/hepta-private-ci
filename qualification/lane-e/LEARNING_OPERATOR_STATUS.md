# `learning.operator` evidence status

The repository distinguishes three facts:

1. **Mapped source/test identity** — a function or test exists and is
   connected to a requirement.
2. **Candidate execution** — a literal command ran for an exact SHA/tree
   and ended in pass, fail, or timeout.
3. **External acceptance** — independent efficacy, target-host,
   promotion, canary, and release evidence.

No tracked file is called “latest” or treated as an execution receipt.
The `Learning operator exact-source diagnostics` workflow emits
`status.json` in each diagnostic artifact. Every record contains the
exact candidate SHA/tree, environment, command, duration, terminal
state, and log filenames. Commands are executed independently, so an
earlier lint failure cannot turn later tests into silent skips.

A source-producing automation commit is not itself an execution
receipt. GitHub suppresses recursive workflow execution for pushes made
with the workflow installation token; qualification therefore requires
a directly authorized push or explicit dispatch bound to the resulting
candidate SHA. An `action_required` run with no jobs is also missing
evidence, not a failed or passing gate.

Artifact families:

- `learning-operator-source-<sha>`
- `learning-operator-rust-<sha>`
- `learning-operator-merge-<sha>-<base>`

A missing artifact or command record is missing evidence, not success.
The performance profile is diagnostic evidence only; it is not
independent acceptance.
