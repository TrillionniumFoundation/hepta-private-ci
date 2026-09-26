# browser.servo production operations

This runbook operates the repository-owned `browser.servo` source boundary. It does not issue operator acceptance, activation, promotion or release authority. Those decisions require the exact source, artifacts, target receipts and independent approvers named below.

## 1. Canonical topology

The production source topology is:

```text
trusted parent
  -> hepta-agentd-browserd
     -> PersistentBrowserServoControl
        -> verified-service-bootstrap.js
           -> service-manifest.json
           -> agentd-service-production-main.js
              -> BrowserProfileHost
              -> monotonic operation journal v2
              -> profile-affine Servo worker pool
              -> grant-scoped egress broker
              -> cgroup-v2 + seccomp + prlimit + Bubblewrap launcher
```

The one-shot `hepta-agentd-browser` binary is diagnostic. The long-running product owner is `hepta-agentd-browserd`; it accepts bounded newline-delimited JSON only over inherited stdin/stdout and creates no Browser TCP, HTTP, WebDriver, CDP or discovery listener.

The seven admitted module operations are generated and checked in `GENERATED_SOURCE_REGISTRY.json`:

- `open_profile`
- `admit_effect_grant`
- `observe_page`
- `navigate_or_act`
- `reconcile_operation`
- `reconcile_persisted_operation`
- `close_profile`

`credential`, `upload` and `download` remain registered fail-closed actions. Do not enable them by weakening the worker or bypassing their missing dedicated broker/terminal-observer boundaries.

## 2. Required immutable artifacts

An activation candidate must identify and retain all of the following:

1. exact repository commit and tree;
2. `verified-service-bootstrap.js` SHA-256 selected by Agentd host configuration;
3. bootstrap-bound `service-manifest.json` and every listed Git blob;
4. exact committed `servo-worker/Cargo.lock`;
5. worker binary SHA-256;
6. deterministic SPDX-2.3 SBOM SHA-256;
7. Bubblewrap and `prlimit` paths and SHA-256 values;
8. reviewed seccomp classic-BPF file path and SHA-256;
9. delegated cgroup-v2 subtree identity;
10. journal path, reconciliation root and observer trust/currentness policy;
11. live final-use authority state directory and monotonic revocation-feed path.

The Agentd `service_path` must select `apps/hepta-browser/src/verified-service-bootstrap.js`, not the unverified service entrypoint. The bootstrap verifies its embedded manifest digest and every transitive Browser ESM object before importing `agentd-service-production-main.js`.

## 3. Owner-private host files

All host configuration, journal, reconciliation, profile and isolation-policy parents must be owned by the Browser/Agentd service identity and not writable by an untrusted caller.

The production service reads `isolation-policy.json` from the parent of `HEPTA_BROWSER_PROFILE_ROOT`. Its exact schema is:

```json
{
  "schema": "hepta.browser.linux-isolation-policy.v1",
  "cgroupRoot": "/sys/fs/cgroup/hepta/browser",
  "seccompProfilePath": "/etc/hepta/browser/servo-seccomp.bpf",
  "seccompProfileSha256": "<64 lowercase hex>",
  "cgroupMemoryMaxBytes": 8589934592,
  "cgroupPidsMax": 256,
  "cgroupCpuQuotaMicros": 200000,
  "cgroupCpuPeriodMicros": 100000
}
```

Unknown or missing fields fail closed. The selected cgroup root must be a delegated cgroup-v2 subtree in which the service identity can create and remove per-worker child cgroups and write `memory.max`, `memory.oom.group`, `pids.max`, `cpu.max` and `cgroup.procs`.

## 4. Activation preflight

Activation is blocked unless all of these are terminal-success for the exact candidate:

1. `Browser required`;
2. `Browser Agentd composition`;
3. `Browser worker exact-head evidence`;
4. `Worker reproducibility required` from two independent hosted builders;
5. repository integrity and applicable Lane B checks;
6. trusted main-only Linux target qualification;
7. reviewed target receipt retaining the exact kernel, cgroup delegation, seccomp profile, Bubblewrap, `prlimit`, bootstrap, service closure and worker identities;
8. independent operator approval.

