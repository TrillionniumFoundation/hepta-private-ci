"""Predeclared disjoint language folds for numeric write/address/compose tasks.

Every supported predicate is asked about the same entity and date anchors. The
training objective cannot succeed by identifying an entity or a calendar token.
The held fold is only materialized by the final evaluation path.
"""

from .numeric_graph import INTENTS, SERIES_NAMES, shift_month
from .semantic_router import REJECT, canonical, digest


DESCRIPTIONS = {
    "at": "Read the recorded value of the requested series for the specified month.",
    "previous": "Read the recorded value for the month immediately before the specified month.",
    "change": "Subtract the preceding month's value from the specified month's value.",
    "mean3": "Compute the arithmetic mean of the three consecutive months ending at the specified month.",
    "range3": "Compute the maximum minus minimum over the three months ending at the specified month.",
    "peak3": "Find the highest value in the three months ending at the specified month.",
    REJECT: "Unsupported request: predict the future, explain a cause, compute a median, standard deviation, or ratio.",
}

TRAINING_ALIASES = (
    "the requested monthly series",
    "the recorded quantity",
    "this time series",
    "the archive's numeric variable",
    "series Q17",
    "the monthly observation series",
)

LANGUAGE = {
    "train": {
        "at": [
            "What was {series} in {date}?",
            "Read the {series} value for {date}.",
            "Give the recorded {series} measurement at {date}.",
            "Look up {series} for the month {date}.",
            "Show the observation of {series} in {date}.",
            "Return that month's {series} reading: {date}.",
        ],
        "previous": [
            "What was {series} in the month before {date}?",
            "Read {series} for the preceding month relative to {date}.",
            "Give the previous month's {series} value, using {date} as the reference.",
            "Look up {series} one month earlier than {date}.",
            "Show the observation immediately preceding {date} for {series}.",
            "Return the {series} reading from the month just before {date}.",
        ],
        "change": [
            "How much did {series} change from the previous month to {date}?",
            "Subtract the previous month's {series} from its value at {date}.",
            "Give the monthly change in {series} at {date}.",
            "Calculate this month minus last month for {series}, with this month equal to {date}.",
            "What is the increase or decrease in {series} at {date} compared with the preceding month?",
            "Return the signed month-to-month difference of {series} ending at {date}.",
        ],
        "mean3": [
            "What is the three-month average of {series} ending at {date}?",
            "Average {series} over {date} and the two preceding months.",
            "Compute the mean of the last three monthly {series} observations through {date}.",
            "Give the arithmetic mean of {series} across the three months ending at {date}.",
            "Return a trailing three-month average for {series} at {date}.",
            "Take the sum of {series} over the three months ending at {date} and divide it by three.",
        ],
        "range3": [
            "What is the three-month range of {series} ending at {date}?",
            "Subtract the smallest from the largest {series} over {date} and the preceding two months.",
            "Compute maximum minus minimum of {series} in the three months through {date}.",
            "Give the spread between highest and lowest {series} over the three months ending at {date}.",
            "Return the high-to-low difference of {series} over the last three months through {date}.",
            "How wide is the range of {series} over the three-month period ending at {date}?",
        ],
        "peak3": [
            "What is the highest {series} in the three months ending at {date}?",
            "Find the maximum {series} over {date} and the two preceding months.",
            "Give the three-month peak of {series} through {date}.",
            "Return the largest of the last three monthly {series} values at {date}.",
            "Which is the greatest {series} reading in the three-month window ending at {date}?",
            "Show the top {series} value across the three months ending at {date}.",
        ],
        REJECT: [
            "Predict {series} for the month after {date}.",
            "Why did {series} change at {date}?",
            "Find the median {series} over three months ending at {date}.",
            "Compute the standard deviation of {series} in the three months ending at {date}.",
            "Divide {series} at {date} by the previous month's value.",
            "Give the total {series} for the entire year containing {date}.",
            "What instrument measured {series} at {date}?",
            "Delete the {series} observation at {date}.",
        ],
    },
    "selection": {
        "at": [
            "Tell me the measured {series} at {date}.",
            "Retrieve the monthly datum for {series} at {date}.",
            "I need the single {series} observation for {date}.",
            "Report {series} as recorded for {date}.",
        ],
        "previous": [
            "Retrieve the {series} observation one calendar month before {date}.",
            "I need last month's {series}, taking {date} as now.",
            "For {series}, report the monthly datum immediately before {date}.",
            "Tell me the preceding month's measurement of {series}, relative to {date}.",
        ],
        "change": [
            "Report the signed difference between {series} at {date} and one month earlier.",
            "How far did {series} rise or fall during the month ending at {date}?",
            "For {series}, compare {date} against the preceding month by subtraction.",
            "I need the current minus preceding {series} value for {date}.",
        ],
        "mean3": [
            "For {series}, calculate a rolling average of three months through {date}.",
            "I need the mean {series} reading across {date} and its two predecessor months.",
            "Report the average of the three consecutive {series} entries ending at {date}.",
            "Find the arithmetic average for {series} in the trailing three months at {date}.",
        ],
        "range3": [
            "For {series}, calculate the amplitude from minimum to maximum in the three months ending at {date}.",
            "Report the largest minus smallest {series} over the trailing three months at {date}.",
            "I need the high-low spread for {series} in the three consecutive months through {date}.",
            "Find the gap between the extremes of {series} during the three months ending at {date}.",
        ],
        "peak3": [
            "Report the uppermost {series} reading from the three months through {date}.",
            "I need the maximum of three consecutive {series} entries ending at {date}.",
            "For {series}, find the largest observation in {date} and the two months before it.",
            "What was the peak reading of {series} over the trailing three months at {date}?",
        ],
        REJECT: [
            "Forecast next month's {series} after {date}.",
            "Explain the reason for {series} at {date}.",
            "Report the middle-ranked {series} value over three months ending at {date}.",
            "Estimate the variance of {series} in the three months through {date}.",
            "Give the percentage change of {series} at {date}.",
            "Rewrite the stored {series} measurement at {date}.",
        ],
    },
    "development": {
        "at": [
            "Fetch the archived {series} entry dated {date}.",
            "What number is stored for {series} at {date}?",
            "State the monthly {series} measurement corresponding to {date}.",
            "For {date}, supply the observed {series} figure.",
        ],
        "previous": [
            "Fetch the archived {series} entry immediately prior to {date}.",
            "What number is stored for {series} one month ahead of {date} in the backward direction?",
            "State the monthly {series} measurement for the calendar month preceding {date}.",
            "Starting at {date}, step back one month and supply the observed {series} figure.",
        ],
        "change": [
            "Measure the month-on-month movement of {series} at {date}, keeping its sign.",
            "At {date}, how much larger or smaller is {series} than in the month before?",
            "Give the net monthly increment in {series} for {date}.",
            "Take {series} in {date} less its reading one month before.",
        ],
        "mean3": [
            "Smooth {series} at {date} with a trailing arithmetic average of three monthly entries.",
            "Find the mean level of {series} across the three months culminating in {date}.",
            "Add the latest three {series} readings through {date}, then divide by their count.",
            "Give the equal-weight three-month moving average for {series} at {date}.",
        ],
        "range3": [
            "Measure the full high-to-low excursion of {series} in the three months through {date}.",
            "Give the width of the smallest interval containing all three {series} readings ending at {date}.",
            "Find the extreme-to-extreme difference for {series} over the three months culminating in {date}.",
            "How far apart are the maximum and minimum {series} readings across the last three months through {date}?",
        ],
        "peak3": [
            "Select the most elevated {series} observation from the three months ending at {date}.",
            "What is the largest recorded figure for {series} in the three-month interval through {date}?",
            "Find the upper extreme of {series} over {date} and its two previous months.",
            "Give the high-water mark of {series} across the three months culminating in {date}.",
        ],
        REJECT: [
            "Extrapolate {series} beyond {date}.",
            "Identify what caused the {series} reading at {date}.",
            "Give the three-month geometric mean of {series} ending at {date}.",
            "Compute a three-month moving standard deviation for {series} at {date}.",
            "Is the {series} change at {date} statistically significant?",
            "Alter {series} for {date} to a new value.",
        ],
    },
    "held": {
        "at": [
            "Quote the logged {series} figure associated with {date}.",
            "Access the historical {series} datum bearing the timestamp {date}.",
            "For the month labeled {date}, what {series} amount was registered?",
            "Consult the archive and state {series} at {date}.",
            "Return the actual monthly entry, {series}, {date}.",
            "Which numerical observation belongs to {series} for {date}?",
        ],
        "previous": [
            "Quote the logged {series} figure directly prior to the month {date}.",
            "Move the calendar back one month from {date} and access {series} there.",
            "For the month immediately antecedent to {date}, what {series} amount was registered?",
            "Consult the archive and state {series} one monthly interval before {date}.",
            "Return the predecessor month's actual entry for {series}, referenced to {date}.",
            "Which numerical {series} observation belongs to the month that came just before {date}?",
        ],
        "change": [
            "Compute the net advance of {series} from the preceding month into {date}.",
            "What signed step separates the prior month's {series} reading from the one at {date}?",
            "At {date}, quantify the month-over-month gain or loss in {series}.",
            "From {series} at {date}, deduct the value registered in the immediately preceding month.",
            "Report the monthly displacement of {series} at {date}, positive for a rise and negative for a fall.",
            "How many units did {series} move between the previous observation and {date}?",
        ],
        "mean3": [
            "Find the equally weighted mean of the trio of monthly {series} figures up to and including {date}.",
            "What is the arithmetic center of the last three recorded {series} values through {date}?",
            "Aggregate {series} over the three consecutive months finishing at {date} by averaging them.",
            "Give a three-observation trailing moving mean for {series} at {date}.",
            "What value results from averaging {series} in {date} together with its two immediate predecessors?",
            "Divide the combined {series} readings from the three-month interval ending at {date} into three equal parts.",
        ],
        "range3": [
            "What is the separation of the upper and lower extremes of {series} in the three months finishing at {date}?",
            "Across the latest three {series} entries through {date}, deduct the floor from the ceiling.",
            "Quantify the span of {series} values within the three-month interval ending at {date}.",
            "Give the peak-to-trough distance for {series} over {date} and its two immediate predecessors.",
            "How broad is the value interval covered by the trio of monthly {series} readings ending at {date}?",
            "Take the highest {series} minus the lowest across the last three observations through {date}.",
        ],
        "peak3": [
            "What is the ceiling attained by {series} during the three months finishing at {date}?",
            "Select the upper extreme among the latest three {series} entries through {date}.",
            "Report the greatest {series} amount registered within the three-month interval ending at {date}.",
            "Give the crest of {series} over {date} and its two immediate predecessors.",
            "Which numerical value tops the trio of monthly {series} readings ending at {date}?",
            "Take the highest {series} across the last three observations through {date}.",
        ],
        REJECT: [
            "Project the trajectory of {series} after {date}.",
            "What mechanism explains {series} in {date}?",
            "Compute the midpoint by rank, rather than the mean, of three {series} entries ending at {date}.",
            "Give the root-mean-square deviation of {series} over three months through {date}.",
            "What multiplicative factor links the previous {series} value to {date}?",
            "Prove that the change in {series} at {date} has a causal origin.",
            "Replace the logged {series} figure for {date} with an estimate.",
            "Give the annual sum of {series} for the year surrounding {date}.",
        ],
    },
}


