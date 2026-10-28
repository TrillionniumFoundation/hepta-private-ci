"""New author-created V5 training templates; no independent held data is read.

The grammar expansions below are training augmentation, not additional human
dialogue samples. Operator/operand contrasts are labeled during data creation;
the deployed router contains no corresponding dispatch rules.
"""

from .contracts import REJECT


def lines(text):
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


POSITIVE_SEEDS = {
    "at": lines("""
What is the recorded {series_name} for {date}?
Retrieve the observation labeled {date} in {series_name}.
Read the single monthly value of {series_name} at {date}.
Please supply {series_name}'s entry for {date}.
I want the historical {series_name} number corresponding to {date}.
Look in the archive for {series_name}, using {date} as the month.
For {series_name}, tell me the figure stored against {date}.
Return the datum in {series_name} whose month label is {date}.
Quote the original monthly measurement of {series_name} in {date}.
Show the actual {series_name} observation at the reference month {date}.
Which numerical reading belongs to {date} for {series_name}?
Report {series_name} as it was logged for {date}.
At the calendar position {date}, read {series_name}.
I need just that month's {series_name}: {date}.
Fetch {series_name} for {date} directly, without smoothing.
Return the value, not a date, of {series_name} in {date}.
Do not average anything: read {series_name} at {date}.
Use {date} itself for the {series_name} lookup, not the preceding month.
Find the stored amount for {series_name} in the specified month {date}.
For month {date}, state the monthly observation in {series_name}.
"""),
    "previous": lines("""
What is {series_name} for the calendar month before {date}?
Read the monthly entry immediately preceding {date} from {series_name}.
For {series_name}, take {date} as an anchor and move back one month.
Retrieve last month's {series_name} relative to {date}.
I want the value one monthly step earlier than {date} in {series_name}.
Quote the {series_name} observation just prior to {date}.
From the position {date}, select the previous monthly cell of {series_name}.
Look up {series_name} at a lag of one calendar month from {date}.
Give the predecessor month's {series_name}, anchored on {date}.
Read {series_name} after shifting {date} backward by one month.
Fetch the immediately earlier monthly observation of {series_name}, relative to {date}.
Use the calendar month directly to the left of {date} and read {series_name}.
Take the monthly timestamp just before {date} and return {series_name} there.
For {series_name}, report the previous month rather than {date} itself.
Do not calculate a difference: give the {series_name} reading one month before {date}.
Move back exactly one month from {date}; which {series_name} value is recorded there?
Give the prior month's recorded level of {series_name}, with {date} as the reference.
The anchor is {date}; the requested {series_name} observation is from the preceding month.
Return the one-month-lagged {series_name} value for the reference {date}.
Select the {series_name} number in the calendar month immediately before {date}.
"""),
    "change": lines("""
Compute {series_name} at {date} minus its value in the previous month.
Subtract last month's {series_name} from the {date} reading.
Give the signed month-on-month change in {series_name} ending at {date}.
How much did {series_name} increase or decrease from the preceding month to {date}?
Take the latest {series_name} at {date} less the immediately previous value.
Report the net monthly movement of {series_name} into {date}.
Calculate current minus prior for {series_name}, with current defined as {date}.
From {series_name} in {date}, deduct {series_name} in the month before it.
For {series_name}, give the gain or loss at {date} relative to one month earlier.
Find the signed increment from last month's {series_name} to the reading at {date}.
Return the difference in original units, {date} minus the month before, for {series_name}.
How many units higher or lower is {series_name} at {date} than one month before?
Give the absolute-unit monthly change of {series_name} at {date}, preserving the sign.
Use subtraction to compare {series_name} in {date} against its immediate predecessor.
Determine the latest minus earlier {series_name} value across the pair ending at {date}.
Compute the month-to-month delta for {series_name} at {date}, positive for an increase.
Do not divide: subtract the prior monthly {series_name} from the {date} observation.
The subtrahend is last month's {series_name}; the minuend is its {date} value.
The change should be negative if {series_name} fell between the preceding month and {date}.
Give {series_name}'s increase in units from one month before {date} to {date}.
"""),
    "mean3": lines("""
Average {series_name} over {date} and its two immediately preceding months.
Give the arithmetic mean of the three monthly {series_name} entries ending at {date}.
Add the latest three {series_name} readings through {date}, then divide by three.
Compute a trailing three-month arithmetic average for {series_name} at {date}.
Return the equal-weight mean across the three-month period concluding in {date} for {series_name}.
Find the ordinary average of {series_name} in the reference month {date} and the two prior months.
Smooth {series_name} at {date} with the arithmetic average of those latest three months.
Give the sum of {series_name} over the final three months through {date}, divided by their count.
What is the mean level in the three consecutive monthly {series_name} cells ending at {date}?
For {series_name}, combine the last three readings up to {date} using an arithmetic mean.
Sum {series_name} at {date}, one month earlier and two months earlier, and divide the total by 3.
Report the equally weighted moving average of {series_name}, window length three, ending at {date}.
The window includes {date} and the two prior months; average their {series_name} values.
Use a three-month trailing window for {series_name} at {date} and take its arithmetic mean.
I want the average, not the maximum, of {series_name} in the three months ending at {date}.
Return a number for the three-month mean of {series_name} through {date}.
Compute the arithmetic center of the three {series_name} observations ending in {date}.
Take one third of the total of the latest three monthly {series_name} values through {date}.
Find the simple moving mean of {series_name} at {date} with three equal monthly weights.
Use {date} as the final month and average three consecutive {series_name} observations.
"""),
    "range3": lines("""
Compute the maximum minus minimum of {series_name} in the three months ending at {date}.
Give the range of {series_name} over {date} and the preceding two months.
Subtract the lowest from the highest {series_name} reading across the last three months through {date}.
Find the span between the two extremes of {series_name} in the trailing three-month window at {date}.
What is the highest-to-lowest gap of {series_name} in the three consecutive months ending at {date}?
Take the largest {series_name} less the smallest in the three-month interval finishing at {date}.
Report the full spread of {series_name} across {date} and its two immediately prior months.
Give the width of the smallest interval covering the latest three {series_name} observations through {date}.
For {series_name}, return the difference between the maximum and minimum over the last three months ending at {date}.
Calculate the peak-to-trough distance of {series_name} across the three months through {date}.
Subtract the floor from the ceiling of the three monthly {series_name} readings ending at {date}.
Measure how far apart the smallest and largest {series_name} are in the trailing three months at {date}.
Find the value range, not the dates, of {series_name} over the final three months through {date}.
Take the upper extreme minus the lower extreme of {series_name} across the three months ending at {date}.
Give a nonnegative high-low difference for {series_name} in the window comprising {date} and the two earlier months.
What is the amplitude from minimum to maximum in the three monthly {series_name} entries ending at {date}?
Use a three-month trailing window ending at {date} and return the numerical range of {series_name}.
For {series_name}, how broad is the interval occupied by the three months up to and including {date}?
The latest three monthly readings through {date} are the window: largest minus smallest {series_name}, please.
Find the separation of the upper and lower {series_name} extremes over the three months ending at {date}.
"""),
    "peak3": lines("""
Find the maximum value of {series_name} in the three months ending at {date}.
Give the largest {series_name} reading among {date} and the two preceding months.
Return the three-month peak level of {series_name} through {date}.
Choose the highest of the latest three monthly {series_name} observations ending at {date}.
What is the upper extreme of {series_name} across the trailing three months at {date}?
Report the greatest recorded {series_name} value in the three-month interval concluding at {date}.
Select the top numerical {series_name} reading across {date} and its two prior months.
Give the ceiling attained by {series_name} during the final three months through {date}.
Find the high-water mark of {series_name} across the three consecutive months ending at {date}.
Among the three {series_name} monthly entries through {date}, which value is largest?
Return the maximum number, not its month, from {series_name} over the last three months ending at {date}.
Read the highest recorded level of {series_name} in the window containing {date} and the previous two months.
Take the uppermost {series_name} observation within the trailing three-month period ending at {date}.
Supply the greatest number in the last three monthly {series_name} cells up to {date}.
What peak reading did {series_name} attain across {date} and the two months immediately before it?
Use {date} as the last month and take the maximum of three {series_name} readings.
Select the largest observation of {series_name} from the three months through {date}.
Give just the peak value, not a list, for {series_name} across the three months ending at {date}.
Do not average: return the maximum of the latest three {series_name} values through {date}.
Report the numerical high of {series_name} for the trailing three months ending at {date}.
"""),
}

