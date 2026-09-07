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
before target contact, during execution, during bundle inspection and before
result acceptance. Bundle traversal runs in a spawned, killable worker with a
policy timeout; special files cannot block the reader. The manifest is
closed-world and cannot inject review, transition or release authority fields.
Timeout, output overflow, nonzero exit, invalid bundle or unconfirmed
original-process-group cleanup are terminal failures. Every started nonce is
non-retryable. A successful capture is only
`CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW`; it does not change a gap.
Setsid-escaped descendants are explicitly not proven absent.

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
