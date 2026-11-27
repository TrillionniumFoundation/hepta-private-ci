# Root publication CLI deployment V1

## Source and validation scope

The source base is `05acfd02b53d2165ef91ddd0d000070af59031de`.
This is a frozen draft of 14 Rust postimages, with exact base-to-postimage line operations
for the eight existing files and a semantic CALLERS delta. GitHub blob identities were
checked against locally computed Git blob SHA-1, byte size and SHA-256 before this
manifest was created. No branch, PR or shared source was changed by this export.

No Rust formatter, Cargo compiler, native test, Root parent or official complete
CALLERS scan was executed for this draft. The root integrator must preserve later
native formatting and unrelated fixes while applying the recorded semantic changes,
then qualify one new exact source. Checks of template markers and line reconstruction
are textual checks only; they are not the official verifier.

The 1,220 added / 15 removed Rust lines are organized into three review slices:
original data/file custody and Artifact location, same-process CLI/lifetime wiring,
and the existing Root component. The slice is deliberately separate from the initial
publication purpose being implemented elsewhere. No initial-purpose authority is
added here.

## Entry and actual ordering

The existing Linux `hepta-authority-host` commands `serve-session` and
`serve-fresh-session` accept a paired set of optional arguments:

```text
--generation-publication-deployment /absolute/private-root/deployment.json
--root-generation-publication-handoff-fd <distinct inherited descriptor>
```

The original learning profile, learning handoff and held Root pidfd are required.
A new Model offer is not required for a legitimate retained-result operation.
The same inherited-FD closed set claims the new descriptor before opens or runtime
construction. Aliased/missing descriptors remain rejected.

After the original registered learning and optional Model preparations, the same
PreparedHostAuthoritySession enables its existing purpose-bound publication route.
Its opaque enrollment capability is consumed into the deployment loader. The ready
callback sends the original purpose offer and prints the correlation session.
The worker waits separately while the original five lanes and learning/Model services
run. Publication is not inserted into the fixed five-lane accept barrier.

After an actual authenticated decision and independent Artifact Selection exist, a
trusted Root deployment host writes the fixed late-material and trigger files. The
worker opens the actual Artifact read-view, verifies the original current registry,
withdrawal floor and Selection, opens the actual selected files, and calls the same
original capability's register method once. That method derives operation, scope,
decision and profile from the live original learning backend and preserves the original
CURRENT, FinalUse, peer, pidfd, witness and journal checks.

## Frozen startup inputs and late data

The deployment descriptor is schema version 1 and rejects unknown fields. All its
fields are explicit; it supplies no key, grant, signature or owner default:

- Reserve or Recover mode.
- Original Root CURRENT directory; original previous journal/witness paths and observer configuration.
- Fixed original target journal/witness paths. These actual files must already exist;
  the loader neither creates a target owner nor initializes a missing journal.
- Original Artifact root, complete writer/head trust, retained signed CURRENT,
  storage binding, and retained withdrawal snapshot path plus its exact receipt.
- Original independent selector trust.
- Existing Device or Notes consumer, actual consumer state root and complete original
  issuer keyring, including its key IDs and epoch windows.
- Fixed private Root paths for late material and trigger.

The descriptor does not contain an unknown future target configuration or Selection.
The late material permits only schema version, actual target observer configuration,
and the complete already-signed independent Selection. It cannot add paths, trust,
consumer, issuer, CURRENT directory or Root learning scope.
`RootGenerationPublicationDeploymentV1::encode_original_material` encodes these
actual typed values, round-trips the entire original Selection, and produces the
canonical bytes expected by the trigger. It does not sign them or grant authority.

The trigger JSON has exactly `session` and `material_digest`. The session is the
printed `publication_deployment_session` value, including schema, Root PID, boot ID,
process start ticks, a checked monotonic attempt number and the descriptor byte digest.
The material digest is the canonical original material's Digest32 string. These
correlation values alone are not permission; the trigger must be delivered through
the fixed private Root file and the retained original capability must remain live.

## File custody and bounds

Descriptor, late material and trigger must each be an actual UID0 regular file with
exact mode 0600 (including rejection of special mode bits), a single hard link,
1..65,536 bytes, and a private original Root parent. Opens use O_NOFOLLOW and retain
the actual descriptor. Exact inode/custody, length, timestamps, bytes and digest are
checked before and after reading, including a final pathname and parent check.

