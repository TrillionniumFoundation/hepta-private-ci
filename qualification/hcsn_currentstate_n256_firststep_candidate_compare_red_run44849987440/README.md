# N256 first-step candidate comparison RED originals

This evidence-only package preserves the terminal RED from the single frozen
comparison attempt in pull request #6819. It does not change the candidate
source and must not trigger another numerical execution.

- source commit: `a3373921a0193336837d217c24d0d35dccd9a5ad`
- source tree: `78269de8c2a7eb695cc76bd3c8eab55f38096922`
- workflow run: `44849987440`
- numerical job: `136678793301`
- artifact: `14684118589`
- artifact ZIP SHA-256:
  `a922989c369eddf6685f273334fcad5d02b464a1cec21607f98d9f1f400ccf0a`
- unique execution key:
  `hcsn-n256-firststep-candidate-compare-hosted-20261120-c06d-001`

## Result

The job passed checkout, exact runtime installation, source/oracle freeze
verification, and the source-only controls. The one numerical child then
failed while constructing the first extended sparse matrix:

```text
ValueError: unrecognized csr_matrix constructor input
```

The frozen candidate supplied a one-dimensional tuple to
`scipy.sparse.csr_matrix` under SciPy 1.17.0. This is an actionable source/API
defect. It is not an OOM and it is not a numerical-tolerance failure.

The child started and terminated after 0.837712323 seconds with maximum RSS
76,568 KiB. The cgroup originals report zero OOM and zero OOM-kill events.
Because the exception occurred before the child wrote its numerical result and
counter record, the actual number of dynamic steps and exponential actions
performed by this attempt remains **UNKNOWN**. The admission limits of one
candidate dynamic step and two candidate sparse exponential actions are not
reported as executed counts.

No candidate capsule or coordinate comparison was produced. Qualification
therefore remains false. Historical RED, OOM, cancelled, and UNKNOWN records
remain unchanged, and global `all_closed` remains false.

## Scope

This package is a zero-model, evidence-only readback. It does not rerun the
oracle, candidate, model, Torch, or optimizer; it does not repair #6819; and it
does not grant N256 dynamic, full-state, migration, full-network, C2 replay,
HPCA, production, or adoption qualification.

