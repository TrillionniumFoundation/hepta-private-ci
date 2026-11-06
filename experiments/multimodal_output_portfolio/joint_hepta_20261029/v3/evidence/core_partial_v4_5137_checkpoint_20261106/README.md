# Core partial custody and attempt 5137 evidence

This immutable additive packet preserves 101 original files and
1,029,716 bytes. It contains the reviewed partial-evidence
collector, its unchanged scanner and positive gate, the original 21 custody
model checks with their first failed attempt, format checks, independent and
root reviews, strict A5/B4 publication identities, and the actual terminal
result of run 42291611782, attempt 1, job 128146186898.

The actual seven-case run failed with exit 100. Five cases each passed once
with actual child `test ... ok` output, JUnit, and no original in-test macro
skip. Two Guardian cases failed both original attempts. The background case
observed zero terminal notifications where one was required. The single-request
case observed no Guardian request; its recorded parent tool output reported
exit code 134 with empty output. That code belongs to the single-request case.
It does not identify the background case's tool exit, an OS signal, or a unique
historical cause. All first and final failures in the accepted bytes remain.

The original artifact contains 18 accepted originals plus its manifest. Only
`logs/list.stderr.log` was rejected, for `URI_UNRECOGNIZED_FRAGMENT`. Its bytes
were never obtained and are not reconstructed, transformed or replaced. The
complete nineteen-original qualification remains false. Individual observed
passes do not change that result or qualify either Guardian case. Retries are
attempts in one run, not independent samples.

Parent `logs/run.stdout.log` has zero bytes. Real child stdout appears in
nextest sections inside the unchanged parent `logs/run.stderr.log` and JUnit.
The separate immutable stream clarification records this distinction. The
original source, tooling, command, list and runtime evidence are preserved;
no scanner, model or product test was replayed to build this packet.

The administrative workflow log is retained locally by its recorded identity,
but excluded here because it was not accepted through the original artifact
scanner. The audit preserves only its already approved finite stage and case
diagnostics. Replaying the audit's administrative-log parsing additionally
requires that original GitHub log. No excluded administrative raw output is
encoded into this packet. The official accepted artifact and all its original
members are included without changes.

Earlier candidate manifests retain their source-only statuses and dates. The
model checks exercise custody with injected scanner decisions, not native
behavior or a changed credential environment. The recorded original ambient
scanner rejection is retained. Earlier 5114 and 5127 failures and prior
18-20b, 21-22 and reporter packets are unchanged and not repeated. Later
prerequisite analysis, v5 source and other suites are outside this packet.

## Restore

```sh
python -O restore.py /absolute/path/to/bundle /absolute/path/to/new-destination
```

The archive is 116,992 bytes with SHA-256 `a86cd4a88d72463d1593761e29fb898e77bf1b0f8808b2b683cd1912719bf8b5`.
It is transported as 1 bounded single-member gzip container(s),
each at most 450,000 bytes. The reader is identical to the reviewed reporter
v3 reader except its two fixed seals. Historical transport filenames retain
the original prefix. It rejects an existing destination, unsafe paths,
duplicates, extra members, invalid modes and malformed containers. It writes
nothing into the input bundle and executes no archived code. Exact original
bytes and safe regular permissions are restored; ownership and timestamps
are not restoration targets. INDEX records original and restored paths.
External reviews are mapped under the supplement input directory.
