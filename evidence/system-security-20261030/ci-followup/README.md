# Original CI follow-up observations

This attachment preserves original observations associated with Hepta parent
`f874d948a38c119e57b1368adab79437956acd78`. It is not a new status authority,
development plan, evidence registry, waiver, qualification profile or production
acceptance decision. It does not establish that a later published commit passed
hosted CI.

The Chain artifact observations belong to source
`24b265834daea34947adbb5903d887e3f6043838`; the merge configured in the Hepta
parent was `db139b5ef964509318de12974ed0d0cea7b02737`. These are retained execution
and configuration identities, not assertions about a later remote HEAD or a
final cross-repository pair. Original source identities inside receipts are
never replaced with a newer commit.

The follow-up configuration points to Chain source
`a38d770966c65ad34c9d5e55f3c2917c2e3bda0f` and merge
`52a3c9d614281897dd5a6adeb3576a8acfb1ee82`. This configuration is recorded
separately from the older artifact executions. No retained 24b/db139 or f874
execution is retargeted to those new identities, and this attachment does not
claim that the new configured pair has passed its native gate.

## Retained material

`index.json` records each original member's source path, byte length, SHA-256,
archive location and scope. For execution JSON, selected original fields are
copied without deriving a new outcome. The complete original JSON or log remains
inside its archive. `selection.json` lists the exact retained inputs.

| Archive | Scope |
|---|---|
| `caller-proof-local.tar.gz` | Original stale-marker failure, superseded candidate snapshots and controls, final exact-source-pin controls and original-verifier counterfactuals. |
| `caller-proof-independent.tar.gz` | Independent seven source-drift counterexamples, their original failing observations and the final source-pin review. |
| `root-followup-checks.tar.gz` | Formatter, AST comparison, read-only verifier, development-doc verifier, buildifier and original Bazel query records. |
| `final-source-observations.tar.gz` | Final formatter mutation, exact AST comparison, stable format check and the configured pair's canonical-merge receipt; no new native execution. |
| `hosted-hepta-baseline.tar.gz` | Selected original f874 hosted failure logs and compact Windows action-log readback; no action replay. |
| `windows-wrapper-history.tar.gz` | Original wrapper RED, retained 65-control candidate and the later review RED. |
| `windows-wrapper-final.tar.gz` | Subsequent 66-control Python wrapper execution, narrow patch and independent review; no native Windows compilation. |
| `chain-codeql-review.tar.gz` | Full 780-finding triage, source-bound review notes and the bidirectional b23-to-24b result-index mapping. |
| `chain-sarif-originals.tar.gz` | Original b23 and 24b SARIF ZIP inputs and original metadata. |
| `chain-raw-history.tar.gz` | Compact and full-cost readbacks of the original 24b raw-History artifacts, artifact references and source diagnosis. |
| `latest-readonly-observations.tar.gz` | Complete original f874 musl log, bounded failure triage, dated Actions snapshot and static a38 pair-compatibility review. |

Additional completed observations can be appended as another explicit selection
file. Earlier results and source snapshots remain historical inputs. In
particular, a superseded candidate's passing tests do not qualify the final
implementation.

## Scope of the results

The original caller-proof gate failed on a stale `verify_strict` marker already
present in the baseline. Final local source-pin controls are retained together
with the original failures and the failed exploratory scope checks. Their
passing observations predate a formatting-only change to the Python verifier;
`hepta-followup-format-ast-equality.json` records the exact before/after hashes
and AST equality. The later complete verifier, documentation check and format
check have their own original records. The formatter run that changed source
retains its recorded `source_stable=false`, even though its process exited zero.
Exact source hashing does not prove runtime signature security or post-quantum
qualification.

The specified plasticity fixture's direct dependency query completed after the
system-trust retry. A separate direct-label query of the listed production and
other-test targets also completed. **Both attempts to query the complete
transitive production-to-qualification path failed with `No space left on
device`.** Their exit codes and logs are retained; direct-label results do not
prove transitive non-reachability, and no Bazel compilation result is inferred.
The original trust-related query failure is retained as well.