WINDOWS = [
    "over the three consecutive months ending at {date}",
    "across {date} and the two immediately preceding months",
    "within the trailing three-month period through {date}",
    "for the last 3 monthly entries up to and including {date}",
    "during the three months finishing in {date}",
    "among the reference month {date}, the prior month and the month before that",
    "in a window of three months whose final month is {date}",
    "across the monthly trio ending in {date}",
]
OPERATORS = {
    "mean3": [
        "arithmetic mean",
        "ordinary average",
        "simple mean",
        "equally weighted average",
        "sum divided by three",
        "average level",
    ],
    "range3": [
        "maximum minus minimum",
        "high-low range",
        "largest less smallest",
        "distance between the highest and lowest",
        "numerical range",
        "width from the lower extreme to the upper extreme",
    ],
    "peak3": [
        "maximum value",
        "highest reading",
        "largest observation",
        "upper extreme",
        "peak numerical level",
        "greatest recorded number",
    ],
}
COMMANDS = ["Compute the", "Please give the", "I need the", "Return the"]
WRONG_WINDOWS = [
    "over the two consecutive months ending at {date}",
    "over the four consecutive months ending at {date}",
    "over the six consecutive months ending at {date}",
    "over the twelve consecutive months ending at {date}",
    "within the month {date} alone",
    "across {date} and the previous three months",
    "over a three-month window starting at {date}",
    "in the three months immediately before {date}, excluding {date}",
    "over the centered three-month window around {date}",
    "across {date} and the two following months",
]
WRONG_OPERATORS = [
    "median",
    "geometric mean",
    "harmonic mean",
    "root mean square",
    "standard deviation",
    "variance",
    "sum",
    "second-largest value",
    "minimum",
    "lowest value",
    "slope of a fitted line",
    "weighted mean with unequal weights",
    "date of the maximum",
    "index of the highest observation",
    "ratio of maximum to minimum",
    "maximum minus the mean",
    "mean minus the minimum",
    "lowest minus highest",
]


