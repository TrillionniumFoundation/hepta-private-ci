"""Label-blind grammar-specific exact binding baseline; research-only.

No source IDs, labels, support indices, metadata, Encoder or hidden annotation read.
Accepted tasks are deliberately narrow: exactly two ownership and storage edges.
This is NOT a general natural-language reasoner and cannot solve MultiRC prose.
"""
import re

OWN = re.compile(r"The ([a-z]+) belongs to ([A-Z][a-z]+)\.", re.ASCII)
STORE = re.compile(r"([A-Z][a-z]+) stores all their possessions in the ([a-z]+) box\.", re.ASCII)
QUESTION = re.compile(r"Where is the ([a-z]+) stored\?", re.ASCII)
CANDIDATE = re.compile(r"The ([a-z]+) box\.", re.ASCII)


class RejectGrammar(ValueError):
    pass


def infer_public(facts, question, candidate):
    """Return (prediction, proof sentence IDs), 1-based. No gold-label argument."""
    if (type(facts) not in (tuple, list) or len(facts) != 4
            or not all(isinstance(s, str) and len(s) <= 256 for s in facts)
            or not isinstance(question, str) or not isinstance(candidate, str)
            or len(question) > 256 or len(candidate) > 256):
        raise RejectGrammar("exact bounded public four-fact query required")
    qm, cm = QUESTION.fullmatch(question), CANDIDATE.fullmatch(candidate)
    if qm is None or cm is None:
        raise RejectGrammar("unknown public question or candidate")
    owners, stores = {}, {}
    for i, fact in enumerate(facts, 1):
        own, store = OWN.fullmatch(fact), STORE.fullmatch(fact)
        if own is not None:
            obj, person = own.groups()
            if obj in owners:
                raise RejectGrammar("ambiguous object ownership")
            owners[obj] = (person, i)
        elif store is not None:
            person, color = store.groups()
            if person in stores:
                raise RejectGrammar("ambiguous person storage")
            stores[person] = (color, i)
        else:
            raise RejectGrammar("unrecognized evidence")
    if (len(owners) != 2 or len(stores) != 2 or len(set(p for p, _ in owners.values())) != 2
            or {p for p, _ in owners.values()} != set(stores)
            or len({c for c, _ in stores.values()}) != 2
            or qm[1] not in owners or cm[1] not in {c for c, _ in stores.values()}):
        raise RejectGrammar("missing or non-bijective relation")
    person, own_source = owners[qm[1]]
    color, store_source = stores[person]
    return int(color == cm[1]), tuple(sorted((own_source, store_source)))


def infer_case(case):
    """Whitelist ONLY public fields, never consult case.label or evidence hints."""
    return infer_public(case.facts, case.question, case.candidate)


def run_panel(cases):
    cases = tuple(cases)
    if not cases:
        raise ValueError("nonempty complete panel required")
    predicted = [infer_case(c)[0] for c in cases]
    # Gold labels are used ONLY after predictions are complete, for postseal scoring.
    correct = sum(p == c.label for p, c in zip(predicted, cases))
    return {"rows": len(cases), "correct": correct, "accuracy": correct / len(cases),
            "model_calls": 0, "optimizer_steps": 0,
            "scope": "narrow_synthetic_ownership_storage_grammar_not_natural_language"}