def language_digest():
    return digest(
        canonical(
            {
                "descriptions": DESCRIPTIONS,
                "training_aliases": TRAINING_ALIASES,
                "folds": LANGUAGE,
            }
        )
    )


def partition_anchors(source, seed):
    years = set(source["years"])
    result = {fold: [] for fold in LANGUAGE}
    for month in range(1, 13):
        candidates = [
            (year, month)
            for year in sorted(years)
            if all(
                shift_month((year, month), offset)[0] in years for offset in (-2, -1)
            )
        ]
        candidates.sort(
            key=lambda address: digest(canonical([seed, source["domain"], address]))
        )
        if len(candidates) < len(result):
            raise ValueError("insufficient written years for independent address folds")
        for index, fold in enumerate(result):
            result[fold].append(candidates[index])
    return result


def language_rows(source, seed, partition, *, repetitions=2):
    if partition not in LANGUAGE or not 1 <= repetitions <= 12:
        raise ValueError("invalid language partition")
    anchors = partition_anchors(source, seed)[partition]
    rows = []
    for intent, templates in LANGUAGE[partition].items():
        for template_index, template in enumerate(templates):
            for repeat in range(repetitions):
                address = anchors[
                    (template_index * repetitions + repeat) % len(anchors)
                ]
                date = f"{address[0]:04d}-{address[1]:02d}"
                utterance = template.format(
                    series=SERIES_NAMES[source["domain"]], date=date
                )
                rows.append(
                    {
                        "id": digest(
                            canonical(
                                [
                                    source["domain"],
                                    seed,
                                    partition,
                                    intent,
                                    template_index,
                                    repeat,
                                ]
                            )
                        )[:24],
                        "partition": partition,
                        "intent": intent,
                        "scope": "numeric-study",
                        "domain": source["domain"],
                        "address": list(address),
                        "date": date,
                        "utterance": utterance,
                        "template_index": template_index,
                    }
                )
    return rows


