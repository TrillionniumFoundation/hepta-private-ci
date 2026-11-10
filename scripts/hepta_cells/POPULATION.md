# A frozen 1 + 2 + 7 population

The population plan assembles the existing experimental Cell owner and producer
routes. The **one contract** is the existing identity/state/budget/receipt/bundle
lifecycle. The **two trainable families** reuse `SemanticComponent` and
`TemporalComponent`; the latter defaults to the existing PRED-1 GRU. Seven
functional lineages organize those components. A lineage label describes an
assigned responsibility; it does not establish that a component has learned it.

| Lineage | Initial route | Initial local plasticity |
| --- | --- | --- |
| PERC | Shared features and private head | Frozen |
| MEM | Shared features and private association/ranking head | Private head |
| PRED | GRU recurrent state and prediction head | Kernel and heads |
| CTRL | GRU policy/decision component | Frozen |
| VERIFY | Shared features and private assessment head, with deterministic checks | Frozen |
| ACT | GRU skill component, with separately injected host tool capability | Frozen |
| LEARN | Deterministic host workflow through `ToolCell` | Frozen; organizes other Cells' training and evaluation |

This is an initial allocation for experiments, not an architecture ranking. The
plan accepts the implemented diagonal recurrence as a temporal control. HCSN
remains outside this admitted registry and is not a prerequisite for the seven
lineages. Existing deterministic retrieval, rule, numerical and tool components
can support any lineage without acquiring neural update privileges.

## What is frozen

[`CellSpec` and `PopulationPlan`](population.py) bind the principal, agent, logical
Cell ID, lineage, actual family/kernel, initial component identity, objective
identifier, local parameter scope, update-rule digest, evaluation-profile digest,
observation interval and exact work/input/output/state/time budgets. Actual
semantic objectives, dimensions, provider bindings and temporal configurations
remain bound by the existing component identity and compatibility bundle.

Every plan retains all seven lineages and 7–128 unique logical Cell IDs. Several
instances may share a lineage. The default cap is **two plastic logical Cells**;
an explicitly chosen cap may range from zero to three. Repeated run partitions of
the same Cell do not create additional update points. Distinct trainable instances
of the same lineage each consume a slot. Owner row limits and per-run work budgets
are separate bounds. The plan's canonical digest is independent of input ordering.

The host supplies the plan before creating the first Cell. The SQLite owner
persists it and checks a supplied plan against the retained one on reopen.
Reopening with no plan still enforces the retained policy. Adding a plan to an
already populated unplanned database requires a separate explicit migration.

## Construct a population from loaded components

The host first loads real components and their complete pinned bundles. In this
example `loaded` maps the seven lowercase Cell IDs to those components, with
temporal components already bound to `run:one`. `objectives`, `profiles`, `budgets`
and `views` are the host's frozen definitions, not values supplied by candidates.
Each `profiles[cell_id]` has `update_rule` and `evaluation_profile` digests matching
the actual proposed bundle lineage. `host_qualification` is the explicit host
evaluation callback used by the existing owner.

```python
from hepta_cells.lifecycle import CellOwner, Partition
from hepta_cells.population import CellSpec, PopulationPlan

routes = (
    ("perc", "PERC", "shared_semantic", "shared_head", "frozen"),
    ("mem", "MEM", "shared_semantic", "shared_head", "heads"),
    ("pred", "PRED", "stateful_temporal", "gru", "kernel_and_heads"),
    ("ctrl", "CTRL", "stateful_temporal", "gru", "frozen"),
    ("verify", "VERIFY", "shared_semantic", "shared_head", "frozen"),
    ("act", "ACT", "stateful_temporal", "gru", "frozen"),
    ("learn", "LEARN", "deterministic", "tool_wrapper", "frozen"),
)
specs = []
for cell_id, lineage, family, kernel, trainable in routes:
    plastic = trainable != "frozen"
    specs.append(CellSpec(
        cell_id=cell_id, lineage=lineage, family=family, kernel=kernel,
        initial_identity=loaded[cell_id].identity.digest,
        objective=objectives[cell_id], trainable=trainable,
        update_rule=profiles[cell_id]["update_rule"] if plastic else None,
        evaluation_profile=profiles[cell_id]["evaluation_profile"] if plastic else None,
        min_observations=8, budget=budgets[cell_id], total_work_units=1_000_000,
    ))
plan = PopulationPlan("principal:one", "agent:one", tuple(specs))
owner = CellOwner("cells.sqlite", qualify=host_qualification, population=plan)
for spec in plan.cells:
    partition = Partition(plan.principal_id, plan.agent_id, spec.cell_id, "run:one")
    owner.create(partition, loaded[spec.cell_id], retrieval_view=views[spec.cell_id],
                 budget=spec.budget, total_work_units=spec.total_work_units)
owner.close()

# Resume existing partitions; do not call create again for the same partition.
owner = CellOwner("cells.sqlite", qualify=host_qualification)
assert owner.population_plan == plan
```

