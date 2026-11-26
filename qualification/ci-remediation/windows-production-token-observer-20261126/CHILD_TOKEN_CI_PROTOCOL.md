# Child-token observation record validation

This layer extends the existing production-observer controller. It leaves the
eight commands, original two exact test identities, strict Clippy invocation,
twenty-minute job budget, zero retries, source and binary before/after binding,
and first-nonzero-exit behavior unchanged. It does not add a workflow or run.

Before the original production-token record verifier runs, the controller
separately validates the single `HEPTA_LEGACY_SPAWN_TOKEN` record from the same
native stdout and stderr. Only records before the first nextest Summary in
each stream count; later failure recaps cannot create extra observations.
Missing, duplicate, oversized, malformed, unknown, overlapping or multiply
captured observations remain incomplete and add an explicit controller error.

The record is bounded to 16 KiB including its prefix and newline. Its exact
field sets, numeric types and ranges, primary token type, fixed generic role
names, array counts and 64-entry limits are checked. Duplicate JSON keys and
unexpected fields, including raw SID fields, are rejected. The two snapshots
are validated independently. Their comparison fields must be booleans with a
consistent aggregate. The four comparisons whose complete fields are visible
(token type, integrity RID and attributes, mandatory policy, and privilege
LUID/attribute tuples) must match those fields in both directions. A true raw
group or restricting-SID equality also requires equal visible counts and
attribute sequences. Two empty raw SID arrays must compare equal, since no
hidden identity remains in an empty array. True raw-user equality requires
equal user attributes.
Role summaries never establish raw SID equality or inequality. A false raw-SID
comparison may therefore coexist with identical redacted summaries. Consistent
recorded disagreement is accepted; equality is not required for completeness.

This validation does not reinterpret either test verdict. An observed child
token cannot convert a failing filesystem assertion into success, and an
unknown child observation cannot replace the original native or Clippy exit.
The existing factory-token and SD record checks remain byte-for-byte intact.
All observations continue to declare production confinement unqualified.

The companion Python controls exercise accepted equality and disagreement,
malformed and incomplete records, bounds, duplicates, failure recap exclusion,
and preservation of original failure exits. They are parser controls, not
Windows tests. An archived-log check, when the separately supplied original
e127 log directory is present, demonstrates that the old two failures remain
recognized and that those old logs provide no new child-token observation.

No Rust compilation or native execution is claimed by these controls. A later
normal push must bind the reviewed source and actual selected binary and retain
the complete original logs regardless of either test outcome.

The first parser candidate passed its initial structural controls but accepted
eight independently supplied contradictions between complete visible facts
and comparison flags. That unexecuted version, its original control results,
and the counterexamples are retained in the evidence. This revision adds the
cross-checks above without changing any native command or source observer.
