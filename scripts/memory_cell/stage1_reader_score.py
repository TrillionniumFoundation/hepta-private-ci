"""Dependency-free replay of frozen Reader diagnostic token-F1, not semantic QA.

Matches selector_answer_metrics.answer_scores but avoids selector_answering's
Torch import on read-only audit runners. Labels are opened after raw answers.
"""

from collections import Counter
import re
import string

ABSTAIN = "I do not have enough evidence."


def normalized(text):
    text = re.sub(r"\[E[1-9][0-9]*\]", "", text).lower()
    text = "".join(char for char in text if char not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def answer_scores(raw, answers, unanswerable):
    if answers is None or unanswerable is None:
        return dict(exact_match=None, f1=None)
    abstained = raw.strip() == ABSTAIN
    if unanswerable:
        return dict(exact_match=float(abstained), f1=float(abstained))
    if not answers:
        raise ValueError("missing gold answer is not unanswerability")
    pred = normalized(raw)
    values = []
    for gold in answers:
        expected = normalized(gold)
        a, b = pred.split(), expected.split()
        common = sum((Counter(a) & Counter(b)).values())
        f1 = 2 * common / (len(a) + len(b)) if a and b else float(a == b)
        values.append((float(pred == expected), f1))
    return dict(exact_match=max(v[0] for v in values), f1=max(v[1] for v in values))
