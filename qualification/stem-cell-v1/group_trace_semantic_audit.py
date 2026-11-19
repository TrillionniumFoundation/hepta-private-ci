"""Pure standard-library semantic audit of public Group System2 traces.

This checks causal trace consistency, not proof of genuine model execution.
"""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def verify_trace_semantics(row, record, public_answer, family):
    if record.get("schema") != "hepta.group.system2-full-trace.v2":
        raise ValueError("versioned replayable System2 trace required")
    candidates = record.get("proposed_candidates")
    statuses = record.get("verifier_statuses")
    steps = row.get("steps")
    if (type(steps) is not int or not 1 <= steps <= 8
            or type(candidates) is not list or len(candidates) != steps
            or type(statuses) is not list or len(statuses) != steps
            or family not in ("dependency", "constraint", "temporal", "composition")
            or (public_answer is not None and
                (type(public_answer) is not int or not 0 <= public_answer < 8))):
        raise ValueError("bounded public evidence and proposal inventory required")
    entries = record.get("trace")
    if type(entries) is not list:
        raise ValueError("callback array required")
    proposal_entries = [x for x in entries if x.get("kind") == "propose"]
    verifier_entries = [x for x in entries if x.get("kind") == "verify"]
    value_entries = [x for x in entries if x.get("kind") == "value"]
    if len(proposal_entries) != steps or len(verifier_entries) != steps:
        raise ValueError("candidate/verification count mismatch")
    for index, (candidate, feedback, proposed, verified) in enumerate(
            zip(candidates, statuses, proposal_entries, verifier_entries)):
        if type(candidate) is not str or len(candidate) != 1 or not "A" <= candidate <= "H":
            raise ValueError("out-of-domain proposed answer")
        expected = ("missing_evidence" if public_answer is None
                    else "supported" if ord(candidate) - 65 == public_answer
                    else "unsupported_" + family)
        if feedback != expected:
            raise ValueError("verifier feedback contradicts public evidence or candidate")
        accepted = expected == "supported" and (
            row["execution_mode"] == "ndu" or index == steps - 1)
        if proposed.get("output_digest") != digest(candidate):
            raise ValueError("propose callback hash does not bind candidate")
        if verified.get("output_digest") != digest([accepted, expected]):
            raise ValueError("verify callback hash does not bind public evidence and acceptance")
        if accepted and index < steps - 1:
            raise ValueError("NDU failed to stop after verified answer")
    if record.get("final_candidate") != candidates[-1]:
        raise ValueError("terminal model proposal differs from recorded output")
    terminal_accepted = statuses[-1] == "supported"
    if (row["execution_status"] == "verifier_accepted_not_independent_eval") != terminal_accepted:
        raise ValueError("terminal System2 status disagrees with public verifier")
    if row["execution_mode"] == "ndu":
        decisions = record.get("ndu_decisions")
        if type(decisions) is not list or len(decisions) != len(value_entries):
            raise ValueError("NDU decisions cannot be detached from value callbacks")
        for index, (choice, value) in enumerate(zip(decisions, value_entries)):
            if type(choice) is not dict or type(choice.get("continue_computation")) is not bool:
                raise ValueError("typed NDU continuation decision required")
            if choice.get("estimate_id") != value.get("output_digest"):
                raise ValueError("NDU decision estimate differs from value callback digest")
            final_stop = index == len(decisions) - 1 and row["execution_status"].startswith("ndu_stop:")
            if choice["continue_computation"] == final_stop:
                raise ValueError("NDU continuation/stopping state does not match actual trace")
            if final_stop and choice.get("reason") != row["execution_status"].split(":", 1)[1]:
                raise ValueError("NDU stopping reason does not match trace outcome")
    elif record.get("ndu_decisions") != []:
        raise ValueError("fixed-depth arm may not contain NDU decisions")
    return True
