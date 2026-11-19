# Actual N256 warm-1 execution

The original frozen request executed successfully in GitHub run
`44462874515`, job `135353619601`, artifact `14501310345`, at source head
`c8e36e8579153761adee4ed84d44b40ec6d36000`. The prior YAML registration failure
and Ubuntu 26.04/Python 3.12.3 setup failure remain recorded in
`WORKFLOW_REPAIR.json`; the latter's full decoded job log is retained here.

The artifact contains an actual `SUCCESS` terminal and a 560,358-byte capsule.
`RESULT.json` records one dynamic step, two dense matrix exponentials, one
serialization, and zero Torch/optimizer calls. Those counts are producer fields;
the original child did not instrument an input-read counter. The independent
review verifies all 15 manifest members, the GitHub ZIP digest, the original
runtime/resource policy, zero readable ancestor OOM counters before and after,
and the actual capsule's 69,728 finite coordinates and nine packets.

The original numerical child used 0.771189599 seconds wall time, 0.767889 CPU
seconds, and 82,989,056 bytes peak RSS. The five probability/content balance
residuals have maximum absolute value 6.535075181468477e-16. The probability
hit mass is 0.0052714509584328596 and its discounted value is
0.005271185866070254 over the fixed interval 0 to 0.001.

This is the frozen warm-1 dense reference. Candidate comparison remains zero
coordinates. It does not establish long-time continuation, training gradients,
the full N256 qualification, or a same-budget task advantage. The source
artifact's `qualification`, `largegrid_qualification`, and `all_closed` fields
remain false.

Reproduce the byte/policy/conservation review without another matrix exponential:

```sh
python3 -m qualification.hcsn_currentstate_n256_firststep_dense_oracle_hosted.review_actual
```

`artifact-14501310345.zip` is the exact downloaded ZIP. `originals/` contains
its byte-identical members. `ARTIFACT_METADATA.json`, `RUN_METADATA.json`, and
`JOB_LOG.txt.gz` retain the GitHub metadata and decoded job log. Gzip preserves
original log whitespace; `PREVIOUS_SETUP_FAILURE.log.gz` preserves the earlier
setup failure.
