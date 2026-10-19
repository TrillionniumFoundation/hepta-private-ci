# ui.control deployment security policy

This policy is enforced by `deployment-security-invariants.mjs` and consumed by the protected external qualification workflow. It is a repository-controlled acceptance policy, not evidence that a deployment has passed it.

## Exact header semantics

The probe parses security headers structurally. Substring matches are not accepted.

- `Content-Security-Policy` must contain each required directive exactly once. The required source sets are exact: same-origin scripts, styles, connections, and default resources; same-origin plus `data:` images; and `none` for objects, base URIs, and framing. Wildcards, insecure origins, externally scoped origins, `blob:`, and unsafe script/style keywords fail closed.
- `Strict-Transport-Security` must contain one integer `max-age` of at least 31,536,000 seconds. `max-age=0`, duplicate directives, and malformed values fail.
- `Cache-Control` must contain `no-store`. `public`, `immutable`, positive `max-age`, and positive `s-maxage` fail even when `no-store` is also present.
- `Permissions-Policy` must explicitly disable camera, microphone, geolocation, and payment with empty allowlists. Similar-looking values such as `camera=(self)` do not satisfy the rule.

## TLS policy

The selected endpoint must negotiate TLS 1.2 or TLS 1.3 with an authorized certificate. TLS 1.2 requires ephemeral ECDHE and AEAD encryption. Ciphers containing RC4, 3DES, DES, CBC, NULL, EXPORT, or MD5 are rejected. The certificate must retain at least seven days of validity at observation time, and the SHA-256 peer fingerprint is retained in the receipt.

The seven-day runway is a qualification floor, not an operational rotation target. Production monitoring should alert substantially earlier.

## Cookie policy

Every session cookie observed during qualification must:

- use a syntactically valid name;
- set `Secure` and `HttpOnly` as flag attributes;
- set `SameSite=Strict` or `SameSite=Lax`;
- use the exact selected deployment path;
- remain host-only by omitting `Domain`;
- avoid duplicate attributes whose interpretation could differ across clients or proxies.

Cookie values, authentication material, and CSRF tokens are never written to qualification receipts.

## Receipt binding

Both passing and failing deployment observations identify the enforced profile as:

```text
hepta.ui-control.deployment-security-policy.v1
```

They also retain the minimum HSTS age and certificate runway. A passing receipt still proves only the exact candidate, deployment digest, build assets, and observed endpoint at the recorded time. It does not imply real Agentd durability, independent accessibility acceptance, independent security review, production approval, activation, or release authorization.
