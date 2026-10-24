# Reading the original canonical writer after a stopped session

`DeploymentFinalUseIssuer::retained_writer_state_for_root` reads the actual
protected issuer under its original request lock. It verifies the retained
proof with the same strict signature and identity check used for a retired
predecessor, then re-reads the complete original state. The result contains
the actual registration, signed proof, policies, revocation head and shared
sequence. It contains no signing key or verified-use token and performs no
CAS, sequence reservation, lease issuance or checkpoint publication.

This private Root administration read intentionally remains available after
the old writer lease expires. The existing runtime proof read and the
original authority-lease verifier still reject that expired writer. A cold
launcher must reopen the original protected issuer using the independently
installed public-key pin, verify the returned Agent against the original
Fleet registry, and separately establish original lease and process
retirement before attempting the strict writer/checkpoint transition.

The observation is useful for an interrupted activation because the actual
retained proof can be newer than Root's last in-memory registration. It does
not resolve that discrepancy on its own. Root must still compare the full
original checkpoint and physical material and distinguish an unactivated
authorization from an already committed successor generation.

The explicit Root qualification test
`root_retained_writer_observation_survives_actual_expiry_without_authorizing_runtime`
issues a new original 20-second lease once, waits for the original actual
clock to reach its recorded expiry, verifies both live gates reject it, and
compares the entire canonical observation and checkpoint before and after.
No time value or expiry is modified. This is an owner observation test;
positive native cold-open and same-disk cross-boot recovery remain separate
integration gates.
