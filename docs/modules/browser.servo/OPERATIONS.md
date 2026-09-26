# browser.servo production operations runbook

**Module:** `browser.servo`  
**Scope:** source-defined operating contract for the long-running Agentd-owned Browser service  
**Claim boundary:** this runbook does not constitute target qualification, operator acceptance, activation, promotion or release approval.

## 1. Supported production topology

The production-shaped topology is:

```text
trusted Agentd owner
  -> hepta-agentd-browser-service (inherited stdio only)
    -> restartable private Browser service child
      -> profile-affine Servo worker pool
        -> Bubblewrap + prlimit containment
        -> grant-scoped private egress broker
```

`hepta-agentd-browser` remains a one-call diagnostic and qualification client. Long-running activation must use `hepta-agentd-browser-service`, which keeps one `PersistentBrowserServoControl` for the process lifetime, owns the monotonic revocation feed and never exposes a TCP, HTTP, WebDriver or CDP listener.

Start syntax:

```sh
hepta-agentd-browser-service \
  /absolute/private/browser-host-config.json \
  /absolute/private/browser-service-closure.json
```

Both inputs must be immutable for the selected activation generation. The host config is owner-private and the closure manifest binds every transitive JavaScript module loaded by `agentd-service-main.js`.

## 2. Mandatory artifact closure

Before activation, retain exact digests for:

- Agentd Browser service binary;
- Browser host config;
- Browser service closure manifest;
- every JavaScript module enumerated by that manifest;
- Servo worker binary and committed `Cargo.lock`;
- Bubblewrap and `prlimit` executables;
- SPDX-2.3 SBOM;
- source commit and source tree;
- kernel, runner and namespace configuration.

Generate the JavaScript closure manifest from the selected deployment tree:

```sh
node apps/hepta-browser/scripts/service-closure-manifest.js \
  /absolute/deployment/apps/hepta-browser \
  /absolute/private/browser-service-closure.json
```

The long-running service rejects missing, additional, renamed, symlinked, group/world-writable, oversized or digest-drifted closure entries before starting the Browser child.

## 3. Hard capacity envelope

The selected host configuration must stay inside source ceilings:

| Resource | Hard source ceiling / default |
| --- | --- |
| Active profiles | configurable, maximum 64; default product target 16 |
| Origins per profile | 128 |
| Effect grants per profile | 1,024 |
| Nonterminal operations per profile | 1,024 |
| Retained terminal operations in memory | 256 |
| Parent/worker frame | 1 MiB |
| Page observation | 1 MiB API budget plus bounded semantic fields |
| Journal | 64 MiB JSONL owner file; compaction at 48 MiB; 65,536 live records |
| Worker address space | 8 GiB default `prlimit` |
| Worker CPU | 300 seconds default `prlimit` |
| Worker file descriptors | 4,096 default `prlimit` |
| Worker processes/threads | 256 default `prlimit` |

Increasing a configurable value requires a new target profile, soak evidence and capacity review. A source maximum is not a measured safe deployment capacity.

## 4. Structured operational metrics

The long-running Agentd service emits one secret-free JSON line on stderr after every completed RPC:

```json
{
  "schema": "hepta.browser.agentd-metric.v1",
  "sequence": 42,
  "method": "navigate_or_act",
  "ok": true,
  "durationMs": 17,
  "requestsTotal": 42,
  "failuresTotal": 1
}
```

Collectors must treat stderr as a bounded structured stream and must not add request payloads, selectors, page text, URLs with query data, credentials, upload paths or raw worker stderr to metric labels.

Required derived signals:

- RPC count and failure ratio by method;
- dispatch-admission latency;
- reconciliation latency and indeterminate-operation age;
- active profile and worker count;
- worker restart/containment count;
- journal bytes, live index size, compaction duration and fenced-owner state;
- egress decisions by non-sensitive disposition;
- RSS, FD and descendant-process counts;
- revocation-feed revision and refresh failure age.

## 5. Activation SLO targets

These are activation targets, not current empirical claims. A target host must measure and retain them before operator acceptance.

