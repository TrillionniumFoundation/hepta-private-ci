# Dynamic provider acceptance contract

Dynamic issue/renew/revoke support is proved only by a real OpenBao service
receipt bound to the exact source head and tree. Synthetic endpoint probes or
direct API-only checks cannot qualify the adapter.

The required matrix covers pinned-CA TLS, KV-v2 control, dynamic issue, renew,
revoke, timeout, DNS and TLS failures, 429/5xx, expired tokens, revoked policy,
provider-success/local-crash, consumer-success/response-loss and restart
query/reconciliation.

Evidence must not retain tokens, leases, credentials or secret values. Three
distinct principals attest secrets/security, product-caller and operations/SRE.
Even a passing dynamic-provider receipt has `productionAuthority=false`; target
host, storage, operator acceptance and release remain separate gates.
