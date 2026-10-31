# Acquired-information broker, version 6

The policy-side `Broker(data_path, work_root, scope)` never opens the private
dataset. A distinct subprocess loads it with `allow_pickle=False`, owns the
inherited actual `ArtifactTransport`, and serves strictly sequenced JSON lines.
The data pathname and opaque case identifiers are orchestration metadata, never
model features. Same-UID hostile isolation is not claimed.
Execution scope is a POSIX research host with directory fsync, tested on Linux;
Windows portability requires separate qualification.

## Public interface and state machine

- `start(index, arm)` returns exactly `initial`, `residuals`, `variances`,
  `repair_cost`, `wait_cost`, `wait_variance`. It performs inherited Round4
  `acquire`: actual initial text/PNG delivery, noisy observation and public cost
  readbacks. No target, latent domain, raw dataset ID or future sensor is sent.
- `wait()` is permitted once in an active case. Only this request acquires the
  second sensor through `acquire_wait`; it appends its actual residual and
  variance and charges the public wait cost exactly once.
- `finish(choice, repair_amount=0)` accepts only terminal `stop` or `repair`.
  Stop requires amount zero; repair amount is finite within [-8,8]. Actual final
  text/PNG delivery and reread precede its response. Repair charges its public
  cost. Response fields are `delivered`, `cost`, `transport`,
  `final_readback_ns`; they contain no target or score.
- A new case may begin only after the previous case is terminal. Each
  `(index, arm)` is accepted once. Duplicate wait, postterminal operations,
  unknown request fields and invalid domains are refused before task mutation.
- `close()` records whether every started case reached a terminal result.
  Closing an unfinished/failed broker reports `complete=false`; it does not
  manufacture a final action or score.

Client `case_dir` and `case_id` expose artifact identity to the study driver;
only the six-field dictionary enters model methods. One persistent broker serves
sequential cases. Use a fresh work root. `EvidenceZip.append(case_dir, prefix)`
may archive and remove a completed case immediately; the persistent transcript
remains outside the cases directory. No pending or incomplete case is resumable
by this version; preserve its evidence and use a separately named attempt.

## Durability, receipts and independent scoring

Inherited ArtifactTransport writes and decodes real disk artifacts but does not
itself fsync them. The broker adds file and directory fsync, then rereads each
artifact's bytes against its inherited receipt digest before releasing public
information. Thus `final_readback_ns` is after the added durable byte reread,
while inherited transport timestamps retain their original scopes.

`BROKER_TRANSCRIPT.jsonl` has a SHA256 predecessor chain. Each accepted operation
also writes `cases/<opaque hash>/PUBLIC_TRANSITIONS.jsonl`. Records include the
request, acquired public state, exact transport receipt slice, accrued costs,
state digests, response and monotonic record time. Rejections record request
digest/keys and unchanged task state. Targets, latent domain values and
unacquired observations never appear in these records. Private targets remain
in the separate input dataset for an independent scorer **after the policy
worker exits**; broker code never computes or releases a target-based score.

The broker enforces the causal program interface, not encrypted storage,
privilege separation, whole-system crash atomicity or hostile-process secrecy.
Readback/IPC/fsync/process costs are measured by outer run receipts separately
from physical wait/repair costs. Failed I/O poisons the broker and retains
partial evidence; it cannot continue producing qualified task results.

The four dev-only tests use actual subprocesses and real text/PNG artifacts,
independently decode final PNG bits, forbid client `numpy.load`, verify the
transcript chain, exercise refusal without artifact/state changes, and archive
then continue with another case. No formal study data is used.
