# Calendar V2 target-host fault matrix

This matrix is the qualification contract for `automation.taskflow` Calendar V2.
It does not convert source/unit-test success into deployment or release evidence.
Every retained receipt MUST bind the exact repository commit/tree, Cargo.lock,
Agentd and automation artifact digests, host identity, tzdb identity and test
profile. A source-only fixture MUST NOT satisfy a target-host row.

## Invariants

1. A claimed occurrence freezes the schedule revision and canonical UTC instant.
2. Updating a schedule never rewrites an already-materialized occurrence.
3. One logical occurrence has one deterministic occurrence identity across owner
   restart and scheduler takeover.
4. A stale scheduler generation cannot materialize or terminalize work.
5. DST gap/overlap policy is explicit; local wall-clock ambiguity never selects a
   hidden default.
6. A tzdb update can affect only future materialization under the admitted
   revision/profile; it cannot reinterpret history.
7. Queue admission is not TaskFlow/effect completion.
8. Unknown external effects remain unknown across timer/scheduler recovery.

## Required retained identity

Each target-host run records:

- repository commit and tree;
- `codex-rs/Cargo.lock` digest;
- Agentd and `codex-hepta-automation` artifact SHA-256;
- host/OS/architecture identity;
- IANA tzdb source, release/version and content digest;
- schedule ID and immutable schedule revision;
- timezone ID, gap policy, overlap policy, missed-run policy and overlap policy;
- scheduler Agent/generation/fencing identity;
- deterministic occurrence ID and canonical UTC instant;
- backup/restore source digest when applicable;
- start/end timestamps and measured latency/resource observations.

## Matrix

| ID | Scenario | Fault / transition | Required observation | Forbidden outcome |
| --- | --- | --- | --- | --- |
| CAL-TZ-01 | ordinary future occurrence | no fault | exact local→UTC projection and deterministic occurrence ID | implicit system timezone |
| CAL-TZ-02 | spring-forward gap | nonexistent local wall time | declared gap policy produces skip/shift/reject exactly as registered | silently choosing an arbitrary instant |
| CAL-TZ-03 | fall-back overlap | duplicated local wall time | declared overlap policy selects the registered occurrence(s) with stable IDs | merging two admitted occurrences or inventing one |
| CAL-TZ-04 | tzdb refresh before future materialization | old→new IANA profile | future occurrence uses newly admitted profile/revision only | mutating already-materialized history |
| CAL-TZ-05 | tzdb refresh after claim | profile changes while occurrence is claimed | claimed occurrence retains frozen revision/profile/UTC identity | re-resolving the claimed local time |
| CAL-RACE-01 | two schedulers see same due row | simultaneous claim | exactly one current fenced claim; loser observes contention/no work | duplicate occurrence |
| CAL-RACE-02 | scheduler A claims then crashes | lease expires; B takes over | B recovers same occurrence/client identity under successor fence | new occurrence identity |
| CAL-RACE-03 | A resumes after B takeover | stale generation/fence | A is denied before mutation | stale terminalization or dispatch |
| CAL-RACE-04 | schedule revision races due claim | update vs claim | claim binds exactly one immutable revision in one owner transaction | mixed old/new schedule fields |
| CAL-RST-01 | owner restart before queue admission | process loss | same durable occurrence resumes from awaiting-admission | duplicate queue submission without reconciliation |
| CAL-RST-02 | owner restart after queue admission | acknowledgement retained/unknown | queue/turn reconciliation follows original identity | treating queue acceptance as terminal success |
| CAL-RST-03 | restart with unresolved provider effect | provider outcome unknown | occurrence remains indeterminate/reconciliation-required | timer retry creating a new external effect |
| CAL-BKP-01 | backup then restore same tzdb | clean restore | exact schedule/occurrence identities and checksums survive | history renumbering |
| CAL-BKP-02 | restore onto host with different tzdb | profile mismatch | startup/qualification fails closed until admitted tzdb profile is available | silently using host-local tzdb |
| CAL-CAP-01 | due backlog exceeds bounded catch-up | capacity pressure | missed-run/catch-up policy and limits are enforced deterministically | unbounded loop/backlog expansion |
| CAL-CAP-02 | per-owner work quantum exhausted | scheduler pressure | work defers without changing occurrence semantics | dropping due work as success |
| CAL-END-01 | end boundary / recurrence exhaustion | final legal occurrence | no occurrence after registered end/exhaustion | one extra recurrence |
| CAL-CANCEL-01 | disable/cancel concurrent with claim | lifecycle race | current transaction/fence determines one durable state and replay is idempotent | half-applied enable/claim state |

## Multi-scheduler execution protocol

A qualification harness SHOULD run at least two independent scheduler processes
against the selected owner database/host contract. It MUST inject process loss
between: lease acquisition, occurrence materialization, durable TaskFlow step
preparation, queue admission, turn persistence, provider dispatch and terminal
projection. Recovery always uses the original durable identity; the harness must
fail if a second logical occurrence or provider key is created merely because a
process generation changed.

## tzdb provenance

A qualifying timezone profile is not just a timezone name. The retained profile
binds the IANA release/version, source digest and the exact transitions used for
the tested horizon. The harness tests one ordinary timestamp plus at least one
gap and one overlap in a zone that actually exhibits those transitions in the
bound tzdb release. If the selected target zone has no transition in the tested
window, a second qualification zone with real transitions is required.

## Exit criteria

Calendar V2 may be marked target-host qualified only when every applicable row
above has a retained PASS receipt on the same immutable candidate and no required
row is represented only by a mocked clock, synthetic timezone table or
single-process unit test. Independent acceptance, activation and release remain
separate gates.
