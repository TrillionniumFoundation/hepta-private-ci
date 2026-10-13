# DecisionCell target-host qualification harness

`CellSplitTargetHostHarnessV1` is a deterministic source qualification
harness. It exercises the lifecycle edges that a real target host must later
prove:

- child artifact load before route activation;
- old-route fence and child dispatch receipt;
- resource budget admission;
- restart and report replay;
- rollback to the predecessor route;
- parent tombstone and no-resurrection after retire.

The JSON output has schema
`hepta.learning.cell-split.target-host-qualification.v1`. Its `origin` is
always `source-simulation` and both `productionEvidence` and
`productionActivationAuthorized` are always false. The fixture does not claim
physical power-loss injection, a CNS cutover, an external observer signature,
or a named production machine merely because `target_host_id` is supplied.

A deployment wrapper may use the report as one input to a target-host
qualification ceremony, but it must replace the simulation gates with
independently retained host receipts. The production ingestion boundary is
`CELL_SPLIT_TARGET_HOST_EVIDENCE.md`: a host/observer-signed canonical event
log is replayed by `CellSplitTargetHostEvidenceAdapterV1` and only that verifier
can issue a production receipt. In particular, a report from this
harness cannot by itself authorize `retain`, `retire`, route activation or
release.