Directory pins hold actual O_DIRECTORY|O_NOFOLLOW descriptors and compare both the
retained descriptor and pathname identity. All paths are canonical, absolute, bounded
to 4,096 bytes, and reject dot/parent traversal. Original journal/witness/material
files are opened read-only, reject unrelated writers and hard links, and retain their
actual parent and inode identity. Their legitimate journal contents may advance;
the original owner/observer still validates the real cut and private custody.

The Artifact locator returns data paths only. It authenticates the independent
Selection at the original CURRENT cut, uses the existing registry snapshot path and
payload-name algorithm, and rechecks receipt, witness, trust, withdrawals and payload
directory before returning. The agentd loader pins actual FDs and repeats location;
the original enrollment loader remains the capability gate. No second Artifact writer,
journal lock, issuer or FinalUse authority is opened by the deployment loader.

## One attempt, cancellation and uncertainty

The deployment object cannot be cloned or constructed from a bootstrap. It retains
the original same-PID cap and compares PID, boot ID, start ticks and phase on capture.
Each accepted trigger must match this exact session and material. The original cap
still performs ACTIVE-to-CONSUMED before sending its request. Failure drops this
one object; there is no automatic re-signing, renewal, mode fallback or re-registration.

The wait is bounded by the original capability lifetime and checks the stop flag,
phase and all frozen files. On serve return, error, ready-callback error or unwind,
the CLI's RAII guard signals stop before the scoped worker is joined. An already
started original register retains its original bounded acknowledgement behavior.
The worker does not hold a second service/writer or kill a thread.

After register succeeds, file/custody observations run again. Any post-check failure
or session ending is reported as registration uncertainty, never permission to retry
Reserve. Cross-owner changes remain subject to the original uncertainty semantics;
this adapter introduces no atomic transaction. The existing limitation concerning a
withdrawal rollback that was never independently observed is unchanged.

## Exact component parent

The existing ignored actual-UID0 agentd parent remains:

```text
neuron_generation_current::publication_root_tests::root_broker_late_enrolls_publishes_and_recovers_original_current
```

No new Root parent or helper is added to the roster. This parent is intended to continue
using real protected Root directories, actual UID60001 child, original five-lane receive,
same Root issuer/frontiers, schema3 nonce owner, original claim/dispatch and actual
Host CURRENT CAS. Its existing EvaluationNoUpdate role/history fixture remains
explicitly synthetic component data.

The parent now builds the descriptor from its actual original inputs, captures the
actual deployment loader before serving, waits for the child's actual
LEARNING_AND_ORIGINAL_INPUTS_READY message, writes canonical late data/trigger, and
calls the production wait-and-register path before continuing its original
publish/readback/recover/revocation/nonce assertions.

Added source assertions cover signature-preserving material round-trip; rejection of
extra late-material authority/path fields; prior actual Publish trigger rejected by
the guard in later sessions with unchanged original profile/CURRENT/claims bytes;
cancellation/deadline guards; replacement inode, symlink, hard link, special mode bits
and replaced parent; duplicate create-only trigger write; and second enable rejection.
The prior-session check is a guard-level replay negative, not an injected stale
full wire dispatch. Cancellation/deadline checks invoke the actual private guard
directly, not a claimed process-kill/cold-restart test.

All these assertions are unexecuted in this export. They cannot be added to any
previous candidate's test totals.

## Remaining external materials and acceptance

The deployment host must possess the actual original files, trust/keyring, independently
signed Selection and original daemon/Root handoff lifecycle. This code creates none
of them. Actual ordinary A/B/C work, business benefit, independent C, physical daemon
and Root cold restart, rollback adoption and deployment acceptance remain unverified.
Ordinary complete, positive-adoption and NoUpdate/rollback chain counts remain zero.

The next validation source must run original formatting/maintenance, same-source
helpers, affected agentd and artifacts suites, the existing full UID0 roster including
this parent, and the unfiltered official CALLERS verifier. Initial-purpose and other
agents' changes must be merged by their exact semantic deltas, not by overwriting
the shared session/runtime/lib files with these old-base full postimages.
