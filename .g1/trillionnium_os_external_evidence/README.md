# Trillionnium OS external evidence admission

Status: **source candidate only; unprovisioned; no target, promotion, or release authority**.

`admission_service.py` implements the independent boundary between the
repository route request and a target-owned harness. It opens root-owned inputs
nonblocking, rejects special files before reading, and closes each descriptor on
every partial-acquisition or malformed-policy failure. It rejects
duplicate/non-finite JSON, verifies exact request/grant binding, requires a
strictly positive bounded grant lifetime, and compares approvals and operational
roles case-insensitively. L5/L6 policy requires two independent approvals.

RSA-SHA256 verification runs over the retained grant bytes through sealed Linux
memfds. A successful admission atomically writes one nonce-consumption record
before any target contact.

The checked-in policy is deliberately `UNPROVISIONED_TEMPLATE`: its key digest
is zero and issuer allowlist empty. An external custodian must install an
`ACTIVE` root-owned policy and public key under `/etc/owner-open-r5`, and must
provision `/var/lib/owner-open-r5/admission` mode 0700. Repository authors or
workflows must not populate the trust root.

This stage does **not** allocate a runner, contact a device, execute candidate
code, execute a harness, produce target evidence, review evidence, change a gap,
or authorize release. The next stage may consume the immutable admission record
and fixed target files, but it must use a separate one-shot execution marker.

Source verification:

```bash
cd .g1/trillionnium_os_external_evidence
python3 -m unittest discover -s tests -v
```

Production entrypoint after independent deployment:

```bash
/usr/bin/python3 -I /opt/owner-open-r5/admission_service.py \
  --request /secure/inbox/request.json \
  --grant /secure/inbox/grant.json \
  --signature /secure/inbox/grant.sig
```
