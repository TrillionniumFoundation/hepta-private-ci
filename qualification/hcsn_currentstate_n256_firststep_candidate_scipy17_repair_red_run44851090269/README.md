# N256 SciPy 1.17 repair RED originals

This evidence-only package preserves the terminal RED from the separately
frozen SciPy 1.17 repair candidate in pull request #6821. It does not alter the
source branch or authorize another execution.

- source commit: `8bf624203ad1266082ae52a2ae2ebdc96dc90036`
- source tree: `1327078f9f39706c5f8ec7d585c73d3d061094f3`
- workflow run: `44851090269`
- numerical job: `136682353885`
- artifact: `14685257001`
- artifact ZIP SHA-256:
  `6866e32f050cdd5e1b7cef7e4b60d771d325de48bd21582d3e61f20ed9209eb1`
- unique execution key:
  `hcsn-n256-firststep-candidate-scipy17-repair-hosted-20261120-c06d-001`

## Result

The source/oracle freeze and all five normal plus five optimized source-only
controls passed. The numerical child then failed at the same first extended
sparse-matrix construction. SciPy 1.17.0 also rejects a single nested tuple as
a `csr_matrix` constructor input:

```text
ValueError: unrecognized csr_matrix constructor input
```

This means the one-line repair hypothesis was false. It is not an OOM or a
numeric-tolerance result. The child returned 1 after 0.769557359 seconds with
maximum RSS 76,036 KiB. The ancestor-cgroup originals report zero OOM and zero
OOM-kill events.

No candidate capsule, coordinate comparison, or numerical result/counter file
was produced. Actual executed dynamic steps and exponential actions therefore
remain **UNKNOWN**; admission maxima are not counted as work performed.
Qualification and global `all_closed` remain false.

## Scope

This package performs zero model, candidate, oracle, Torch, optimizer, expm, or
dynamic executions. It preserves the failed identity and does not grant N256
dynamic/full-state, migration, N512, C2 replay, HPCA, production, or adoption
qualification. The earlier #6819 RED and all other historical negative and
UNKNOWN records remain unchanged.