def training_templates():
    rows = []

    def add(text, intent, family):
        rows.append({"template": text, "intent": intent, "family": family})

    for intent, templates in POSITIVE_SEEDS.items():
        for text in templates:
            add(text, intent, "manual-positive")
    for intent, operators in OPERATORS.items():
        for operator in operators:
            for window in WINDOWS:
                for command in COMMANDS:
                    add(
                        f"{command} {operator} of {{series_name}} {window}.",
                        intent,
                        "generated-positive-operator-window",
                    )
            for window in WRONG_WINDOWS:
                for command in COMMANDS[:2]:
                    add(
                        f"{command} {operator} of {{series_name}} {window}.",
                        REJECT,
                        "different-window-or-alignment",
                    )
    for operator in WRONG_OPERATORS:
        for window in WINDOWS:
            for command in COMMANDS[:2]:
                add(
                    f"{command} {operator} of {{series_name}} {window}.",
                    REJECT,
                    "unsupported-statistic-or-output",
                )
    current = [
        "its value at {date}",
        "the current month's reading at {date}",
        "the {date} observation",
        "the latest value at {date}",
    ]
    prior = [
        "its value one month before {date}",
        "the preceding month's reading",
        "the previous monthly observation",
        "last month's value relative to {date}",
    ]
    for new in current:
        for old in prior:
            for text, label in (
                (f"For {{series_name}}, subtract {old} from {new}.", "change"),
                (f"For {{series_name}}, subtract {new} from {old}.", REJECT),
                (f"For {{series_name}}, calculate {new} minus {old}.", "change"),
                (f"For {{series_name}}, calculate {old} minus {new}.", REJECT),
                (f"For {{series_name}}, deduct {old} from {new}.", "change"),
                (f"For {{series_name}}, deduct {new} from {old}.", REJECT),
                (f"For {{series_name}}, divide {new} by {old}.", REJECT),
            ):
                add(text, label, "generated-ordered-operand-contrast")
    for verb in (
        "Read",
        "Retrieve",
        "Report",
        "Fetch",
        "Look up",
        "Return",
        "Quote",
        "Show",
    ):
        for suffix in (
            "at {date}",
            "for the specified month {date}",
            "in the reference month {date}",
            "corresponding to {date}",
            "for month {date} itself",
            "with timestamp {date}",
        ):
            add(
                f"{verb} the recorded {{series_name}} value {suffix}.",
                "at",
                "generated-read-address",
            )
        for suffix in (
            "one month before {date}",
            "in the calendar month immediately before {date}",
            "for the previous month relative to {date}",
            "one monthly interval earlier than {date}",
            "in the predecessor month of {date}",
            "at a one-month backward offset from {date}",
        ):
            add(
                f"{verb} the recorded {{series_name}} value {suffix}.",
                "previous",
                "generated-read-address",
            )
        for suffix in (
            "one month after {date}",
            "two months before {date}",
            "in the same month one year before {date}",
            "three months earlier than {date}",
            "in the next month after {date}",
            "in the year containing {date}",
            "at the end of the quarter containing {date}",
        ):
            add(
                f"{verb} the recorded {{series_name}} value {suffix}.",
                REJECT,
                "wrong-address",
            )
    for text in OTHER_REJECTS:
        add(text, REJECT, "manual-near-ood")
    return rows


