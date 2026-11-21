# N256 list-row candidate strict bitwise RED originals

This evidence-only package preserves the terminal RED from the separately
frozen SciPy 1.17 list-row candidate in pull request #6823. It does not alter
the source branch, relax the preregistered bitwise gate, or authorize another
execution.

- source commit: `c0fb79ba896d3d4fb30a58ea40ce33d757ac9658`
- source tree: `cd2487c63d31e7abce3ea4bfd13a4e8e312163bf`
- workflow run: `44851931235`
- numerical job: `136685046474`
- artifact: `14685796500`
- artifact ZIP SHA-256:
  `6323e8494359b42e11639afd3033d90c7fa86bbb057b824aefae49799ecb4ef5`
- unique execution key:
  `hcsn-n256-firststep-candidate-listrow-repair-hosted-20261120-c06d-001`

## Result

The source/oracle freeze, five normal plus five optimized source-only controls,
and the single zero-model SciPy 1.17 list-row constructor probe all passed. The
frozen numerical child then completed its admitted work: one dynamic step and
two sparse exponential actions. It produced a 560,358-byte candidate capsule
with SHA-256
`248cfc56d575b15d4a8340267e8b668fd0b6dc94be71b61e2b0cec8b913981b1`.

The 69,728 coordinate identities matched, but 1,291 values were not bitwise
equal to the archived independent dense oracle. The maximum absolute error was
`0x1.0600000000000p-50`, the summed absolute error was
`0x1.b78520bb26befp-47`, and the maximum ULP distance was 335. The original
gate required bitwise equality, so this is a real numerical **RED** and is not
converted into a pass by the small absolute error.

The child returned 0 after 0.902504958 seconds with maximum RSS 123,856 KiB.
The parent then raised `RuntimeError: candidate/oracle bitwise gate`. Ancestor
cgroup originals report zero OOM and zero OOM-kill events.

## Scope

The evidence review performs zero model, candidate, oracle, Torch, optimizer,
expm, or dynamic executions. The hosted run performed exactly one candidate
dynamic step and two sparse expm actions, zero oracle re-executions, zero Torch
calls, and zero optimizer steps. Qualification and global `all_closed` remain
false.

This does not grant later-cycle or arbitrary-history continuation, N512,
finite-domain, full-network, task-benefit, asynchronous-cost, C2 full replay,
HPCA external-custody, production, or adoption qualification. Both earlier
constructor REDs and every other historical negative and UNKNOWN record remain
unchanged.