This is construction from host-supplied real implementations, not a substitute
model or a complete task runner. Registering `ToolCell` does not supply its tool
capability or implement the LEARN workflow. Those remain explicit host inputs.

## Ports, adoption and subsequent tasks

[`PopulationPolicy`](population_owner.py) checks concrete component classes and
their actual family/kernel bindings. Semantic calls retain their `{"inputs": [...]}`
payload. Temporal calls retain the explicit `observe` and `predict` schemas,
including episode and cursor checks. Retrieval views, rule grammar, numerical
operations and host tool descriptors retain their existing validation. This is a
registry of implemented interfaces, not a general multimodal adapter ABI.

Local adoption still requires the existing host qualification callback. Within
the owner's transaction it also checks the current source identity, immediate
bundle successor, allowed parameter changes, frozen update/evaluation digests and
unused observation interval. A candidate cannot declare a wider trainable scope.
The cap governs adoption of local parameter updates. It does not intercept raw
trainer calls or prove that a host actually ran the optimizer named by a digest;
training execution and its complete cost still require the original receipts.
Only successful unique committed observation intents with applied state count:
semantic input calls and temporal `observe` calls. Exact replays, `predict` calls,
failed or over-budget outcomes, resets, restores and rollbacks do not manufacture
observations. Consumed evidence remains consumed after rollback.

The latest admitted version belongs to the logical Cell; hidden state belongs to
each principal/agent/Cell/run partition. A new run must load that latest version
and starts with fresh state. For a temporal component, construct a new
`TemporalComponent(current_kernel, current_bundle, "run:two")` using the actual
admitted parameters, then create the new partition with the same spec budgets.
Existing runs retain their own state and exact admitted version. Every adoption
and rollback advances a monotonic logical epoch. A stale run cannot adopt after
another run changes that epoch, even when rollback restores identical parameter
bytes (A-to-B-to-A). Only observations from the current logical epoch satisfy the
next update interval. A newly opened run captures the current epoch; historical
request replay retains its original receipt. Reopening refuses missing policy,
current-version or partition-admission records instead of reinstalling an initial
version. This does not promise
state migration between parameter generations or activation in the native daemon.

Receipts and checkpoints carry the population digest, lineage, Cell ID, local
scope and logical epoch. These commitments establish consistency. They do not authenticate the
host, prove truthful evaluation, authorize external effects, or grant native
production execution. The existing source/effect owners retain those duties.

## Qualification and further differentiation

Population/owner tests exercise policy enforcement, transaction behavior,
isolation, replay and cold-run loading. Temporal numerical qualification checks
actual gradients and optimizer/state restoration on bounded examples. Neither
category establishes independent task benefit or a preferred neural architecture.
Scientific acceptance still needs held-out tasks, credible baselines, equal
information and tuning opportunities, and complete training/serving/recovery cost.

Split a lineage only after a specified hypothesis is supported: incompatible loss
or representations, different update timescales, reproducible negative transfer,
or a required separation of state/permissions. Compare the split against sharing
under the same total budget, including retained-task regressions. Consider merging
instances that learn the same function when sharing preserves retained ability.
Instance count should follow workload, state isolation and measured parallelism.
This version performs no automatic split, merge or population search; a changed
plan is a new reviewed experimental configuration with its own evidence.