OTHER_REJECTS = lines("""
What percentage change occurred in {series_name} from last month to {date}?
Compute the relative increase in {series_name} at {date} as a percentage of its previous value.
Give the ratio of {series_name} at {date} to its value one month earlier.
Return the log return of {series_name} for the month {date}.
Give the absolute value of the month-to-month difference in {series_name} ending at {date}.
Ignore the sign and state how far {series_name} moved from the prior month into {date}.
Normalize {series_name} at {date} by its trailing three-month mean.
Standardize the {date} {series_name} reading using its three-month standard deviation.
Express the three-month range of {series_name} through {date} as a percentage of the mean.
Calculate the growth factor of {series_name} from the previous month to {date}.
Predict the value of {series_name} in the next month after {date}.
Estimate a missing {series_name} entry at {date} by interpolation.
What will {series_name} be at {date}, according to a forecast model?
Explain why {series_name} increased at {date}.
Name the cause of the {series_name} maximum in the three months ending at {date}.
Test whether the change in {series_name} at {date} is statistically significant.
Give a confidence interval for the three-month average of {series_name} through {date}.
Replace the stored {series_name} value at {date} with zero.
Delete {series_name} in {date} from the archive.
List all three {series_name} values from the three months ending at {date}.
Tell me which month had the maximum {series_name} in the three months ending at {date}.
Return the date, not the number, of the three-month {series_name} peak through {date}.
Give the peak value and its month for {series_name} over the three months ending at {date}.
Average {series_name} and another series R91 at {date}.
Subtract the value of series R91 from {series_name} at {date}.
Compare the latest three-month means of {series_name} and series R91 ending at {date}.
Read {series_name} at {date} and also provide the preceding month's value.
Give both the range and mean of {series_name} over the three months ending at {date}.
Count how many months {series_name} exceeded zero in the three months through {date}.
Is {series_name} higher in {date} than it was in the preceding month?
Rank the three monthly {series_name} readings ending at {date}.
Compute the product of {series_name} over the three months ending at {date}.
Subtract the highest from the lowest {series_name} in the three months ending at {date}.
For {series_name}, find the average of the maximum and minimum over the three months ending at {date}.
Give the midpoint of the minimum and maximum {series_name} values in the three months ending at {date}.
Find the largest monthly increase of {series_name} within the three months ending at {date}.
Compute {series_name} at {date} minus its three-month mean ending at {date}.
Subtract the {date} value of {series_name} from its previous month's value.
Report last month minus this month for {series_name}, taking this month as {date}.
Give the decrease in {series_name} from the previous month to {date}, positive when it fell.
Return the mean of {series_name} over just the single month {date}.
Find the maximum of {series_name} for the singleton window containing only {date}.
""")