| Objective | Target |
| --- | --- |
| Duplicate irreversible effects | zero tolerated |
| Unauthenticated terminal reconciliation | zero tolerated |
| Unregistered external listener | zero tolerated |
| Final-use release before worker admission receipt | zero tolerated |
| Control RPC availability | >= 99.9% over 30 days, excluding declared maintenance |
| Non-effect control RPC p99 | <= 250 ms |
| Local worker admission p99 | <= 500 ms |
| Reconciliation p99 when observer receipt is present | <= 2 s |
| Revocation-feed staleness | <= 1 s normal; page at 5 s |
| Indeterminate effect backlog | alert at 1 item older than 5 min; page at 30 min |
| Worker RSS terminal growth over 32-cycle soak | <= 256 MiB |
| Worker RSS peak growth over 32-cycle soak | <= 512 MiB |
| FD terminal growth over 32-cycle soak | bounded by the retained target receipt |

An SLO miss must not be reclassified as success by retrying with a fresh operation identity.

## 6. Normal startup and shutdown

### Startup

1. Resolve the exact source SHA/tree and approved build receipt.
2. Verify committed Servo lock, worker, SBOM, Bubblewrap and `prlimit` digests.
3. Generate and independently review the complete service closure manifest.
4. Verify owner-private directories for authority state, revocation feed, journal, profiles and reconciliation receipts.
5. Start `hepta-agentd-browser-service` as the Agentd child using inherited pipes only.
6. Require a health qualification call sequence: open profile, bootstrap navigation, semantic observation, close profile.
7. Confirm no non-loopback listener and record the process tree/resource baseline.

### Shutdown

1. Stop admitting new profiles and effects.
2. Reconcile or quarantine every nonterminal operation.
3. Close each profile and require worker descendant cleanup.
4. Flush and retain journal/receipt storage.
5. Close the inherited channel; the service then terminates its Browser child.
6. Preserve the final metric, journal and process-tree receipts.

Never delete unresolved journal entries to unblock shutdown.

## 7. Failure response

### Journal owner fenced

Symptoms: journal read/write returns owner-recovery-required, checksum/tail failure or durability barrier failure.

Actions:

1. stop new effects immediately;
2. preserve the exact journal bytes and filesystem metadata;
3. do not restart against a copied or silently truncated journal;
4. run the versioned repair/migration tool on an isolated copy;
5. compare the repaired prefix and terminal receipts with the external observer;
6. activate only under a new reviewed owner generation.

### Worker protocol, timeout or crash

1. classify the operation as pre-admission rejected, admitted/indeterminate or terminal;
2. never redispatch an admitted or uncertain identity;
3. contain and reap the complete worker descendant tree;
4. start a fresh worker only for later calls;
5. reconcile the original identity using the authenticated observer path.

### Revocation feed stale or invalid

1. fail closed for every new effect;
2. keep observational reconciliation available;
3. inspect owner, mode, hard-link count, inode stability, schema, epoch and monotonic revision;
4. restore a current signed head without decreasing the frontier;
5. record the staleness interval and affected admitted operations.

### Egress policy violation

1. close the effect-scoped broker path;
2. quarantine the profile generation;
3. preserve DNS/IP/redirect/TLS decision receipts;
4. confirm no background network survives profile expiry/close;
5. require security review before reactivation.

## 8. Rollback and quarantine

Rollback changes executable selection, not operation history. It must preserve:

- journal and segment generations;
- authenticated terminal receipts;
- profile-generation retirement markers;
- selected authority/revocation frontier;
- exact worker and service closure identities.

If an older binary cannot read the current journal schema, keep the current owner offline and perform a reviewed forward-compatible migration. Never silently reinterpret v2 records as v1.

## 9. Servo pin and CVE refresh

For every Servo, Rust, TLS, Bubblewrap, `prlimit` or critical transitive dependency update:

1. freeze the proposed upstream commit and toolchain;
2. review the delta affecting WebView, navigation, networking, JavaScript, storage, permissions and renderer/process lifetime;
3. generate and review the exact `Cargo.lock` bytes;
4. reject forbidden features and WebDriver/CDP server dependencies;
5. run locked check/test, two-build reproducibility, SBOM generation and dynamic-library closure inspection;
6. run real public HTTPS, redirect/subresource denial, revocation race, crash reconciliation, profile isolation and 32-cycle soak;
7. rerun trusted target qualification on the exact main SHA;
8. obtain independent operator/release decisions.

A CVE exception must name the affected package/version, exploitability analysis, compensating controls, expiry and owner. It cannot be represented by a generic “not applicable” label.

## 10. Mandatory fault drills

Run and retain exact receipts for:

