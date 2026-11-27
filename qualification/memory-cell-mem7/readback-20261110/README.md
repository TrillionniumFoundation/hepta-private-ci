# MEM7 retained and hosted evidence readback

Decision: **HOLD / NoUpdate**. This branch preserves previously unpublished
MEM7 execution evidence and independently verifies the original hosted results.
It changes no actor, model, owner, workflow, feature flag or production default.
Its source base is `9385535e683b97058fedeee490c6ff921652f793` (PR #5787),
not the separate common P0 integration candidate.

## What is newly established

The original MEM6 revocation campaign reused a snapshot that update had already
invalidated. The separately frozen MEM7 campaign instead proves that the updated
fact and its rebuilt dependency chain are readable, revokes that fact, then reads
the **same snapshot** through fresh processes. Its original local execution has
14/14 passing scenarios, 14 distinct reader PIDs and three exited writer PIDs.
This readback verifies all 156 retained files (316,435 bytes), the original 154
indexed entries, the five implementation files against Git, request/response
bindings, snapshot identity, generation increment, exact three-record revocation,
unrelated contact retention and the original test logs.

This closes the narrow **same-authority synthetic revocation-attribution** gap.
It does not authenticate a malicious writer, prove external effect fencing,
recover a production owner, establish physical deletion or measure memory benefit.
PID and exit records are retained process evidence, not a new trusted-execution
attestation. The original local runs occurred before this readback; they are not
new actor tasks performed by this audit.

## Original hosted result is now available

[Workflow 42836074869](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42836074869)
completed successfully on exact source `9385535e683b97058fedeee490c6ff921652f793`.
The complete two original artifact ZIPs and decoded job logs are retained under
`hosted/`. Their ZIP digests match the GitHub artifact metadata exactly. The job
logs use lossless deterministic gzip; `LOG_COMPRESSION.json` binds original and
stored byte lengths/digests, including original timestamp-line whitespace.

| Hosted job | Observed test invocations | Additional campaign |
| --- | ---: | --- |
| [Frozen candidate and coverage contracts](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42836074869/job/129898492113) | 108/108 | None claimed |
| [Source-memory receipts and post-update revocation](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/42836074869/job/129898492613) | 24/24 | 14/14 deterministic scenarios |

The jobs overlap on **23 test identifiers**: there are **109 distinct test
identifiers**, not 132 independent tests or real tasks. Every retained test
receipt identifies the same clean Git source/tree before and after execution;
its raw log hash, named tests, terminal summary and exit code are checked.
The hosted campaign pins the same five source files and the same frozen plan.
It has `model_calls=0`. This audit did not start or retry these hosted jobs.

`HOSTED_READBACK.json` records the verified counts and original archive hashes.
`hosted/runs.json` preserves the separate timestamped status snapshot: the
source's MEM/EVOLVE/canary runs succeeded while architecture was still running
and blocking CI queued. The later CI-only source `4a53997...` remained queued;
the earlier source result is not transferred to that source or this evidence
commit. Full repository CI and common P0 qualification remain open.

## MEM6 raw archive remains incomplete

The local predecessor chunk stores contain **804 verified chunks / 52,690,944
bytes** of the expected 61,412,948-byte CAS archive. The exact missing half-open
byte intervals are:

- `[51,576,832, 51,642,368)` — 65,536 bytes.
- `[52,756,480, 61,412,948)` — 8,656,468 bytes.

Total missing: **8,722,004 bytes**. `MEM6_CHUNK_READBACK.json` records the original
version and expected whole-archive digest. No new native transfer, full archive
digest verification or 10,365-file restore was completed here. The retained
chunk readback does not upgrade the old transfer checkpoint to a restoration
PASS. No repeated business dispatch or replacement operation key was submitted.

## Scientific and sample-size boundaries

The previous MEM6 results remain unchanged: fixed-public retention 30/84 versus
28/84 over 20 source groups, with the preregistered lower-bound gate not met;
new-source selector 21/54 versus 13/54 over 14 source groups. Those 276 actor
episodes represent 138 pairs across 34 source groups. They are not additional
replicates created by this readback. Real successor-task benefit, competing
retrieval baselines under matched information, authenticated source/exposure
history, original owner/effect recovery and complete physical costs remain open.

This audit adds **zero model calls, zero actor episodes and zero independently
sourced real tasks**. Readback wall time is a local verification cost; historical
training, failed attempts, inference, storage, communication, energy and full
recovery costs are not made complete by these receipts.

## Reproduce without rerunning actors

From a checkout that retains the two historical source commits:

```bash
python -B qualification/memory-cell-mem7/readback-20261110/audit_retained.py \
  --root qualification/memory-cell-mem7/run-001 \
  --repository . \
  --snapshot-index qualification/memory-cell-mem7/readback-20261110/SNAPSHOT_INDEX.json

python -B qualification/memory-cell-mem7/readback-20261110/audit_hosted.py \
  --root qualification/memory-cell-mem7/readback-20261110/hosted \
  --repository .
```

Both commands are read-only. They validate pinned source bytes before importing
the receipt verifier, read original evidence and print an audit result. They do
not execute the archived mutation/reader commands, change SQLite stores, open
reserved future sources, or authorize adoption. `run-001/` is an exact snapshot
of the predecessor evidence; its development attempts and historical pending-CI
snapshot are deliberately preserved alongside the later readback.