def graph_training_rows(source, seed):
    rows = []
    for intent in INTENTS:
        for address in partition_anchors(source, seed)["train"]:
            date = f"{address[0]:04d}-{address[1]:02d}"
            rows.append(
                {
                    "id": digest(
                        canonical(["graph", source["domain"], seed, intent, address])
                    )[:24],
                    "partition": "train",
                    "intent": intent,
                    "scope": "numeric-study",
                    "domain": source["domain"],
                    "address": list(address),
                    "date": date,
                    "utterance": LANGUAGE["train"][intent][0].format(
                        series=SERIES_NAMES[source["domain"]], date=date
                    ),
                }
            )
    return rows


def router_training_rows(source, seed, *, alias_count=6):
    """Counterfactual names for the same training source, not new domain facts."""
    if type(alias_count) is not int or not 0 <= alias_count <= len(TRAINING_ALIASES):
        raise ValueError("invalid bounded training alias count")
    base = language_rows(source, seed, "train")
    rows = list(base)
    for alias in TRAINING_ALIASES[:alias_count]:
        for row in base:
            augmented = dict(row)
            augmented["id"] = digest(canonical([row["id"], alias]))[:24]
            augmented["utterance"] = row["utterance"].replace(
                SERIES_NAMES[source["domain"]], alias
            )
            augmented["training_source_alias"] = alias
            rows.append(augmented)
    return rows
