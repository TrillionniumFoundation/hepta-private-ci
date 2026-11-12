"""Describe frozen policies from original journals; never grant qualification.

The opportunity, forecast, host disposition and terminal truth are different
records. Matching their hashes proves neither complete free information nor
independent custody. Unknown truth and unmeasured resources remain unknown.
"""

from dataclasses import asdict
import math

from .check_opportunities import CheckOpportunityJournal
from .contracts import _require, digest
from .cost_ledger import summarize_costs
from .policy_costs import bind_optional_costs, snapshot_costs
from .policy_metrics import calibration_metrics, freeze_evaluation_spec
from .shadow_risk import DISPOSITIONS
from .treatment import TreatmentJournal


def evaluate_policy_journals(
    opportunities, policies, *, specification, cost_rosters, cost_receipts
):
    """Join actual journals to their common opportunity and frozen cost roster.

    Costs include only declared exclusive operations. Complete measurements are
    required even for zero-priced metrics before reporting declared net utility.
    No label authenticator, gate checker or source-independence oracle is created.
    """
    _require(
        type(opportunities) is CheckOpportunityJournal,
        "exact opportunity journal required",
    )
    cost_rosters, cost_receipts = snapshot_costs(cost_rosters, cost_receipts)
    plan = opportunities.report()
    manifest = plan["manifest"]
    _require(
        type(policies) is dict
        and set(policies) == set(manifest["policies"])
        and type(cost_rosters) is dict
        and set(cost_rosters) == set(policies)
        and type(cost_receipts) is dict
        and set(cost_receipts) == set(policies),
        "frozen policy roster changed",
    )
    _require(
        len(set(manifest["policies"].values())) == len(policies),
        "one frozen policy manifest cannot count as multiple executed policies",
    )
    paths = []
    for journal in policies.values():
        _require(type(journal) is TreatmentJournal, "exact treatment journal required")
        path = journal.shadow.path
        _require(
            all(not path.samefile(other) for other in paths),
            "one physical policy journal cannot count as multiple executions",
        )
        paths.append(path)
    _require(
        type(specification) is dict
        and set(specification)
        == {"schema", "utility_unit", "losses", "rates", "bins", "cost_roster_sha256"},
        "evaluation specification fields changed",
    )
    spec = freeze_evaluation_spec(
        cost_rosters,
        losses=specification["losses"],
        rates=specification["rates"],
        utility_unit=specification["utility_unit"],
        bins=specification["bins"],
    )
    _require(
        spec == specification and digest(spec) == manifest["evaluation_spec_sha256"],
        "evaluation specification or cost roster changed after freeze",
    )
    costs = {
        policy: summarize_costs(
            cost_rosters[policy], cost_receipts[policy], spec["rates"]
        )
        for policy in policies
    }
    # Cross-policy duplicate operations and overlapping resource/clock intervals
    # must also refuse; separate per-arm aggregation would miss these.
    summarize_costs(
        [item for rows in cost_rosters.values() for item in rows],
        [item for rows in cost_receipts.values() for item in rows],
    )
    reports, roots, consumption = {}, {}, {}
    for policy, journal in policies.items():
        consumption[policy] = opportunities.audit_treatment(journal)
        with journal.shadow._transaction() as connection:
            registry, base, _, state, root, _ = journal._read(connection)
        shadow, predictions, finishes, labels, shadow_root, _ = base
        _require(
            digest(shadow) == manifest["policies"][policy]
            and shadow["roster"] == manifest["roster"]
            and shadow["target"] == manifest["target"],
            "policy/target/roster drift",
        )
        roots[policy] = dict(
            shadow=shadow_root, treatment=root, registry=digest(registry)
        )
        bind_optional_costs(state, cost_rosters[policy], cost_receipts[policy])
        free = {
            prediction.snapshot.trajectory_id: prediction
            for prediction in predictions
            if prediction.snapshot.observed_step == manifest["frontier"]
        }
        rows, missing_views = [], []
        for attempt in shadow["roster"]:
            identity = attempt["trajectory_id"]
            ticket, prediction = plan["tickets"].get(identity), free.get(identity)
            if ticket is not None and prediction is not None:
                _require(
                    digest(asdict(prediction.snapshot))
                    == ticket["free_snapshot_sha256"],
                    "policy free snapshot differs from original opportunity",
                )
            else:
                missing_views.append(identity)
            disposition = state["dispositions"].get(identity)
            finish, label = finishes.get(identity), labels.get(identity)
            _require(
                disposition is None
                or finish is None
                or disposition["disposition"] == finish,
                "host disposition/finish mismatch",
            )
            rows.append(
                dict(
                    disposition=disposition["disposition"] if disposition else None,
                    truth=label.error if label is not None else None,
                    probability=prediction.probability
                    if prediction is not None
                    else None,
                    finished=finish is not None,
                    label_recorded=label is not None,
                )
            )
        count = len(rows)
        missing_dispositions = sum(row["disposition"] is None for row in rows)
        accepted = [row for row in rows if row["disposition"] == "accept"]
        false_accepts = sum(row["truth"] is True for row in accepted)
        unknown_accepts = sum(row["truth"] is None for row in accepted)
        loss_bounds = []
        for row in rows:
            actions = (
                [row["disposition"]] if row["disposition"] is not None else DISPOSITIONS
            )
            truths = (
                ["error" if row["truth"] else "correct"]
                if row["truth"] is not None
                else ["correct", "error"]
            )
            values = [
                spec["losses"][action][truth] for action in actions for truth in truths
            ]
            loss_bounds.append((min(values), max(values)))
        bounds = [
            math.fsum(pair[index] for pair in loss_bounds) / count for index in (0, 1)
        ]
        complete_outcomes = all(
            row["finished"]
            and row["label_recorded"]
            and row["disposition"] is not None
            and row["truth"] is not None
            for row in rows
        )
        cost = costs[policy]
        pending = sorted(set(state["starts"]) - set(state["completions"]))
        measured = (
            cost["declared_roster_complete"]
            and all(value is not None for value in cost["totals"].values())
            and not pending
        )
        net = (
            -bounds[0] - cost["declared_receipt_utility"] / count
            if complete_outcomes and measured
            else None
        )
        reports[policy] = dict(
            planned=count,
            observed_finishes=sum(row["finished"] for row in rows),
            known_terminal_labels=sum(row["truth"] is not None for row in rows),
            missing_terminal_label_records=sum(
                not row["label_recorded"] for row in rows
            ),
            unknown_terminal_labels=sum(row["truth"] is None for row in rows),
            missing_host_dispositions=missing_dispositions,
            by_disposition={
                name: sum(row["disposition"] == name for row in rows)
                for name in DISPOSITIONS
            },
            accepted_count=len(accepted),
            acceptance_coverage=len(accepted) / count
            if not missing_dispositions
            else None,
            acceptance_coverage_bounds=[
                len(accepted) / count,
                (len(accepted) + missing_dispositions) / count,
            ],
            observed_false_accept_count=false_accepts,
            observed_accepted_error_bounds=[
                false_accepts / len(accepted),
                (false_accepts + unknown_accepts) / len(accepted),
            ]
            if accepted
            else None,
            false_accept_per_planned_bounds=[
                false_accepts / count,
                (false_accepts + unknown_accepts + missing_dispositions) / count,
            ],
            postdecision_clean_reject_count=sum(
                row["disposition"] == "reject" and row["truth"] is False for row in rows
            ),
            postdecision_clean_interruption_count=sum(
                row["disposition"] == "interrupted" and row["truth"] is False
                for row in rows
            ),
            property_or_authority_false_reject_rate=None,
            rejection_interpretation="clean named target does not discharge authorization or other acceptance obligations",
            calibration=calibration_metrics(rows, spec["bins"]),
            missing_common_free_snapshot_ids=missing_views,
            opportunity_consumption=consumption[policy],
            terminal_loss_per_planned_bounds=bounds,
            declared_mean_terminal_utility=-bounds[0] if complete_outcomes else None,
            declared_mean_net_utility=net,
            cost=cost,
            actual_optional_starts=len(state["starts"]),
            actual_optional_completions=len(state["completions"]),
            pending_optional_operation_ids=pending,
            exposure_at_disposition={
                status: sum(
                    state["exposures"]
                    .get(attempt["trajectory_id"], {})
                    .get("status", "missing")
                    == status
                    for attempt in shadow["roster"]
                )
                for status in (
                    "checked",
                    "unchecked",
                    "abstained",
                    "pending",
                    "missing",
                )
            },
            label_authentication=journal.shadow.authentication_report(
                expected_ledger_sha256=shadow_root
            ),
        )
    for policy, journal in policies.items():
        with journal.shadow._transaction() as connection:
            current = journal._read(connection)
        _require(
            current[4] == roots[policy]["treatment"]
            and current[1][4] == roots[policy]["shadow"],
            "policy journal changed during evaluation",
        )
        _require(
            opportunities.audit_treatment(journal) == consumption[policy],
            "opportunity consumption changed during evaluation",
        )
    _require(
        opportunities.report()["ledger_sha256"] == plan["ledger_sha256"],
        "opportunity journal changed during evaluation",
    )
    return dict(
        schema="hepta.verify.policy-evaluation.v1",
        manifest_sha256=plan["manifest_sha256"],
        evaluation_spec_sha256=digest(spec),
        opportunity_ledger_sha256=plan["ledger_sha256"],
        target=manifest["target"],
        policy_roots=roots,
        policies=reports,
        opportunity_denominators=dict(
            planned=len(manifest["roster"]),
            retained_tickets=len(plan["tickets"]),
            pending_unknown_draws=len(plan["pending_opportunity_ids"]),
            unstarted=len(plan["unstarted_opportunity_ids"]),
        ),
        declared_source_groups=sorted(
            {row["source_group"] for row in manifest["roster"]}
        ),
        source_group_count_is_independent_sample_size=False,
        common_free_snapshot_bindings_complete=all(
            not report["missing_common_free_snapshot_ids"]
            and not report["opportunity_consumption"]["missing_consumption_ids"]
            for report in reports.values()
        ),
        bounds_kind="finite-roster missing-data bounds, not confidence intervals",
        entire_free_information_verified=False,
        independent_terminal_truth_verified=False,
        cross_journal_wall_clock_order_verified=False,
        full_physical_cost_complete=False,
        causal_paid_check_value_established=False,
        scientific_admission="HOLD",
        production_authority="NONE",
    )
