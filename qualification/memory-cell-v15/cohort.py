"""Validate host-owned prospective evidence; hashes do not authenticate provenance.

A node ID is never a source task ID. Repeated node observations of one task must
retain its source cluster. The case cohort binds logical source units before any
predictor runs. Independence, timestamps and actual permitted inputs remain host
responsibilities; this validator does not prove semantic utility.
"""

INFORMATION = ("memory", "training_inputs", "executor", "budget", "encoder",
               "decoder", "tool_permissions")
PHASES = ("train", "calibration", "selection", "final")


def check_registration(registration, cases, protocol, data_digest, settings_digest):
    """Return fail-closed reasons without turning missing provenance into samples."""
    if not isinstance(registration, dict):
        return ["missing_frozen_cohort_registration"]
    reasons = []
    if (registration.get("schema") != "hepta.memory.frozen-cohort.v1"
            or registration.get("data") != data_digest
            or registration.get("protocol_settings") != settings_digest):
        reasons.append("cohort_identity_mismatch")
    look = registration.get("look_index")
    if type(look) is not int or not 1 <= look <= protocol.planned_looks:
        reasons.append("unregistered_monitoring_look")
    freeze = registration.get("frozen_at")
    if type(freeze) is not int or freeze < 0:
        reasons.append("invalid_cohort_freeze")
        return reasons
    phases = registration.get("phases", {})
    if not isinstance(phases, dict) or set(phases) != set(PHASES):
        return reasons + ["missing_phase_isolation"]
    used, final_clusters = set(), set()
    for name in PHASES:
        phase = phases[name]
        if not isinstance(phase, dict):
            reasons.append("invalid_phase:" + name)
            continue
        clusters, start, end = (phase.get("clusters"), phase.get("start"), phase.get("end"))
        if (not isinstance(clusters, list) or not clusters
                or any(not isinstance(x, str) or not x for x in clusters)
                or len(set(clusters)) != len(clusters)
                or type(start) is not int or type(end) is not int or not 0 <= start <= end):
            reasons.append("invalid_phase:" + name)
            continue
        current = set(clusters)
        if current & used:
            reasons.append("phase_cluster_leakage:" + name)
        used |= current
        if name == "final":
            final_clusters = current
            if start <= freeze:
                reasons.append("final_not_after_freeze")
        elif end > freeze:
            reasons.append("nonfinal_after_freeze:" + name)
    if final_clusters != {case.cluster for case in cases}:
        reasons.append("final_cluster_roster_mismatch")
    units = registration.get("final_units", {})
    if not isinstance(units, dict) or set(units) != {case.key for case in cases}:
        return reasons + ["final_unit_roster_mismatch"]
    source_units = set()
    final = phases["final"]
    if not isinstance(final, dict):
        return reasons
    for case in cases:
        row = units[case.key]
        if (not isinstance(row, dict) or not isinstance(row.get("unit"), str)
                or not row.get("unit") or row.get("cluster") != case.cluster
                or type(row.get("observed_at")) is not int
                or type(final.get("start")) is not int or type(final.get("end")) is not int
                or not final["start"] <= row["observed_at"] <= final["end"]):
            reasons.append("invalid_final_unit:" + case.key)
            continue
        if row["unit"] in source_units:
            reasons.append("replicated_source_unit:" + row["unit"])
        source_units.add(row["unit"])
    comparisons = registration.get("comparisons")
    if (not isinstance(comparisons, list) or not comparisons
            or any(not isinstance(pair, list) or len(pair) != 2
                   or any(not isinstance(x, str) or not x for x in pair) for pair in comparisons)
            or len({tuple(pair) for pair in comparisons}) != len(comparisons)
            or len(comparisons) > protocol.comparisons):
        reasons.append("invalid_frozen_comparison_roster")
    return reasons


def check_arms(registration, candidate, incumbent):
    if not isinstance(registration, dict):
        return []  # Already rejected before evaluation.
    comparisons = registration.get("comparisons")
    if not isinstance(comparisons, list) or [candidate.bundle, incumbent.bundle] not in comparisons:
        return ["unregistered_candidate_comparison"]
    reasons = []
    arms = registration.get("arms", {})
    for model in (candidate, incumbent):
        declared = arms.get(model.bundle) if isinstance(arms, dict) else None
        actual = {key: getattr(model, key) for key in INFORMATION}
        if not isinstance(declared, dict) or declared != actual or any(not isinstance(x, str) or not x for x in actual.values()):
            reasons.append("unbound_arm_information:" + model.bundle)
    return reasons
