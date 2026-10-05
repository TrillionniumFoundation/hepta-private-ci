# AuthBus executable observability contract

`AuthBusOperationalSnapshot::prometheus_text()` renders 15 bounded, label-free
Prometheus gauges from one database snapshot. The Rust tests verify the real
renderer. `scripts/test-authbus-operations.py` checks the dashboard, alert names
and default thresholds against source. Neither test proves a live deployment.

## Exporter integration

The owner supervisor runs `AuthBusAuthorityWorker::run_until_shutdown`, supplies
fresh verified time, and hands each report to an exporter through a bounded,
nonblocking observer. A full/closed queue is an error, never silently dropped.
The exporter atomically replaces the exposed snapshot using `prometheus_text()`
and serves a read-only endpoint under scrape job `hepta-authbus`. Do not reset
`observed_at_ms` when re-serving an old snapshot. Do not synthesize Prometheus
`up` inside AuthBus: only the collector can attest transport health.

The repository now supplies the native serializer and deployable configuration,
not an installed HTTP listener, collector, alert receiver or Grafana instance.
Production activation requires evidence of those actual components, transport
ACLs, fresh snapshots, delivered test alerts and target-host failure rehearsal.

## Configuration

`prometheus.rules.json` is a JSON/YAML-compatible Prometheus rule document.
`grafana-dashboard.json` is the importable dashboard. The older uppercase files
are descriptive inventories; use these lower-case files for deployment.
Run the target installation's `promtool check rules` and Grafana import validation
before rollout and retain their versions and outputs in the deployment evidence.
A custom `AuthBusSloPolicy` requires corresponding reviewed rule thresholds;
the committed rules intentionally match only the Rust default policy.

Missing metrics, stale reports and exporter transport loss have distinct alerts.
Do not interpret absence of an unsafe-state gauge as a healthy service.
Quota totals are aggregate monitoring signals, not accounting evidence across
different quota units; investigate individual quotas before increasing limits.
Counters for request latency, signature failures and external provider/KMS
operations still belong to their concrete product adapters and are not invented
by this snapshot serializer.
