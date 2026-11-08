# S0–S5 evidence review input

`CURRENT_INPUT.json` records the available evidence inventory for the six-stage
research route. The input preserves absent joint configuration, protocol and
foundation as `null`, and keeps the experiment registry empty.

## Run

From the repository root, choose a new output path outside the checkout:

```bash
python -B scripts/hepta_cell_research_gate.py \
  qualification/cell-research-stages-20261108/CURRENT_INPUT.json \
  --source-root . \
  --artifact-root qualification/cell-research-stages-20261108 \
  --output /tmp/hepta-cell-research-review-20261108.json
```

Exit zero means a review report was written. Missing evidence remains visible
in its blockers. Output files are create-only.

## Evidence and its scope

The four inventory files listed below are byte-for-byte copies. Their sizes and
SHA256 values are bound in the input; the original records retain their own
identities. Additional source provenance is recorded separately in that directory.

| Evidence | Use in this review |
| --- | --- |
| `github_state_20261108.json` | Current-turn projection of native GitHub observations, including exact `6ddfca24` CI runs and separate research refs. |
| `hcsn_mechanism_summary_20261108.json` | HCSN CPU mechanism qualification, failed-attempt preservation and explicit numerical/scientific limits. |
| `previous_compute_and_science_6ddfca24.json` | Prior compute/source accounting and unresolved joint-freeze, owner, budget and scientific requirements. |
| `ace_current_byte_binding_20261108.json` | Existing causal-helper source bindings and remaining A/C/E implementation/evaluation gaps. |

Inventory hashing checks the copied bytes. Referenced transitive artifacts and
original remote services require their own verification. Historical stage
numbers, thresholds and results remain in their original scopes; this input
does not reinterpret them as S0–S5 experiments or prospective registration.

## Remaining inputs

The current route still needs a shared frozen version/model/data/budget
configuration, its original registration, and original trajectory, source,
recovery, successor-consumption and evaluator-owner evidence. Paired experiments
need complete admitted-attempt denominators, strong baselines, retained-ability
measurements and complete costs under that same binding.

This entry point reviews reproducibility and descriptive numerical consistency.
`research_advancement`, `production_qualification` and `authority_granted` remain
false; independent owner authentication, scientific acceptance and adoption
remain outside its authority. This inventory introduces no numerical thresholds.

## Validation history and CI repairs

`VALIDATION.json` and its original receipts describe the initial gate delivery.
Their source hashes and failed attempts are retained as historical evidence.
They do not qualify a later commit merely because it descends from that source.

`validation/ci-review-b86dcb2a.json` records the exact `b86dcb2a` CI observations:
the dedicated gate tests passed, the architecture source lane passed, and the
broader blocking workflow failed. It preserves the distinction between the
source head and GitHub's merge checkout, including checks that never executed.

The follow-up repairs address inherited Python formatting, the actual `inout`
crate name in the spelling dictionary, and three groups of test fixtures:
reading locked state through the original file handle, reconstructing cold
resume environments from the persisted rollout, and resolving the bubblewrap
fixture through the existing Cargo/Bazel binary resolver. Original assertions,
trust checks and dependency advisories retain their force.

`FOLLOWUP_VALIDATION.json` indexes the repair inputs, individual native attempts,
formatting and their scope. A native Linux pass does not establish Windows or
musl behavior. A recorded CI failure remains a failure even if a later bounded
attempt passes. None of these implementation checks supplies the missing
matched-budget scientific experiments or advances an S0–S5 stage.

## Original copy sources

- GitHub: `/workspace/scratch/304d47497d18/audit/github_state_20261108.json`
- HCSN: `/workspace/scratch/0cbd0d20fc48/hcsn_execution/candidate/qualification/hcsn_differentiable/evidence/20261108/summary.json`
- Compute/science: `/workspace/scratch/34e7fd019a13/evidence/final_report/compute_and_science-6ddfca24.json`
- A/C/E: `/workspace/scratch/cf0b0141e32e/candidate/qualification/cell-causal-abcde-20261108/ACE_CAPABILITY_AUDIT_CURRENT_BINDING.json`
