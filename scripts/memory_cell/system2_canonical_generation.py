"""Sound local generation pruning for equal-valued arithmetic operands.

Research-only optimization: equal-value operand pairs yield the same numeric
successor multiset regardless of their expression provenance. Keep the first
valid proof representative; the runtime independent verifier still checks each
full proof. Prune BEFORE doing duplicate rational arithmetic. Do not count
uncomputed suppressed options as generated successors; record filter work
separately. This does not reduce the cost of checking pair equality to zero.
"""

from itertools import combinations


def canonical_successors(terms, counts):
    """Yield a representative of every one-step reachable NUMERIC state.

    `counts` is caller-owned and cumulative. It records cheap pair comparisons,
    eliminated entire pair branches, and symmetry-pruned arithmetic variants.
    """
    if not isinstance(counts, dict) or any(
        k not in counts
        for k in ("pair_checks", "pair_skips", "symmetry_skips", "emitted")
    ):
        raise ValueError("bounded generation counters required")
    seen_pairs = set()
    for i, j in combinations(range(len(terms)), 2):
        a, ap = terms[i]
        b, bp = terms[j]
        counts["pair_checks"] += 1
        key = tuple(sorted((a, b)))
        if key in seen_pairs:
            counts["pair_skips"] += 1
            continue
        seen_pairs.add(key)
        rest = tuple(term for k, term in enumerate(terms) if k not in (i, j))
        options = [
            (a + b, ap + bp + ("+",)),
            (a * b, ap + bp + ("*",)),
            (a - b, ap + bp + ("-",)),
        ]
        if a == b:
            counts["symmetry_skips"] += 1
        else:
            options.append((b - a, bp + ap + ("-",)))
        if b:
            options.append((a / b, ap + bp + ("/",)))
        if a:
            if a == b:
                counts["symmetry_skips"] += 1
            else:
                options.append((b / a, bp + ap + ("/",)))
        for value, proof in options:
            counts["emitted"] += 1
            yield rest + ((value, proof),)
