# Declared exclusive cost receipts

Freeze a `CostItem` roster before a comparison. Every item names operation,
attempt, stage, resource attribution scope and monotonic clock. Preserve failed,
cancelled, not-run and unpublished attempts; publication is separate from status.

`CostReceipt` retains an exclusive interval and measured CPU, peak RSS, energy
and external charge, or explicit measurement gaps. Parent and child CPU must
not be charged twice. A process-time delta excludes child CPU unless separately
measured. Peak RSS is a maximum, never a sum or a host-wide concurrent peak.

`summarize_costs` refuses overlaps within one declared resource/clock. Parallel
resource-seconds are distinct from makespan. With omitted operations, complete
totals, global elapsed and peak RSS remain null; observed partial values retain
their own names. Different clocks do not form a global elapsed interval.

Optional explicit rates convert receipt metrics to declared utility. A zero
rate is a pricing assumption, not evidence of free work. Missing priced metrics
prevent a complete utility total. Roster completeness does not prove physical
coverage or truthful attribution; `full_physical_cost_complete` remains false.

Seven behavior tests passed, with an independent aggregation review. Full
cost-matched real-task benefit remains an external experiment requirement.