- process loss before journal dispatch reservation;
- process loss after reservation but before worker admission;
- process loss after worker admission but before terminal observation;
- torn journal tail and compaction/retirement crash cuts;
- file and parent-directory fsync failure;
- revocation racing `authority_enter` and worker admission;
- DNS rebinding, private/special IP, redirect escape and TLS/SNI mismatch;
- profile expiry and explicit close during background network activity;
- worker stdout/stderr saturation and parent death;
- worker fork/FD/RSS pressure at configured limits;
- cross-profile cookie, localStorage, cache and profile-directory isolation;
- service closure, worker, Bubblewrap and `prlimit` digest drift.

A drill passes only when the exact expected state transition and containment receipt are observed; process exit alone is not evidence.

## 11. Promotion checklist

Promotion remains false until all of the following are true on the exact candidate:

- `Browser source truth` succeeds;
- `Browser Agentd service` succeeds;
- Browser/Agentd composition succeeds;
- locked Servo build, E2E, reproducibility, SBOM and soak succeed;
- deterministic source-head and base-merge gates succeed;
- trusted main-only target qualification succeeds;
- all open indeterminate operations are reconciled or explicitly quarantined;
- independent operator acceptance, activation, promotion and release are issued by their designated owners.

## 12. Operation-scoped egress and immutable recovery invariants

Only `.hepta-egress.sock` is worker-visible. The underlying profile policy socket
must live in a fresh owner-private sibling directory outside the writable profile
mount. A second policy socket inside the profile directory bypasses operation
admission and is forbidden, irrespective of its filename or Unix mode.

Every accepted connection belongs to the operation that accepted it, including
connections still waiting for their first complete header. Revalidate that same
identity after asynchronous header/connect work and before forwarding bytes.
Enforce both wall-clock expiry and a monotonic deadline. Expiry closes partial
headers, active tunnels and upstream peers without waiting for another RPC.
Completion closes the operation's sockets; a late settlement returns its original
receipt and cannot affect a newer operation. Completed identities cannot reopen
network authority; the bounded identity set does not evict old entries to admit
more effects. Rotate the profile generation when its identity capacity is reached.

For plaintext HTTP, check every request on a persistent or pipelined connection,
not just its first header. Bind the absolute target and Host to the effect origin,
parse bounded Content-Length/chunked framing, and reject ambiguous framing,
authority-bearing trailers and protocol upgrades. HTTPS uses the existing frozen
DNS/IP and CONNECT/SNI broker. A network receipt establishes a bounded transport
observation, not a remote business outcome or durable post-crash proof.

Journal transitions compare all immutable scalar fields, not only caller-supplied
request and semantic hashes. Principal, process, document, origin, action, grant,
epoch, deadline and witness cannot change during observation or replay. Retirement
is checked under the writer lock at dispatch admission as well as at profile open.
Retirement serialization must round-trip case-sensitive, punctuation and numeric
identifiers without locale-dependent ordering.

The Browser parent validates the admission semantic digest against the exact
request semantics plus this invocation's verified-use witness. In-process host and
driver capability objects may have prototype methods; wire requests and authority
messages remain plain JSON objects with exact key sets. Failure of gate cleanup
must not skip the underlying worker stop or containment operation.

## 13. Required source verification and evidence limits

`blocking-ci.yml` invokes the Browser source lane independently of Cargo scope and
includes it as a non-skippable dependency of `CI required`. Pull requests execute
both their exact source head and a deterministic base-merge candidate. Main pushes
execute the merged head. This does not alter or waive branch-protection rules.

The source lane checks generated source blobs, all JavaScript syntax, the complete
Browser Node suite and committed lock/pin identity. Original TAP output and a
tracked-source archive are retained even when a test fails. It does not generate
a lock in CI. Reproduce the source checks from the selected checkout:

```sh
node apps/hepta-browser/scripts/browser-source-registry.js --check
node --test --test-concurrency=4 apps/hepta-browser/test/*.test.js
```

The following remain distinct obligations, not facts established by a Node pass:

- locked native Servo and Agentd compilation, lint and real WebView execution;
- a worker-originated, durable admission receipt and verified post-process-loss
  recovery, rather than treating a host-generated admission wrapper as that proof;
- cgroup/seccomp enforcement and complete descendant containment on the target;
- durable retention of operation egress receipts and independently issued remote
  business terminal observations;
- isolated multi-builder reproducibility and verified signed SBOM/provenance;
- real public HTTPS, hostile DOM drift, cookie/cache/storage isolation and soak;
- the trusted target run, independent operator acceptance and release decisions.

Do not infer any of these from a workflow definition, an uploaded partial artifact,
a source-registry substring check, a merged history edge or a prior-head pass.
