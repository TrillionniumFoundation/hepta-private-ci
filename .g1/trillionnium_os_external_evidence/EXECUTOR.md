# Fixed target executor

Status: **stacked source candidate; no target evidence or release authority**.

`trusted_executor.py` consumes only a root-owned admission record previously
written by `admission_service.py`. The caller supplies a validated nonce, not an
executable, module, target, configuration or output path. The admission filename
nonce must exactly match the internal authorization nonce before a one-shot
marker can be created. The executor derives:

```text
/opt/owner-open-r5/harnesses/<evidence-kind>
/etc/owner-open-r5/attestations/<evidence-kind>.json
```

It verifies the admission-policy/key/issuer allowlists, exact source subject,
case-insensitive role separation, authorization expiry, fixed harness and
target-attestation hashes, target custodian and environment class. The verified
harness bytes are copied to a sealed executable memfd, so a same-inode rewrite
or atomic pathname replacement after verification cannot change the program
that executes. It persists a distinct `STARTED_NO_AUTOMATIC_RETRY` marker before
invoking that sealed harness in a private empty working directory with a fixed
environment.

Stdout/stderr, runtime and bundle sizes are bounded. Authorization is rechecked
before target contact, on every leader-wait path even after both output pipes
close, during bundle inspection and before result acceptance. Bundle traversal
runs in a spawned, killable worker with a policy timeout; special files cannot
block the reader, and any directory-walk error fails the complete capture. The
manifest is closed-world and cannot inject review, transition or release
authority fields.

Timeout, output overflow, nonzero exit, invalid bundle, an outliving descendant
or unconfirmed complete-descendant cleanup are terminal failures. Before launch,
the executor enables Linux child-subreaper semantics and requires pidfd signaling
plus procfs identity/start-time observation. Daemonized or `setsid()` descendants
therefore remain in the executor-owned descendant tree, are signaled by stable
pidfd identity, reaped, and observed absent twice before any successful receipt.
After
`STARTED_NO_AUTOMATIC_RETRY` is durable, unexpected working-directory, fsync,
process-launch, worker or inspection failures are converted to a non-overwriting
`CAPTURE_FAILED_NO_RETRY` receipt. If the ordinary result medium is unavailable,
a separate non-overwriting terminal-failure receipt binds the intended result
digest. If both media are unavailable, the durable STARTED record remains the
authoritative no-retry boundary and the service reports that degradation
explicitly. Every started nonce is non-retryable. A successful capture is only
`CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW`; it does not change a gap. A
success receipt records `linux_subreaper_pidfd_descendant_tree_v1` and proves the
complete spawned descendant tree empty. Any observation or signaling ambiguity
fails closed and leaves the durable one-shot boundary authoritative.

`execution-policy.template.json` is deliberately unprovisioned. The external
custodian must install an `ACTIVE`, root-owned policy and independently bind the
active admission-policy digest, grant key digest, issuer and current subject.

Source verification, after stacking on the admission change:

```bash
cd .g1/trillionnium_os_external_evidence
python3 -m unittest discover -s tests -v
```

Production invocation after independent installation:

```bash
/usr/bin/python3 -I /opt/owner-open-r5/trusted_executor.py --nonce <32-64 lowercase hex>
```
