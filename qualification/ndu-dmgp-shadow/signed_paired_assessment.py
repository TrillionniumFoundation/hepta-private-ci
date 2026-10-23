"""Read-only signed-to-paired NDU assessment. NEVER an activation certificate.

Unlike a structural Outcome tuple, each row is signed by a distinct observer and
host meter and bound to an independently signed prospective cohort/price profile.
Identities/signatures prove provenance within nominated keys, not key custody,
perceptual truth, independent sampling, or physical calibration.
"""
import hashlib
from math import fsum, isfinite, log, sqrt
from pathlib import Path

from signed_evidence import (
    ARMS, EvidenceRejected, _hex_digest, _read_key_der, verify_envelope,
    verify_pair,
)

BASELINES = ("A0", "A1", "A2", "A3", "A4")
PIN_FIELDS = (
    "objective_digest", "critic_digest", "snapshot_digest",
    "encoder_digest", "decoder_digest", "runtime_digest",
    "evaluator_digest", "device_digest",
)


def _number(value, label, low=0.0, high=float("inf")):
    if type(value) not in (float, int):
        raise EvidenceRejected(f"invalid preregistered {label}")
    try:
        result = float(value)
    except (ValueError, OverflowError, TypeError) as exc:
        raise EvidenceRejected(f"invalid preregistered {label}") from exc
    if not isfinite(result) or not low <= result <= high:
        raise EvidenceRejected(f"invalid preregistered {label}")
    return result


