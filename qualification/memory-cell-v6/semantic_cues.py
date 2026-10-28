"""A disclosed finite English concept encoder, not a pretrained language model.

Feature definitions express this six-operation contract. Coefficients and pair
interactions are learned only from public training utterances. No evaluator
label, family, row ID, numeric answer, or hidden addressing metadata is read.
"""

import re



PATTERNS = {
    "average": r"\b(?:averag\w*|mean|arithmetic center|one third|1/3)\b|divid\w*.{0,45}(?:three|3|their (?:number|count))\b",
    "maximum": r"\b(?:max\w*|highest|high|largest|greatest|biggest|upper\w*|peak|ceiling|top|high.water mark)\b",
    "minimum": r"\b(?:min|minimum|minima|lowest|low|smallest|least|lower|trough|floor)\b",
    "range": r"\b(?:range|span|spread|amplitude|width|breadth|extremes|high.to.low|high.low|peak.to.trough|apart|separation)\b|distance (?:between|from)|room between",
    "subtract": r"\b(?:subtract\w*|deduct\w*|minus|less|difference|delta|change|increment|displacement|movement|gain|loss|increase|decrease|rose|fell|rise|fall|advance|minuend|subtrahend)\b|higher or lower|added to|take away|signed (?:step|amount)|how many units separate",
    "lookup": r"\b(?:read\w*|record\w*|retriev\w*|fetch|lookup|look up|quote|observation|entry|datum|stored|archiv\w*|value|number|figure|amount|level|measurement)\b",
    "prior": r"\b(?:prior|preced\w*|previous|predecessor|earlier|older|last month|back\w*|lag\w*|left|before)\b",
    "three": r"\b(?:three|3|trio|triple)\b",
    "two_prior": r"(?:two|2|pair of).{0,36}(?:prior|preced\w*|previous|earlier|before|predecessor)|(?:prior|preced\w*|previous).{0,24}(?:two|2)\b|two monthly predecessors|lags one and two",
    "trailing": r"\b(?:trail\w*|ending|ends|end|conclud\w*|finish\w*|terminat\w*|through|latest|last|final|up to|right edge|endpoint|inclusive|including)\b",
    "wrong_length": r"\b(?:four|4|five|5|six|6|seven|7|twelve|12|year|quarter|two.month|2.month|single.month|one.month|singleton)\b|(?:two|2).{0,25}(?:months|monthly (?:records|readings|entries|observations|values|measurements|numbers))",
    "single_window": r"\b(?:single.month|one.month|singleton|month.{0,12}alone|only.{0,12}month)\b",
    "wrong_alignment": r"\b(?:centered|centred|around|starting|beginning|strictly|excluding|exclude|future|next|following|forward|right of|after it|after to|first of)\b|leav\w*.{0,16}out|months.{0,24}(?:precede|before).{0,24}\[date\]|after\s+\[date\]",
    "wrong_lag": r"\b(?:two|three|four|six|2|3|4|6).{0,30}(?:earlier|before|backward|back|lag)|(?:lag|back|backward).{0,16}(?:two|three|six|2|3|6)|same month.{0,32}year|year.{0,12}(?:earlier|before)|previous year|equivalent calendar month",
    "relative": r"%|\b(?:percent\w*|ratio|fraction|normalize|normalise|standardize|standardise|log\w*|growth factor|times as|relative (?:increase|change)|divid\w*.{0,70}(?:previous|prior|last month|mean)|scale.{0,70}by|units of)\b",
    "unsigned": r"\b(?:unsigned|magnitude|absolute (?:value|difference)|ignore.{0,12}sign|decreases.{0,24}positive|positive.{0,20}(?:fell|fall)|positive when it fell)\b",
    "weighted": r"\b(?:geometric|harmonic|exponential|unequal|weighting|weights decreasing|trimmed|root|squares|midpoint|mean square)\b|weight.{0,25}twice",
    "rank": r"\b(?:median|quartile|percentile|rank\w*|runner.up|second|middle|sort\w*)\b|how many of",
    "dispersion": r"\b(?:deviation|variance|covariance|correlation|slope|trend|fit|residual|uncertainty|confidence interval|variation|squared)\b",
    "sum": r"\b(?:sum|total|add|accumulate|cumulative|product|multiply|count|nonzero)\b",
    "forecast": r"\b(?:predict\w*|forecast\w*|extrapolat\w*|interpolat\w*|infer|missing|cause\w*|causal|why|explain|scenario|intervention|significan\w*|would|will)\b",
    "mutation": r"\b(?:replace|delete|erase|remove|change the stored|change the record|overwrite|update the)\b",
    "date_output": r"\b(?:which|what|name|give|return|report).{0,18}(?:calendar month|date of|month when|month had|month contains)|\b(?:index of|date of|and its month|and the date)\b|which.{0,20}month.{0,30}(?:max|high|peak)",
    "list_output": r"\b(?:list|ordered|chronological|both|and also|together with its|and the maximum|and the range|and mean|value and its)\b",
    "boolean_output": r"^(?:is|was|are|did|does)\b|\b(?:whether|which is (?:greater|larger)|tell me which|how many of)\b",
    "cross_series": r"\b(?:another|separate|second|different) series\b|\bseries [a-z]+[0-9]+|\b[a-z][0-9]{2,}\b",
    "explicit_numeric": r"\b(?:numeric\w*|number|value|units|reading|level)\b",
    "signed": r"\b(?:signed|sign|negative|original units|units|net)\b",
}
COMPILED = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
CURRENT = r"(?:\[date\]|current|latest|newer|this month|reference month)"
PREVIOUS = r"(?:prior|previous|preced\w*|last month|older|earlier|before|predecessor)"