The Windows wrapper records distinguish the original 3-test run with one
failure, the superseded 65-control candidate, the 9-test review run with eight
failing subcases, and the subsequent 66-control Python run. The compact spawned
action readback belongs to the original hosted merge. Neither the local wrapper
controls nor that readback establish a successful native Windows rebuild.

The final formatter changed only
`.github/scripts/test_run_bazel_native_msvc_toolchain.py`, from SHA-256
`31d418ebe69fe482baf47e8369e09a5ab3ed8aef0cbd8141c57c2e24c17456fc`
to `925d8366e9954d858d3ef9e2ee88fa4452bc8b0b59acb301d5588ffc5bfd71e9`.
`hepta-ci-followup-final-format-ast-equality.json` records recovery of the exact
tested source from the retained patch and equality of the complete Python AST,
including constants. The wrapper source remained at
`2f47b73ff9d39fba2216be940adac80954aeea92c989af6668c3934b56069067`.
The formatter's exit-zero/source-unstable record is retained unchanged; the
separate format check records a stable pass. These are formatting and source
equivalence observations, not another test run or native Windows rebuild.

The original f874 musl hosted summary reports **234 of 607 actually executed**,
with **397 passed including cache hits, 1 failed to build, 26 failed remotely,
and 183 skipped**. The three narrow caller-proof, fixture-dependency and Windows
wrapper fixes here do not resolve all 26 remote failures; those failures remain
under triage. This attachment does not claim that all blocking jobs are fixed.

The 24b raw-History readback retains the original failed criteria: strict missed
three-round completion in all nine phases; the resource-fence workload completed
business and complete-State checks in all nine phases, while its six hostile
phases lacked the required actual paid-credit depletion. Business completion is
not pressure qualification. The full raw-History ZIPs are referenced by their
original IDs and digests in the readbacks, rather than duplicated here.

The CodeQL comparison preserves all 780 emitted findings and maps original
indices in both directions before applying prior review notes. The original
`passed`, extraction-coverage and official-security-qualification results remain
false. Review classifications do not waive the original gate or establish the
safety of code absent from extraction.

## Storage and reproduction

Archives contain unchanged original bytes. Tar metadata and gzip timestamps are
fixed for reproducibility. Every output file is strictly smaller than 512,000
bytes. Large JSON is compressed inside the archives, not shortened. The large
raw-History and Windows execution ZIPs are not duplicated; their retained
readbacks identify the original artifacts.

Read members without changing them:

```sh
tar -tzf caller-proof-local.tar.gz
tar -xOzf chain-codeql-review.tar.gz \
  quantum-review-b23c/codeql-b23-production-triage.json
```

To rebuild from the same retained inputs, extract the archives into an empty
scratch directory and run the included script. Output is intentionally limited
to a new directory below the supplied validation root; the script never copies
into repository evidence or publishes anything.

```sh
python3 assemble_ci_followup.py \
  --validation-root /absolute/retained-inputs \
  --selection selection.json \
  --readme README.md \
  --output /absolute/retained-inputs/rebuilt \
  --source-checkout /absolute/hepta-checkout
```

The optional checkout argument records the nine current source-file hashes and
checks that they did not change during assembly. It does not retarget earlier
test logs to those bytes. A preview assembled without that argument has a null
source observation. Repeated `--selection` arguments append explicit supplemental
inputs; the assembler rejects duplicate members, changing inputs and oversized
output blobs.

The dated Actions readback and full original musl log remain in
`latest-readonly-observations.tar.gz`. Actual provider/TaskFlow passes are
separated from cached targets. Six old PoN process tests retain their ENOENT
failures; the specific missing executable is not proved by that log. Cognitive
and supervisord failures remain unassigned, including the possibility of a
shared-store effect. Same-byte test sources alone do not exclude a regression.
The a38 review verifies immutable Git identities and retained component evidence;
it does not execute the new pair or qualify the whole chain as post-quantum.
