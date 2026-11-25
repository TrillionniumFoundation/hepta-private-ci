# Original paired operation preparation

This engineering component prepares one operation in the existing production
writer journal after the original protected turn owner verifies the requested
human statement. It does not read training materials, issue a FinalUse grant,
dispatch an effect, or qualify real participant enrollment or adoption.

Trusted composition may explicitly install it with
`AgentdConfig::with_original_paired_preparation`. The original Notes thread
runtime and production writer must already be installed. The default is absent;
the installer rejects a host that already has the paired material destination.
No startup path installs this component automatically. Its channel has one
queued request slot; the owner may separately be processing one request. Each
request shares one ten-second deadline across queueing, verification and journal
preparation, and listens to cancellation of the existing required runtime.

The durable operation ID depends only on the original delivery. The exact study,
enrollment commitment, purpose statement, requested operation, material
commitment, principal, policy generation, original route and human verification
revision/expiry are retained in the payload and semantic identity. Changing
these fields cannot create a second slot for that delivery. Admission uses the
existing writer's SQLite transaction and compare-and-swap checks for the
operation, event and outbox records.

The typed response distinguishes a fresh preparation, an observation of the
original retained record, and an unknown acknowledgement. It exposes no queued
receipt, verified-turn token, grant, material bytes or continuation. Before any
new preparation, the required runtime reuses its existing Core, AuthBus replay,
Root human owner and exact-purpose verification path. An identical retained row
is read before attempting that path again. Restart, a lost reply, cancellation,
and an unknown effect therefore retain the original record; none automatically
replays, rebinds or dispatches it. A retained response reports historical state,
not renewed human permission.

The native CI selector is `test(paired_preparation::tests)` with a minimum of
eight executed controls. They use explicitly synthetic writer authority and
metadata with real temporary SQLite journals: repeat, changed semantics,
restart, concurrent admission and unknown state, writer revocation, cancellation
after commit, caller loss after commit, and invalid/full/closed/expired lanes.
The existing ten original-turn controls remain a separate gate. These are new
engineering tests; they do not spend or qualify the frozen E1–E6 experiments.

Production material use still needs a real paired material target, frozen
material custody and enrollment owner, independent Root policy registration,
and a fresh human fence at the actual material-use boundary. No Notes grant or
synthetic fixture substitutes for those owners. The existing Python engineering
scope refusals remain in force. No production dispatch is enabled by this stage.