Preflight commands for a source checkout are:

```sh
node apps/hepta-browser/scripts/browser-source-registry.js --check
node --test apps/hepta-browser/test/*.test.js
find apps/hepta-browser/src apps/hepta-browser/scripts -type f -name '*.js' -print0 \
  | sort -z | xargs -0 -n1 node --check
cargo metadata --locked --manifest-path apps/hepta-browser/servo-worker/Cargo.toml \
  --format-version 1 >/dev/null
cd codex-rs
cargo test --locked -p codex-hepta-agentd browser_servo --lib
cargo test --locked -p codex-hepta-agentd browser_revocation_feed --lib
cargo check --locked -p codex-hepta-agentd \
  --bin hepta-agentd-browser --bin hepta-agentd-browserd
```

Passing source checks is necessary but is not target-host or release evidence.

## 5. Runtime invariants

Operators must preserve these invariants:

- one durable operation identity has one immutable request and semantic digest;
- terminal state is monotonic and conflicting terminal evidence is rejected;
- exact duplicate dispatch/observation is a no-op;
- final-use authority remains held until the Servo worker emits the exact admission/dispatch-boundary receipt;
- an uncertain timeout terminates or quarantines the private child; AbortSignal delivery alone is not containment evidence;
- no operation that may have crossed the effect boundary is blindly redispatched;
- profile expiry and explicit close terminate worker and egress leases;
- all external network access goes through the grant-scoped broker;
- page action execution revalidates document/navigation revision, origin and actionable-surface identity;
- journal, logs, metrics and receipts contain no raw credentials, upload content or page-secret values.

## 6. Service metrics and SLOs

`hepta-agentd-browserd` writes redacted JSON metrics to stderr using schema `hepta.browser.service-metric.v1`. Request metrics contain only request ID, registered method, success boolean and elapsed microseconds. They do not contain typed actions, URLs, selectors, visible text, credentials or error text.

Initial activation SLOs are operational gates, not universal performance claims:

| Signal | Initial objective | Alert threshold |
| --- | ---: | ---: |
| Browser owner availability | >= 99.9% over 30 days | < 99.9% |
| non-effect RPC p95 | <= 1 s | > 1 s for 15 min |
| worker-admission p95 | <= 2 s | > 2 s for 15 min |
| unresolved indeterminate operations | 0 aged > 15 min | any aged > 15 min |
| journal owner fencing | 0 | any event |
| journal utilization | < 70% | >= 70%; critical >= 85% |
| active profiles | < 80% of configured cap | >= 80% for 10 min |
| worker restart rate | < 3/profile/hour | >= 3/profile/hour |
| cgroup OOM events | 0 | any event |
| egress policy denial anomaly | baseline-dependent | > 5x 7-day baseline |
| revocation-feed age | <= 2 refresh periods | older than 2 periods |
| target receipt age | <= selected release policy | expired receipt |

Do not use success rate alone as proof of external business terminality. Browser success means only the registered Browser receipt semantics; independent business outcome evidence remains separately owned.

## 7. Capacity policy

Hard source ceilings include bounded profiles, origins, grants, outstanding operations, frame sizes, journal size, action fields and deadlines. Target capacity must additionally record:

- CPU quota and period;
- memory and PID ceilings;
- file descriptor limit;
- worker RSS and FD growth under 32-cycle soak;
- observation byte and latency distributions;
- journal append, replay, compaction and recovery latency;
- egress broker concurrent connections and bounded response bytes.

Increase a ceiling only with an exact candidate, updated soak profile and rollback plan. Never treat a larger ceiling as a substitute for backpressure.

## 8. Fault-injection qualification

Before activation and after changes to journal, authority, worker, broker or launcher code, execute at least these drills:

### Durable journal

- process death before append, during write, after file fsync and before parent-directory fsync;
- torn final line and checksum corruption;
- duplicate dispatch before and after terminal observation;
- terminal rollback and conflicting terminal receipt;
- `ENOSPC`, `EDQUOT`, `EIO`, read-only filesystem and close failure;
- two-process owner-lock contention;
- stale dead-owner lock recovery;
- compaction interruption before/after rename and directory fsync;
- retired-generation resurrection attempt.

