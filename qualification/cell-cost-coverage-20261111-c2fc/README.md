# Incomplete cost coverage remains unknown

This change fixes report semantics for grouped research records. A numeric measurement with unknown coverage is not a complete arm cost. A registered opportunity without an observation is not a zero-cost attempt. The report now retains those arm totals and the campaign total as `null`, while `recorded_cost_subtotals` and `recorded_campaign_subtotal` preserve the explicitly supplied partial measurements.

The existing statistical gate already refused advancement for incomplete coverage. This change does not alter effect thresholds, source independence requirements, production authority or adoption policy.

## Source and validation

The three-file patch was developed against exact source `0c99a30dbe9307d48aa50ffc63404235ade8ae9c` (#5807). Original Git blob identities and the final postimages are listed in [manifest.json](manifest.json).

The added or strengthened regression cases fail against the original implementation (four failures and one error). The five research modules then pass 76 tests after the fix. See [pre-fix-recovered.log](pre-fix-recovered.log) and [research-post-fix-recovered.log](research-post-fix-recovered.log). A real `just fmt` run on ai395 exits zero; all three Python ASTs remain identical across maintenance, with only test formatting changing. Per repository guidance, behavior tests were not rerun after that final formatting step. [maintenance.json](maintenance.json) retains that boundary.

The cloud executor was replaced during this work. The initial lost workspace was reconstructed from authenticated GitHub blobs, and the logs retained here come from fresh execution after reconstruction. An earlier unobserved test invocation is not counted.

## Limits

This is file-scoped engineering validation, not full repository CI or independent scientific confirmation. New real confirmation units: 0. Scientific adoption remains HOLD; production authority and research advancement remain false. The recorded partial subtotal may be zero when no numerical measurements exist; that field is explicitly a subtotal and never substitutes for the unknown complete campaign cost.
