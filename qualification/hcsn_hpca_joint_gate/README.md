# One-source HCSN and HPCA research checks

This source assembly takes #6107 as its first parent, adds the disjoint phase
transport files from #6108, selects the complete C2-successor subtree from
#6106, and the complete HPCA-neuroscience subtree from #6109. Its extra Git
parents retain the input histories. Existing HCSN operator/contract blobs
were compared between the input branches and are identical. No mathematical
operator is silently replaced by an older parent during this assembly.

MANIFEST pins the 20 source files required by these particular checks. Every
listed local Git blob was compared with the exact upstream tree before
publication. The runner launches the checks again on this assembly; earlier
per-branch PASS reports are not accepted as inputs. It requires the declared
19 spatial/phase, 33 C2 terminal, 15 normal HPCA and 15 optimized-Python HPCA
test executions, without skipped tests. The spatial and phase probes also
execute, with before/after source guards and complete output streams.

The local final attempt completed all 82 test executions and both probes.
These are repeated structural/mechanism checks, not 82 independent tasks,
model evaluations, or scientific replications. C2 tests compile the actual
controller function from its AST using synthetic fixtures; checkpoints in
these fixtures remain opaque. HPCA reparses already-retained outputs and
executes zero model forwards. The spatial and phase primitives are still
separate mathematical models, even though their tests run on one source.

The first invocation and the stricter counter-checking successor invocation
are retained separately under evidence/joint-source-20261112. Tests preceded
formatting; normalized AST equivalence is recorded. New hosted CI checks the
actual published source and remains a separate receipt.
Large spatial arrays are stored as deterministic `.json.gz` archives;
ARRAY_ARCHIVES.json pins both compressed and original byte identities.

This closes only the ambiguity of combining test claims from distinct source
trees. It does not qualify the complete HCSN model, original 14,336-position
continuation gate, independent full C2 training replay, external HPCA evaluator,
calibration, retention, baseline superiority, full costs or production.
Those fields remain false in every generated report. No deployment or model
adoption is authorized by this research check. Status: HOLD_NO_GO.

```bash
python -B qualification/hcsn_hpca_joint_gate/run.py --output /path/to/new-directory
```
