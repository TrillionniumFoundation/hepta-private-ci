# Empty Matrix restart projection

An admitted release without a Matrix command reaches the no-companion branch on
every supervisor tick. Previously each visit rewrote the same empty Matrix
restart projection, including the canonical record's temporary file, file sync,
atomic publication, and directory sync. The daemon performs this synchronous
work while holding its existing supervisor mutex.

The private companion slot now remembers a successful empty projection only for
its current release. The first visit still uses the complete existing writer.
An unchanged release can skip later identical empty publications. No active
release, a configured Matrix command, or a failed publication invalidates the
acknowledgment. A recovered Supervisor always starts without an acknowledgment.
The real Matrix restart budget, main-process pending domain, canonical codec,
journal format, file permissions, and all lifecycle fences stay unchanged.

The main restart writer preserves the companion domain. Release catalog and
lifecycle writes use different files, and registration refuses an existing
Agent. The acknowledgment is local to one Supervisor instance; it does not
detect external removal or replacement of the journal by another actor.

Five authored controls use real temporary registries, admitted releases, the
existing fake process driver, and actual canonical journal writes. They cover
unchanged ticks and main pending preservation; failed writes followed by repair;
failure after changing releases and return to the old release; reopen and stale
window cleanup; and two genuine configured-companion restart attempts. An old
mtime on the test-owned record detects an atomic rewrite without sleeping.

The retained Intel failure reached `stage=agent_e_drain method=Drain` and then the
existing supervisord read timeout. The log does not measure mutex wait or disk
latency. Removing a deterministic redundant write is not proof that it caused
that observed timeout. The client budgets, assertions, process protocols, and
test timing remain unchanged. These new controls are authored only; source and
format checks do not establish native or performance qualification.