Expected result: validated prefix recovery where allowed, otherwise owner fencing. No uncertain write may be acknowledged as durable success.

### Effect admission and authority

- revoke before challenge, between challenge and authority entry, during journal fsync and before worker admission;
- worker rejects stale document revision before effect execution;
- pipe write succeeds but admission receipt is lost;
- admission receipt arrives after parent timeout;
- parent, Browser service or worker receives `SIGKILL` at every boundary;
- malformed sequence, request digest, semantic digest, worker generation or page revision.

Expected result: pre-admission negative outcome, recoverable admitted identity, or full child containment/quarantine. No blind retry.

### Network and page state

- DNS rebinding and excessive answer set;
- private, loopback, link-local, multicast and special-address targets;
- redirect to ungranted origin;
- cross-origin subresource, iframe, WebSocket and download attempts;
- TLS/SNI mismatch;
- oversized or slow response;
- DOM/navigation mutation between observation and action;
- stale handle, hidden element and non-actionable target;
- profile expiry and close during background traffic.

Expected result: exact grant enforcement, bounded resource use and no post-lease external traffic.

### Isolation and lifecycle

- cgroup memory, PID and CPU pressure;
- seccomp-denied syscall;
- worker attempts to read host secrets or execute general host binaries;
- parent death and descendant cleanup;
- stderr flood;
- 32-cycle profile start/use/close soak;
- service restart with unresolved journal entries and live revocation updates.

## 9. Incident response

On journal fencing, admission uncertainty, artifact drift, revocation-feed rollback, closure-manifest mismatch or isolation failure:

1. stop admission of new Browser effects;
2. preserve journal, reconciliation receipts, exact artifacts, policy files and redacted metrics;
3. terminate or quarantine all affected private children and egress brokers;
4. do not delete unresolved operations to restore capacity;
5. classify each identity as terminal applied, terminal not applied or unresolved/quarantined using current trusted evidence;
6. rotate or revoke affected grants when authority integrity is uncertain;
7. open a new exact candidate for repair and rerun all relevant fault drills;
8. require an independent operator to restore activation.

Raw page content, typed text, secrets and upload bytes must not be copied into incident tickets or logs.

## 10. Servo pin and CVE update procedure

A Servo or dependency update is a new artifact and qualification cycle:

1. select an explicit upstream commit and record the rationale/security advisory set;
2. update `Cargo.toml`, committed `Cargo.lock`, pin manifest and topology registry together;
3. review feature graph and reject WebDriver/server or unapproved capabilities;
4. run unit, Browser, real E2E, policy, crash-recovery and soak tests;
5. build on two independent hosted builders and require byte-identical output;
6. regenerate deterministic SPDX-2.3 SBOM and provenance receipt;
7. compare dynamic library closure and license/security scan results;
8. qualify the exact artifact on the trusted target;
9. stage canary activation with rollback artifact retained;
10. obtain independent promotion/release approval.

A source pin change, generated lock, successful compilation or author statement is never sufficient by itself.

## 11. Rollback

Rollback selects a previously qualified immutable tuple:

```text
source tree
+ verified bootstrap and ESM closure
+ worker and Cargo.lock
+ SBOM/provenance
+ launcher/cgroup/seccomp policy
+ journal schema compatibility
+ target receipt
```

Before rollback, verify that the older code can read every live journal schema and terminal receipt. If not, leave the current durable owner in reconciliation-only mode, migrate through an explicitly tested converter or quarantine the affected generations. Never reinterpret, truncate or delete unresolved operations merely to make older code start.

## 12. Evidence retention

Retain at minimum:

- exact-head and synthetic-merge source receipts;
- independent worker reproducibility receipt;
- worker, lock, SBOM and provenance digests;
- real Browser E2E and 32-cycle soak outputs;
- sandbox, cgroup, seccomp and descendant-cleanup evidence;
- trusted target public HTTPS and isolation receipt;
- fault-injection results;
- operator activation, rollback and release decisions;
- current signed terminal-observer trust/frontier configuration.

Repository source and CI configuration cannot self-issue independent acceptance, activation, promotion or release.
