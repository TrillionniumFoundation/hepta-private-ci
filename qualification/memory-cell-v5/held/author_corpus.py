"""Independent synthetic English holdout authoring; do not import in model code."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
from string import Formatter


ROOT = Path(__file__).resolve().parent
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
OFFSETS = {"at": [0], "previous": [-1], "change": [-1, 0], "mean3": [-2, -1, 0], "range3": [-2, -1, 0], "peak3": [-2, -1, 0]}
OPERATORS = {"at": "read", "previous": "read", "change": "current_minus_previous", "mean3": "arithmetic_mean", "range3": "maximum_minus_minimum", "peak3": "maximum_value"}

# Each entry below was authored as a separate expression. No date/entity
# substitution creates additional independent language samples.
KNOWN = {
    "at": [
        "The row marked {date} is the one I need: what number does it hold for {series_name}?",
        "Looking up {series_name}, please report the observation attached to the calendar label {date}.",
        "For {date}, copy the stored measurement of {series_name} into the answer.",
        "I have the month, {date}, and the variable, {series_name}; I am missing the recorded number.",
        "Which reading of {series_name} belongs to {date} itself?",
        "Use {date} as the record key and retrieve its {series_name} field.",
        "Please fill in this blank from the archive: {series_name}, month {date}, value ___.",
        "The requested cell is at {series_name} and {date}. Tell me its contents.",
        "I want the single {series_name} entry dated {date}, exactly as a monthly observation.",
        "Read across the {date} row to the {series_name} column and give the numeric entry.",
        "What did the archive actually record for {series_name} in {date}?",
        "My reference month is {date}. For {series_name}, return that month's reading rather than an earlier one.",
        "Locate {date} in the {series_name} record and quote the value found there.",
        "Could you supply the observed {series_name} amount whose date stamp is {date}?",
        "I am checking one entry only: the value of {series_name} assigned to {date}.",
        "From the monthly table, fetch the {series_name} number indexed by {date}.",
        "Use the observation at {date} directly for {series_name}; no comparison between months is requested.",
        "What number would I see in the {series_name} record if I opened the entry for {date}?",
        "Report the actual {date} observation in the series called {series_name}.",
        "Please identify the measurement stored at the intersection of {series_name} and month {date}.",
        "The date to read is {date}, and the series to read is {series_name}. What is the value?",
        "For {series_name}, I need the archived level at {date}, not a change from another month.",
        "Retrieve the numeric observation associated with the pair ({series_name}, {date}).",
        "The report should contain just the {date} reading from {series_name}. What is it?",
    ],
    "previous": [
        "Treat {date} as the reference for {series_name} and read the entry one calendar month earlier.",
        "Move back exactly one month from {date}; what {series_name} reading is stored at that date?",
        "I need the {series_name} observation immediately preceding {date} on the monthly calendar.",
        "For {series_name}, which number belongs to the month just before {date}, rather than {date} itself?",
        "Start at the month labelled {date} and take a single backward calendar step to retrieve {series_name}.",
        "What was the stored {series_name} level in the calendar month directly prior to {date}?",
        "Use the month before {date} as the lookup key for {series_name}.",
        "Please return the one-month-lagged observation of {series_name}, with {date} as the anchor.",
        "The current reference is {date}; I want {series_name} from its immediately preceding month.",
        "Read {series_name} at a lag of one calendar month relative to {date}.",
        "Which archived measurement of {series_name} sits one month to the left of {date} on the calendar?",
        "For an anchor of {date}, fetch the {series_name} record from the preceding calendar month only.",
        "Go to the month that ends immediately before {date} begins, and give its {series_name} value.",
        "I already have a reference date of {date}; retrieve {series_name} for the month just behind it.",
        "Shift the date {date} backward by one month and report the observation of {series_name} there.",
        "The {series_name} number I am after is from one calendar month before the specified month, {date}.",
        "Without calculating a change, give me {series_name} for the month immediately before {date}.",
        "Trace the calendar backward from {date} by one month, and look up the {series_name} value at the month you reach.",
        "At reference month {date}, what is the lag-one monthly reading of {series_name}?",
        "Please fetch the earlier of the two {series_name} observations for {date} and the calendar month directly before it.",
        "Use {date} only as an anchor: the requested {series_name} entry is the one from a month earlier.",
        "For {series_name}, step from {date} to its predecessor month and return that month's measurement.",
        "The requested observation is one month old as of {date}; what is that {series_name} reading?",
        "Look up {series_name} in the month immediately before the one labelled {date}.",
    ],
    "change": [
        "For {series_name}, take the reading at {date} and deduct the reading one month earlier; keep the sign.",
        "How much is the {date} observation of {series_name} above or below the immediately preceding month's observation, in the original units?",
        "Calculate newer minus older for {series_name}, using {date} and the month directly before it.",
        "What is the signed step in {series_name} from the preceding calendar month into {date}?",
        "I need the difference {series_name} at {date} less {series_name} at the immediately prior month.",
        "Use the {date} value of {series_name} as the minuend and last month's value as the subtrahend.",
        "Subtract the observation one calendar month before {date} from the {date} observation of {series_name}.",
        "In measurement units, what is the net gain or loss in {series_name} on moving from the preceding month to {date}?",
        "For the two consecutive months ending in {date}, report the later {series_name} reading minus the earlier reading.",
        "Please compute the month-to-month increment of {series_name} at {date}, allowing a negative answer when it fell.",
        "Compare {series_name} at {date} with the month immediately before it by doing current value minus prior value.",
        "What signed amount must be added to the preceding month's {series_name} value to obtain its value at {date}?",
        "I want the raw difference in {series_name} for {date} versus its predecessor month, with the newer month first in the subtraction.",
        "Report the signed change in {series_name} between the month before {date} and {date}; leave it in the series' own units.",
        "Take the latest of the two monthly {series_name} readings ending at {date}, then subtract the other one.",
        "For {series_name}, evaluate value({date}) minus value(the calendar month before {date}).",
        "If I start with last month's {series_name} reading, what signed adjustment gets me to the {date} reading?",
        "Measure the one-month movement into {date} for {series_name} as the ending level minus the starting level.",
        "What is the increase in {series_name} from the month directly before {date} to {date}, treating a decrease as a negative increase?",
        "For {series_name}, compute the first monthly difference at {date}: this month's reading less the preceding month's.",
        "Give the arithmetic difference between the {date} and immediately prior readings of {series_name}, in that order.",
        "At {date}, how far has {series_name} moved up or down from one month earlier? Return the signed difference, not a percentage.",
        "Please subtract the earlier from the later {series_name} measurement in the adjacent-month pair that ends at {date}.",
        "The requested result is {series_name}'s {date} reading after removing the preceding month's reading by subtraction.",
    ],
    "mean3": [
        "For {series_name}, average the readings for {date} and the two calendar months immediately before it, with equal weight on each.",
        "What is the arithmetic mean of the three consecutive {series_name} observations whose last month is {date}?",
        "Take the {series_name} values at {date}, one month earlier, and two months earlier; add them and divide by three.",
        "Please give the equally weighted three-month average of {series_name}, including {date} as the newest month.",
        "Use the three-month block that finishes at {date} and calculate its ordinary arithmetic average for {series_name}.",
        "I need one mean value for {series_name} across {date} plus the two preceding calendar months.",
        "For the window consisting of {date} and its two immediate predecessor months, what is the arithmetic average of {series_name}?",
        "Combine the three monthly readings of {series_name} ending with {date} by giving each a weight of one third.",
        "How large is the simple average of {series_name} over the anchor month {date} and the two months just behind it?",
        "Please calculate the sum of {series_name}'s current and previous two monthly observations at {date}, then divide that sum by three.",
        "The averaging window has three months and ends at {date}. What arithmetic mean does {series_name} have in it?",
        "Use all three consecutive months up to and including {date} to produce the equal-weight mean of {series_name}.",
        "For {series_name}, what single arithmetic average represents the readings two months before {date}, one month before it, and at {date}?",
        "Average exactly three {series_name} entries: the one labelled {date} and the two immediately older monthly entries.",
        "I want the unweighted average of the three-month {series_name} segment ending in {date}.",
        "Read {series_name} for {date} and the prior two months; what is their total divided equally among the three observations?",
        "At reference {date}, compute the trailing three-observation arithmetic mean for monthly {series_name}, including the reference month's observation.",
        "For the latest three calendar months ending at {date}, find {series_name}'s mean by adding the three values and dividing by three.",
        "Which arithmetic mean results from pooling {series_name} at {date} with its two preceding monthly readings?",
        "Set equal weights on {date} and the two months before it. What average does this give for {series_name}?",
        "Return the conventional arithmetic average for the three {series_name} months ending on {date}, rather than choosing one of their individual values.",
        "Please smooth {series_name} at {date} using only an equal-weight average of that month and the two preceding months.",
        "Take the three-month run of {series_name} that stops at {date}. What is the sum of its readings divided by the number of readings?",
        "I need the mean level of {series_name} in the inclusive three-month interval whose final month is {date}; use the arithmetic mean.",
    ],
    "range3": [
        "Across {date} and the two prior calendar months, how far apart are the largest and smallest {series_name} readings?",
        "For the three monthly {series_name} values ending at {date}, subtract the minimum value from the maximum value.",
        "What numerical width separates the low and high {series_name} observations in the three-month block finishing at {date}?",
        "Use {date} together with its two immediately preceding months and return the high-minus-low spread of {series_name}.",
        "I need the range width, maximum less minimum, for {series_name} over the three consecutive months ending in {date}.",
        "Find the greatest and least {series_name} readings among {date} and its two predecessor months, then report their difference.",
        "How many measurement units lie between the minimum and maximum of {series_name} in the trailing three-month window including {date}?",
        "Please give a single number for the high-to-low span of {series_name} over {date} and the two months before it.",
        "For the inclusive three-month period that ends at {date}, what is max({series_name}) minus min({series_name})?",
        "Take exactly three monthly {series_name} observations ending with {date}. How large is their largest value less their smallest value?",
        "What is the difference between the two extreme {series_name} values in the window containing {date} and the prior two months?",
        "Calculate {series_name}'s peak-to-trough amplitude over the three months ending at {date}, meaning highest reading minus lowest reading.",
        "For {series_name}, measure the distance from the smallest to the largest reading among the anchor month {date} and the two months immediately before it.",
        "The window is three consecutive months, with {date} last. Report the maximum-minus-minimum amount for {series_name}.",
        "Use the {series_name} readings two months before {date}, one month before it, and at {date}; subtract their smallest from their largest.",
        "I want the width of {series_name}'s observed value interval over {date} and its two preceding months, expressed as high less low.",
        "How much larger is the maximum {series_name} reading than the minimum reading in the three-month segment terminating at {date}?",
        "From the three most recent monthly {series_name} observations up through {date}, compute the spread as maximum minus minimum.",
        "Please reduce the {series_name} values for {date} and the prior two months to their numeric range width.",
        "What gap remains after subtracting the lowest {series_name} observation from the highest one across the three months ending at {date}?",
        "For the three-month {series_name} window that includes {date} and the two months behind it, give the high-low difference, not the endpoints.",
        "Take the three consecutive {series_name} records whose newest month is {date}; how wide is their range from lowest to highest value?",
        "Determine {series_name}'s largest-minus-smallest variation over the anchor month {date} plus the two prior calendar months.",
        "In the three-month window ending with {date}, what is the nonnegative distance between the most and least elevated {series_name} readings?",
    ],
    "peak3": [
        "Among {series_name} at {date} and at the two preceding months, which numeric reading is the largest?",
        "Take the three-month block of {series_name} finishing at {date} and return its maximum observed value.",
        "What is the uppermost {series_name} reading in the inclusive three-month window ending with {date}?",
        "I need the value of the highest {series_name} observation among {date} and its two immediate predecessor months.",
        "Of the three consecutive monthly {series_name} readings up to and including {date}, give me the greatest number.",
        "Find the maximum of {series_name} at {date}, one calendar month before it, and two calendar months before it.",
        "Please report the peak magnitude of {series_name} across the three months ending at {date}, rather than the month of the peak.",
        "For {date} and the preceding two months, what is the highest stored level reached by {series_name}?",
        "Choose the largest value from the three {series_name} entries whose newest month is {date}.",
        "I am interested in the high value only: the maximum {series_name} observation in the trailing three-month period including {date}.",
        "What number tops the {series_name} readings for the three consecutive months that end in {date}?",
        "For {series_name}, return the upper extreme among the anchor month {date} and the two months just before it.",
        "Which value would be last if the {series_name} readings for {date} and the prior two months were sorted from smallest to largest?",
        "Use the three monthly {series_name} records ending at {date}; report only the greatest of their values.",
        "What was the maximum observed {series_name} amount over the anchor month {date} plus the two preceding calendar months?",
        "Locate the largest {series_name} measurement in the three-month interval ending at {date}, and return the measurement itself.",
        "The comparison set contains {date} and its two predecessor months. What is its largest {series_name} reading?",
        "For the inclusive three-month run that finishes at {date}, give the highest numeric entry in {series_name}.",
        "I want the largest of {series_name}'s current and previous two monthly readings, using {date} as current.",
        "Read the three {series_name} observations ending with {date} and retain the one with the greatest numeric value.",
        "What high-water value does {series_name} attain among {date} and the two calendar months immediately before it?",
        "From the {series_name} window starting two months before {date} and ending at {date}, return the maximum value.",
        "For {series_name}, pick the high reading out of the three consecutive monthly readings whose endpoint is {date}.",
        "What is the largest number observed for {series_name} over the three-month period that includes {date} and the two months before it?",
    ],
}

OOD = {
    "relative_percent_change": [
        ("Express {series_name}'s change from the month before {date} to {date} as a percentage of the earlier reading.", "100*(x[0]-x[-1])/x[-1]"),
        ("What percentage growth does {series_name} show at {date} relative to its immediately preceding month?", "percentage_growth_previous_to_current"),
        ("For {series_name} at {date}, subtract the previous month's level, divide by that previous level, and multiply by one hundred.", "relative_change_in_percent"),
        ("I need {series_name}'s month-on-month rate of change in percent for {date}, using last month as the base.", "percent_change_previous_baseline"),
        ("How large is the movement into {date} for {series_name} when quoted as a percentage of the prior month's value?", "normalized_difference_times_100"),
        ("Use the immediately preceding {series_name} observation as a hundred-percent baseline; what percentage increase or decrease occurred by {date}?", "relative_percent_increase_or_decrease"),
    ],
    "adjacent_month_ratio": [
        ("For {series_name}, divide the {date} reading by the reading from one calendar month earlier.", "x[0]/x[-1]"),
        ("How many times the previous month's level is {series_name} at {date}?", "current_to_previous_ratio"),
        ("Give the multiplicative factor from the preceding month to {date} for {series_name}, with a factor of one meaning unchanged.", "multiplicative_growth_factor"),
        ("I want a quotient, using {series_name} at {date} as the numerator and its immediately prior value as the denominator.", "current_divided_by_previous"),
        ("Report the ratio of the newer to the older {series_name} observation in the adjacent-month pair ending at {date}.", "newer_to_older_quotient"),
        ("With {date} as the anchor, express the current {series_name} value as a multiple of its one-month-lagged value.", "current_as_multiple_of_lag_one"),
    ],
    "fitted_linear_trend": [
        ("Fit a least-squares straight line to {series_name} over {date} and the preceding two months; what is its slope per month?", "OLS_slope_three_months"),
        ("For the three {series_name} observations ending at {date}, regress the values on equally spaced month indices and report the fitted coefficient.", "linear_regression_coefficient"),
        ("What monthly trend coefficient results from an ordinary linear fit to {series_name} in the three-month window ending with {date}?", "fitted_trend_slope"),
        ("Use a least-squares line through the {series_name} readings at {date} and the two prior months to estimate a per-month slope.", "least_squares_rate_per_month"),
        ("I need the slope of the best-fitting straight line for the three consecutive {series_name} months whose endpoint is {date}.", "best_fit_line_slope"),
        ("Assign time indices zero, one, and two to the three {series_name} months ending at {date}; fit an intercept and slope and return the slope.", "OLS_time_index_slope_with_intercept"),
    ],
    "population_zscore": [
        ("Standardize {series_name} at {date} using the mean and population standard deviation of that month and its two predecessors; return the z-score.", "(x[0]-mean3)/population_std3"),
        ("How many population standard deviations away from its three-month mean is {series_name} at {date}, including {date} in that window?", "current_population_zscore"),
        ("For {series_name}, take the {date} value minus the mean of the three months ending there, then divide by that window's population standard deviation.", "center_then_scale_by_population_std"),
        ("What standardized score does the {date} observation receive within the last three monthly {series_name} readings, when the sum of squared deviations is divided by three?", "zscore_using_population_variance"),
        ("Use {date} and the previous two {series_name} months as the reference population and give the current observation's signed z-score.", "signed_population_zscore"),
        ("Convert the {date} reading of {series_name} to a zero-mean, unit-population-standard-deviation score based on the three-month window ending there.", "unit_population_std_standardization"),
    ],
    "minmax_normalization": [
        ("Map {series_name} at {date} onto a zero-to-one scale using the minimum and maximum of that month and the two preceding months.", "(x[0]-min3)/(max3-min3)"),
        ("For the three {series_name} months ending at {date}, subtract their minimum from the current value and divide by their maximum-minus-minimum range.", "current_minmax_normalized"),
        ("Where does the {date} reading sit between zero for the lowest and one for the highest {series_name} reading in the trailing three-month window?", "relative_position_within_minmax_range"),
        ("Normalize the current {series_name} observation at {date} by stretching the three-month minimum to zero and the three-month maximum to one.", "zero_one_minmax_scaling"),
        ("I want {series_name}'s fractional position in its high-low interval over {date} and the prior two months, measured from the low end.", "fraction_above_window_minimum"),
        ("Using only {date} and the two earlier months of {series_name}, return the current reading after min-max scaling to the interval [0, 1].", "minmax_scaling_current_value"),
    ],
    "three_month_median": [
        ("Sort the {series_name} readings for {date} and the prior two months, then return the middle value.", "median3"),
        ("What is the median {series_name} observation in the three-month block ending at {date}?", "three_observation_median"),
        ("Of the three monthly {series_name} readings ending with {date}, choose the second one after ordering them by value.", "second_order_statistic_of_three"),
        ("I need the central ranked value, rather than the arithmetic average, of {series_name} over {date} and its two preceding months.", "middle_ordered_value"),
        ("For the three consecutive {series_name} months whose newest month is {date}, report their fiftieth percentile using the middle observed value.", "middle_value_percentile50"),
        ("Take {series_name} at {date} and at the previous two months; discard one highest and one lowest value, and give the value left.", "remove_extremes_to_obtain_median"),
    ],
    "unsupported_temporal_scope": [
        ("Find the arithmetic average of {series_name} across four consecutive months ending at {date}.", "mean_offsets_-3_-2_-1_0"),
        ("Average {series_name} over the three calendar months immediately before {date}; leave the {date} observation out.", "mean_offsets_-3_-2_-1"),
        ("Which {series_name} value is larger, the one at {date} or the one immediately before it? Return the larger value from those two months only.", "max_offsets_-1_0"),
        ("For {series_name}, calculate the high-minus-low range of the four months finishing at {date}.", "range_offsets_-3_-2_-1_0"),
        ("Go back exactly two calendar months from {date} and read that month's {series_name} entry.", "read_offset_-2"),
        ("Look up {series_name} in the same calendar month one year before {date}.", "read_offset_-12"),
    ],
    "other_three_month_aggregation": [
        ("Add up {series_name} for {date} and the two previous months and return the three-month total without dividing it.", "sum3"),
        ("What is the smallest {series_name} reading among {date} and the two calendar months preceding it?", "minimum3"),
        ("Compute the population standard deviation of {series_name} across the three consecutive months ending at {date}.", "population_standard_deviation3"),
        ("For the {series_name} window containing {date} and its prior two months, give the population variance, dividing the squared deviations by three.", "population_variance3"),
        ("Take the geometric mean of the three {series_name} observations ending with {date}, by taking the cube root of their product.", "geometric_mean3"),
        ("Average {series_name} over {date} and the previous two months with weights 0.5 for the current month, 0.3 for the previous month, and 0.2 for the oldest.", "unequal_weight_mean3"),
    ],
    "peak_month_not_peak_value": [
        ("In the three {series_name} months ending at {date}, name the month with the highest reading; choose the earliest month if there is a tie.", "argmax_month_earliest_tie"),
        ("Which calendar label belongs to the maximum {series_name} value across {date} and the two months before it? Resolve ties in favor of the earliest label.", "argmax_calendar_label"),
        ("Return the date, rather than the numeric magnitude, of {series_name}'s peak in the trailing three-month window including {date}; use the earliest tied date.", "peak_date_not_scalar"),
        ("For {series_name} over {date} and its two predecessor months, tell me which month won the highest-value comparison, taking the oldest if tied.", "winning_month_of_maximum"),
        ("Locate the greatest of the three {series_name} readings ending with {date} and give that observation's month, with the earliest occurrence breaking a tie.", "month_of_greatest_reading"),
        ("I need the month identifier attached to the highest {series_name} reading in the three-month block ending at {date}; on equal highs pick the earlier month.", "maximum_record_month_identifier"),
    ],
    "forecast_unobserved_value": [
        ("Using the {series_name} history through {date}, forecast the value for the following calendar month.", "forecast_offset_+1"),
        ("What do you predict {series_name} will be one month after {date}, based only on observations available through {date}?", "predict_next_month_from_history"),
        ("Extrapolate {series_name} beyond the record ending at {date} and estimate the next monthly observation.", "extrapolate_unobserved_next_month"),
        ("Please project {series_name} two months ahead from {date}; I want a prediction, not a lookup of an existing row.", "forecast_offset_+2"),
        ("Treat {date} as the last observed month of {series_name}. What value should I expect in the month immediately afterward?", "expected_future_unobserved_value"),
        ("Based on {series_name} up to and including {date}, estimate next month's level before that observation is recorded.", "estimate_unrecorded_next_level"),
    ],
    "cross_series_operation": [
        ("At {date}, subtract the value of the separate series named Control from the value of {series_name}.", "same_month_cross_series_difference"),
        ("Compare {series_name} with the separate Control series at {date} by dividing the former's value by the latter's.", "same_month_cross_series_ratio"),
        ("What is the correlation between {series_name} and the distinct Control series over {date} and the two preceding months?", "cross_series_three_month_correlation"),
        ("For {date}, return the larger of the {series_name} reading and the reading in the other series called Control.", "cross_series_maximum_at_anchor"),
        ("Average the two contemporaneous readings at {date}: one from {series_name} and the other from the separate Control series.", "cross_series_same_month_mean"),
        ("Fit {series_name} as a function of the distinct Control series using the three months ending at {date}, and give the regression slope.", "cross_series_regression_slope"),
    ],
    "alternative_adjacent_difference": [
        ("For {series_name}, subtract the {date} reading from the preceding month's reading, in that order.", "x[-1]-x[0]"),
        ("How large is the absolute difference between {series_name} at {date} and one month earlier? Discard the sign.", "abs(x[0]-x[-1])"),
        ("Take the month-to-month change in {series_name} ending at {date} and return its square.", "(x[0]-x[-1])**2"),
        ("For the change in {series_name} into {date}, return only -1 for a decrease, 0 for no change, or 1 for an increase.", "sign(x[0]-x[-1])"),
        ("Compute {series_name}'s increase from the preceding month to {date}, but replace any negative result with zero.", "max(0,x[0]-x[-1])"),
        ("At {date}, calculate twice the signed difference between the current {series_name} reading and the reading one month earlier.", "2*(x[0]-x[-1])"),
    ],
}


def main():
    rows = []
    for intent in INTENTS:
        if len(KNOWN[intent]) != 24:
            raise ValueError(f"known count differs for {intent}")
        for utterance in KNOWN[intent]:
            rows.append({
                "utterance": utterance, "gold_intent": intent, "ood_family": None,
                "risk_group": "known", "allow_numeric_read": True,
                "expected_provenance_offsets": OFFSETS[intent],
                "requested_operator": OPERATORS[intent],
                "label_reason": "Exact single-series scalar task in the six-intent contract, with the stated temporal support and operator.",
            })
    for family, examples in OOD.items():
        if len(examples) != 6:
            raise ValueError(f"OOD family count differs for {family}")
        for utterance, requested_operator in examples:
            rows.append({
                "utterance": utterance, "gold_intent": None, "ood_family": family,
                "risk_group": "near", "allow_numeric_read": False,
                "expected_provenance_offsets": None, "requested_operator": requested_operator,
                "label_reason": "Requested operation, temporal support, input arity, or output type differs from all six admitted tasks; numeric coincidence does not change the label.",
            })
    random.Random(2026102701).shuffle(rows)
    seen = set()
    for index, row in enumerate(rows, 1):
        row.update(query_id=f"v5-held-en-{index:03d}", series_name="{series_name}", date="{date}", partition="sealed_held_v5", language="en")
        normalized = re.sub(r"\W+", " ", row["utterance"].lower()).strip()
        if normalized in seen:
            raise ValueError("duplicate utterance after punctuation/case normalization")
        seen.add(normalized)
        fields = {field for _, field, _, _ in Formatter().parse(row["utterance"]) if field is not None}
        if fields != {"series_name", "date"}:
            raise ValueError("unexpected or missing slots")
    if len(rows) != 216 or Counter(row["gold_intent"] for row in rows)[None] != 72:
        raise ValueError("wrong total or OOD count")
    corpus = {"schema": "hepta.memory.v5.sealed-language.v1", "queries": rows}
    content = (json.dumps(corpus, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path = ROOT / "queries.en.json"
    with path.open("xb") as stream:
        stream.write(content)
    print(json.dumps({"path": str(path), "queries": len(rows), "known": 144, "near_ood": 72, "sha256": hashlib.sha256(content).hexdigest()}, sort_keys=True))


if __name__ == "__main__":
    main()
