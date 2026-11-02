"""Independent service-outcome enumeration for declared open-loop READ plans.

This reference enumerates the full Bernoulli product rather than using latest-
success product weights. It does not generate or inspect a real task path.
"""
from itertools import product


def score(schedule, deadlines, baseline_correct, after_read_correct, success, fee=.04,
          normalizer=4):
    total = 0.
    for outcomes in product((False, True), repeat=len(schedule)):
        probability = 1.
        for arrival, succeeded in zip(schedule, outcomes):
            probability *= success[arrival] if succeeded else 1-success[arrival]
        if probability == 0:
            continue
        reward = 0.
        for deadline in deadlines:
            latest = max((arrival for arrival, succeeded in zip(schedule, outcomes)
                          if succeeded and arrival <= deadline), default=None)
            reward += baseline_correct[deadline] if latest is None else after_read_correct[latest, deadline]
        total += probability*reward/normalizer
    return total-fee*len(schedule)
