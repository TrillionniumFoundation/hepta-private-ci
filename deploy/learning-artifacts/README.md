# learning.artifacts operational assets

These assets consume the Prometheus text emitted by
`ArtifactOwnerOperationalMetricsV1::prometheus_text`. Unknown owner-supplied
retention values are omitted rather than exported as zero.

The alert rules deliberately page on persistence-unknown, recovery
reconciliation failure and identity conflict. They warn on stale pending work,
stalled drain and withdrawal blocking. Thresholds are deployment defaults and
must be reviewed against target-host SLOs before activation.

These files do not establish target-host durability, operator acceptance,
activation, promotion or release authority.