def assess_signed_paired(
    signed_registration: dict,
    trials: list,
    *,
    registrar_public_key: Path,
    observer_public_key: Path,
    meter_public_key: Path,
    trusted_pins: dict,
) -> dict:
    """Validate a prospectively frozen, signed complete A0-A5 future panel.

    Trust anchors and exact source/model/objective digests are OUT-OF-BAND inputs;
    no observation, optimization result, or registration signature grants runtime
    authority. Repeats and missing sources are rejected before any statistical
    comparison; covariance and Cell attribution are separate qualifications.
    """
    keys = (registrar_public_key, observer_public_key, meter_public_key)
    key_ids = [hashlib.sha256(_read_key_der(key)).hexdigest() for key in keys]
    if len(set(key_ids)) != 3:
        raise EvidenceRejected("registrar, observer and host meter keys must differ")
    if (not isinstance(trusted_pins, dict)
            or set(trusted_pins) != set(PIN_FIELDS) | {"generation"}
            or not all(_hex_digest(trusted_pins[k]) for k in PIN_FIELDS)
            or type(trusted_pins["generation"]) is not int
            or trusted_pins["generation"] <= 0):
        raise EvidenceRejected("missing immutable external source/model pins")

    p = verify_envelope(signed_registration, registrar_public_key,
                        "independent_registrar")
    if (p.get("schema") != "hepta.ndu-dmgp.signed-paired-a0-a5.v1"
            or any(p.get(k) != trusted_pins[k] for k in PIN_FIELDS)
            or type(p.get("generation")) is not int
            or p["generation"] != trusted_pins["generation"]):
        raise EvidenceRejected("registration does not match trusted frozen sources")
    if (type(p.get("registered_at")) is not int
            or type(p.get("training_cutoff")) is not int
            or not 0 < p["registered_at"] < p["training_cutoff"]):
        raise EvidenceRejected("retroactive or unbounded registration time")
    roles = [p.get(k) for k in ("registrar_id", "actor_id",
                               "observer_id", "meter_id")]
    if any(not isinstance(r, str) or not r for r in roles) or len(set(roles)) != 4:
        raise EvidenceRejected("registrar/actor/observer/meter role collision")
    alpha = _number(p.get("familywise_alpha"), "familywise alpha",
                    1e-12, .05)
    max_time = _number(p.get("max_end_to_end_ms"), "time ceiling",
                       1e-9, 1e9)
    max_energy = _number(p.get("max_energy_joules"), "energy ceiling",
                         1e-9, 1e12)
    max_risk = _number(p.get("max_risk"), "risk ceiling", 0, 1)
    time_price = _number(p.get("price_per_ms"), "time price", 0, 1e6)
    energy_price = _number(p.get("price_per_joule"), "energy price", 0, 1e6)
    risk_price = _number(p.get("risk_price"), "risk price", 0, 1e6)
    max_skew = _number(p.get("max_av_skew_ms"), "AV skew", 0, 120)
    penalty_cap = time_price * max_time + energy_price * max_energy + risk_price * max_risk
    if not isfinite(penalty_cap):
        raise EvidenceRejected("unbounded preregistered net utility range")
    modalities = p.get("required_modalities")
    if (not isinstance(modalities, list) or not modalities
            or any(type(m) is not str or m not in ("text", "audio", "image", "video")
                   for m in modalities)
            or len(modalities) != len(set(modalities))):
        raise EvidenceRejected("invalid preregistered required outputs")
    roster = p.get("future_roster")
    if not isinstance(roster, list) or not 32 <= len(roster) <= 256:
        raise EvidenceRejected("unregistered future episode count")
    required = {}
    clusters = set()
    sources = set()
    for item in roster:
        if (not isinstance(item, dict)
                or set(item) != {"episode", "input_digest", "source_group_digest"}
                or type(item["episode"]) is not str or not item["episode"]
                or not _hex_digest(item["input_digest"])
                or not _hex_digest(item["source_group_digest"])
                or item["episode"] in required
                or item["input_digest"] in sources
                or item["source_group_digest"] in clusters):
            raise EvidenceRejected("duplicate or malformed preregistered source cluster")
        required[item["episode"]] = item
        sources.add(item["input_digest"])
        clusters.add(item["source_group_digest"])
    if not isinstance(trials, list) or len(trials) != 6 * len(roster):
        raise EvidenceRejected("missing/extra paired A0-A5 executions")
    groups = {}
    run_ids = set()
    trace_ids = set()
    for trial in trials:
        row = verify_pair(
            trial, observer_public_key, meter_public_key,
            expected_objective=trusted_pins["objective_digest"],
            expected_evaluator_digest=trusted_pins["evaluator_digest"],
            expected_device_digest=trusted_pins["device_digest"],
            training_cutoff=p["training_cutoff"],
            max_av_skew_ms=max_skew,
        )
        obs = trial["observer"]["payload"]
        meter = trial["meter"]["payload"]
        episode = row["episode"]
        registered = required.get(episode)
        if (registered is None or row["window"] != "future"
                or row["input_digest"] != registered["input_digest"]
                or obs.get("source_group_digest") != registered["source_group_digest"]
                or meter.get("source_group_digest") != registered["source_group_digest"]
                or obs["generation"] != p["generation"]
                or obs.get("actor_id") != p["actor_id"]
                or obs.get("observer_id") != p["observer_id"]
                or obs.get("critic_digest") != p["critic_digest"]
                or meter.get("meter_id") != p["meter_id"]
                or obs["artifact_digest"] != p["snapshot_digest"]
                or any(meter.get(k) != p[k] for k in
                       ("encoder_digest", "decoder_digest", "runtime_digest"))
                or not set(modalities).issubset(obs["modalities"])):
            raise EvidenceRejected("signed trial violates prospective objective/roster/model/output")
        if row["run_id"] in run_ids or row["trace_digest"] in trace_ids:
            raise EvidenceRejected("reused physical run or generated trace")
        run_ids.add(row["run_id"])
        trace_ids.add(row["trace_digest"])
        if (row["end_to_end_ms"] > max_time
                or row["energy_joules"] > max_energy
                or row["risk"] > max_risk):
            raise EvidenceRejected("hard resource/risk ceiling exceeded")
        utility = (row["quality"] - time_price * row["end_to_end_ms"]
                   - energy_price * row["energy_joules"]
                   - risk_price * row["risk"])
        if not isfinite(utility) or not -penalty_cap <= utility <= 1:
            raise EvidenceRejected("out-of-range observed net NDU")
        group = groups.setdefault(episode, {})
        if row["arm"] in group:
            raise EvidenceRejected("duplicate signed arm within future episode")
        group[row["arm"]] = utility

    if set(groups) != set(required) or any(set(g) != ARMS for g in groups.values()):
        raise EvidenceRejected("incomplete registered A0-A5 future panel")
    # net U in [-C,1], so each paired delta lies in [-(1+C),1+C].
    # The five-comparison one-sided Hoeffding radius is conservative *only*
    # under independently drawn future clusters, not distinct hash labels.
    n = len(required)
    radius = 2 * (1 + penalty_cap) * sqrt(log(5 / alpha) / (2 * n))
    paired = {}
    for arm in BASELINES:
        d = [groups[ep]["A5"] - groups[ep][arm] for ep in sorted(required)]
        mu = fsum(d) / n
        paired[arm] = {
            "observed_mean_net_delta": mu,
            "assumption_based_lcb": mu - radius,
            "lcb_positive_given_independent_clusters": mu > radius,
        }
    return {
        "schema": "hepta.ndu-dmgp.signed-paired-assessment.v1",
        "paired_future_episodes": n,
        "observer_meter_registrar_signatures_valid": True,
        "familywise_alpha": alpha,
        "hoeffding_radius": radius,
        "paired_net_ndu": paired,
        "all_lcb_positive_given_independent_clusters":
            all(v["lcb_positive_given_independent_clusters"] for v in paired.values()),
        "external_sampling_independence_verified": False,
        "original_perceptual_truth_verified": False,
        "host_calibration_verified": False,
        "conditional_covariance_identified": False,
        "causal_cell_credit_verified": False,
        "production_blockers_closed": False,
        "no_promotion_authority": True,
    }
