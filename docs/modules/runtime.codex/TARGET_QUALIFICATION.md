# runtime.codex real-provider target qualification

The manual `runtime.codex target qualification` workflow executes only on a protected self-hosted runner. Its external driver must operate the deployed Agentd/App Server, independent issuer, trusted clock, anti-rollback service, and real provider. The driver is digest-pinned by an environment secret.

For every required case and iteration it emits one JSON object using schema `hepta.runtime-codex.target-observation.v1`. Evidence must bind the exact candidate SHA/tree, profile, host boot ID, process identity, Agent generation, App Server session, issuer signer/epoch/revocation head, operation, provider/process evidence digests, physical request count, replay count, outcome, latency, RSS, and CPU.

Required cases are success, provider acknowledgement loss, provider event lag, worker death before and after effect entry, Agentd restart, App Server restart, issuer restart, and revocation-frontier race. The verifier rejects missing/duplicate cases, reused operation identities, more than one physical provider request, any blind replay, revocation rollback, unverifiable process/key/clock/anti-rollback claims, and threshold violations.

The output receipt may state that the target evidence and real-provider fault matrix validated. It must keep independent acceptance, activation, promotion, and release false. A separate authorized body reviews the attested receipt and canary/rollback evidence.