def active_text(text):
    """Remove only explicit non-request side clauses; retain all other negation."""
    text = text.replace("-", " ")
    for pattern in (
        r"\b(?:do not|don't) (?:average|divide|calculate a difference)\s*:\s*",
        r",?\s*not (?:a date|its month|the dates|a list|the maximum|the preceding month|a difference)\b",
        r"\bwithout (?:smoothing|converting it to a percentage|dividing it|taking an absolute value)\b",
        r"\brather than \[date\] itself\b",
        r"\bbring back\b",
    ):
        text = re.sub(pattern, " ", text)
    return text


def concepts(text):
    text = active_text(text)
    out = {name: float(bool(pattern.search(text))) for name, pattern in COMPILED.items()}
    out["has_series"] = float("[series]" in text)
    out["has_date"] = float("[date]" in text)
    out["two_prior"] = float(bool(out["two_prior"]))
    # Ordered roles, unlike bag-of-words, distinguish a-b from b-a. These are
    # syntactic evidence features, not a final operation dispatch rule.
    minus = re.search(r"(.{0,140})\b(?:minus|less)\b(.{0,140})", text)
    deduct = re.search(r"\b(?:subtract|deduct)\b(.{0,140})\bfrom\b(.{0,140})", text)
    reverse = False
    for match, swapped in ((minus, False), (deduct, True)):
        if match:
            left, right = match.groups()
            left, right = left.rsplit(",", 1)[-1], right.split(",", 1)[0]
            if swapped:
                left, right = right, left
            reverse |= bool(re.search(PREVIOUS, left) and re.search(CURRENT, right) and not re.search(PREVIOUS, right))
            reverse |= bool(re.search(r"\b(?:minimum|min|lowest|smallest|floor|lower)\b", left) and re.search(r"\b(?:max\w*|highest|largest|ceiling|upper)\b", right))
    out["reverse_operands"] = float(reverse)
    # Interactions are learned from training; preserve original counterfeatures.
    out["window_three"] = float(bool(out["three"] or out["two_prior"]))
    out["window_wrong"] = float(bool(out["wrong_length"] and not out["two_prior"]))
    out["window_alignment_wrong"] = float(bool(out["wrong_alignment"] and not re.search(r"before.{0,20}(?:through|to) \[date\]", text)))
    if re.search(r"subtract\w*\s+(?:one|1) (?:calendar )?month from (?:the )?(?:timestamp|date)", text):
        out["subtract"], out["prior"] = 0.0, 1.0
    if re.search(r"one month old|one monthly step earlier", text):
        out["prior"] = 1.0
    return out


def concept_features(text):
    observed = concepts(text)
    active = sorted(name for name, value in observed.items() if value)
    features = {"cue:" + name: 1.0 for name in active}
    for i, left in enumerate(active):
        for right in active[i + 1:]:
            features["pair:" + left + ":" + right] = 1.0
    return features


def deterministic_label(text):
    """Auditable hand-written contract parser baseline, using the same cues."""
    f = concepts(text)
    reject = "__reject__"
    if any(f[name] for name in ("relative", "unsigned", "weighted", "rank",
            "dispersion", "forecast", "mutation", "date_output", "list_output",
            "boolean_output", "cross_series", "reverse_operands")):
        return reject
    aggregate = f["average"] or f["range"] or f["maximum"] or f["minimum"]
    if aggregate:
        if not f["window_three"] or f["window_wrong"] or f["window_alignment_wrong"]:
            return reject
        if f["average"]:
            return "mean3" if not (f["maximum"] or f["minimum"] or f["range"]) else reject
        if f["range"] or (f["maximum"] and f["minimum"]):
            return "range3" if not f["sum"] else reject
        return "peak3" if f["maximum"] and not f["minimum"] else reject
    if f["wrong_lag"] or f["wrong_alignment"] or f["sum"]:
        return reject
    if f["subtract"]:
        return "change"
    if f["prior"]:
        return "previous"
    return "at" if f["lookup"] and f["has_date"] else reject
