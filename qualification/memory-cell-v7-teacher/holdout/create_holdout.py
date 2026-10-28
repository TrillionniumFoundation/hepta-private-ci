#!/usr/bin/env python3
"""Freeze an independently authored synthetic English routing holdout.

This file must not import a candidate router, teacher prompt, old holdout, model
weights, or an evaluation result. Labels are emitted separately from requests.
Re-running after publication is a byte verification, never an overwrite.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys


SEED = 7281041
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
REJECT = "__reject__"
SERIES = (
    "monthly series K41", "monthly measure J26", "monthly indicator L58",
    "monthly record M73", "monthly quantity N64", "monthly metric P82",
)
DATES = ("2019-12", "2020-01", "2020-07", "2021-03", "2022-10", "2024-11")


def lines(text):
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


SUPPORTED = {
    "at": lines("""
In the ledger for {series_name}, I have highlighted the row marked {date}. Copy its numeric contents into my answer.
The reporting period is {date}. What number is actually entered for {series_name} in that period?
Treat {date} as a row key in {series_name}; the answer should be the number at that key.
I am filling the {date} box in a report on {series_name}. Supply the archived observation for that box.
Open the {series_name} table at {date} and transcribe the recorded number exactly as a value.
Use the dated observation itself: {series_name}, timestamp {date}, numeric contents please.
My question concerns only the entry labeled {date} in {series_name}. What does that entry say numerically?
The month I selected is {date}; return the existing measurement attached to that month in {series_name}.
Locate the intersection of {series_name} and month {date}, and give the scalar stored there.
Which recorded number would I see beside {date} when inspecting the monthly history of {series_name}?
For the {series_name} archive, reproduce the actual observation whose timestamp is {date}.
I need to cite the {date} measurement of {series_name}. Please provide that measurement's numeric value.
Keep the month fixed at {date} and consult the stored {series_name} observation at that position.
Select the {date} record of {series_name}; my requested output is its number, unchanged.
The requested calendar slot is {date}. Return the recorded amount occupying it in {series_name}.
Read the value field of the {series_name} record identified by month {date}.
I want the source measurement, with no calculation: {series_name} in {date}.
From the historical monthly observations of {series_name}, take the one stamped {date} and report its value.
For {series_name}, use exactly the indicated month {date} as the lookup address and return the archived scalar.
The month and series are already specified: {date} and {series_name}. Give the number entered at that address.
"""),
    "previous": lines("""
In {series_name}, find the calendar row immediately before the row labeled {date}; copy that earlier row's number.
Starting at {date}, turn the calendar back by a single month and give the recorded {series_name} for the resulting month.
My reference is {date}, but the observation I need from {series_name} belongs to the month directly before that reference.
Consider the consecutive monthly pair in {series_name} whose later member is {date}. Return only the older member's value.
Take the month immediately adjacent to {date} on its earlier side and retrieve {series_name} there.
Which {series_name} measurement would be selected by moving exactly one monthly row backward from {date}?
For {series_name}, the target is the calendar predecessor of {date}; provide its stored numeric contents.
I need the observation that comes immediately before {date} in the monthly chronology of {series_name}.
If {date} is the current reporting month, supply the recorded {series_name} for the reporting month just completed before it.
Use a one-month delay: with {date} as the anchor, return the earlier {series_name} measurement rather than a calculation.
At the {date} position in {series_name}, move to the directly preceding calendar month and read its number.
The entry sought in {series_name} is one calendar month older than {date}, including a year rollover if necessary.
Retrieve the {series_name} measurement attached to the monthly tick immediately to the past of {date}.
For reference {date}, report the {series_name} observation with a calendar offset of minus one month.
Advance from the preceding month to {date} by one monthly step; I want {series_name} at that step's starting month.
The requested {series_name} value is from the last monthly slot before {date}, without including the reference slot.
Go back one page from {date} in the monthly record of {series_name} and quote the value on that page.
From the adjacent-month pair ending in {date}, select the earlier observation of {series_name} as the answer.
Shift the lookup timestamp from {date} to its immediately prior month; then return {series_name} at the shifted timestamp.
For {series_name}, give the recorded value a single calendar-month interval before the anchor {date}.
"""),
    "change": lines("""
For {series_name}, what signed adjustment must be added to the preceding month's level to obtain the level recorded at {date}?
Treat the month before {date} as the starting point and {date} as the endpoint in {series_name}; calculate endpoint value minus starting value.
In {series_name}, subtract the value in the calendar row before {date} from the value in the {date} row.
Report the arithmetic increase from the immediately preceding month into {date} for {series_name}, using a negative number for a decline.
How many original units were gained between the previous month's {series_name} measurement and the {date} measurement? Preserve negative gains.
Let the newer reading be {series_name} at {date} and the older reading be one month earlier. Return newer minus older.
For the adjacent {series_name} observations ending at {date}, reduce the later reading by the earlier reading; return that signed result.
The baseline is {series_name} one calendar month before {date}. Subtract that baseline from the {date} observation.
Measure the signed vertical step in {series_name} from its preceding monthly observation to its observation at {date}.
What number closes the equation previous-month {series_name} plus that number equals {series_name} at {date}?
For {series_name}, compute the reference-month observation at {date} after deducting only its immediately preceding monthly observation.
Use {date} minus the month just before it, in value terms rather than time terms, for {series_name}.
Calculate the net unit movement of {series_name} between two adjacent months, with {date} being the later month.
Return the difference in the order latest observation then immediate predecessor for {series_name}, with latest fixed at {date}.
If the {date} reading of {series_name} is lower than the preceding one, my answer should be negative. Give that signed subtraction.
Take the number in {series_name}'s {date} row and remove the number from the preceding calendar row by subtraction.
For {series_name} at {date}, calculate the monthly gain in original units, defining gain as current level less the immediately prior level.
Give the displacement from the earlier to the later of two consecutive {series_name} readings whose later timestamp is {date}, with direction retained.
Using only {date} and the preceding month of {series_name}, form current reading minus prior reading as one scalar.
In {series_name}, how large is the signed step needed to move from last month's number to the number at {date}?
"""),
    "mean3": lines("""
For {series_name}, pool the measurements from {date} and its two immediately preceding months, then divide their total equally among three positions; give the amount per position.
Use three consecutive {series_name} observations with {date} last. Add them and divide by three, returning that single number.
What constant number could replace all three {series_name} readings from the window ending at {date} while preserving their total? The window contains the reference month and the two before it.
Compute the equally weighted arithmetic center of the {series_name} readings at {date}, one month before, and two months before.
I want a simple three-observation moving average of {series_name}, evaluated with {date} as the newest included month.
Give the arithmetic average of the {series_name} trio made up of the anchor {date} and both immediately earlier calendar months.
Assign weight one third to each {series_name} measurement in the three-month block ending with {date}, and return the weighted total.
For {series_name}, evaluate the sum of the current and previous two monthly readings divided by three, taking current to mean {date}.
Smooth {series_name} at the right-hand endpoint {date} using an ordinary mean with three monthly observations and equal weights.
The sample is the {date} observation of {series_name} together with its first and second monthly lags. Return the arithmetic mean of that sample.
Calculate the mean of the three latest {series_name} entries available through {date}, counting the {date} entry as one of the three.
Combine exactly the {series_name} values at {date} and the two months immediately before it by adding them, then scaling the sum by one third.
With {date} as the inclusive end of a three-month window, report the ordinary numerical average for {series_name}.
For {series_name}, treat {date} and its two calendar predecessors as equally important observations and compute their arithmetic average.
Take the three consecutive calendar rows of {series_name} ending at {date}; their total divided by their count is my requested answer.
Return the simple trailing mean of length three for monthly {series_name} at the anchor {date}.
I need the equal-share value of the total across {date} and the two earlier consecutive months of {series_name}: total divided by three.
Use the monthly values of {series_name} at offsets zero, minus one, and minus two from {date}; compute their arithmetic mean.
For the {series_name} window that contains {date} as its third and final month, give the equally weighted mean of all three readings.
Average the anchor-month {series_name} observation at {date} with the two observations immediately behind it on the monthly calendar, using equal weights.
"""),
    "range3": lines("""
Place the three {series_name} readings ending at {date} on a number line. What is the distance from the leftmost to the rightmost reading?
For {date} and its two preceding months in {series_name}, return the width of the smallest closed numeric interval containing all three values.
Among the three consecutive {series_name} observations with {date} last, subtract the smallest number from the largest number.
Measure the separation between the top and bottom {series_name} readings in the block containing {date} and the two immediately earlier months.
Give the numerical extent of the trailing three observations of {series_name} at {date}, defining extent as greatest value less least value.
Take the high end and low end of the three-month {series_name} window concluding at {date}; return high end minus low end.
I need the full value span across {date} and the previous two months of {series_name}, expressed as upper extreme minus lower extreme.
For the {series_name} observations at {date} and its first two monthly lags, calculate largest minus smallest.
How wide is the band of values occupied by the three monthly {series_name} records ending at {date}? Use maximum minus minimum.
Report the distance between the two most separated values among the three {series_name} readings ending with {date}.
Use the inclusive three-month window whose endpoint is {date} in {series_name}; subtract its minimum observation from its maximum observation.
For {series_name}, find the width between the outermost of the three monthly values at {date} and the two months before it.
Take the largest pairwise absolute separation within the three monthly {series_name} readings ending at {date}; this is the maximum minus minimum.
Return one nonnegative number describing the high-to-low spread of {series_name} from two months before {date} through {date}.
The three {series_name} readings through {date} define a lower and upper boundary. Give the upper boundary less the lower boundary as a value.
Calculate the range of the {series_name} sample consisting exactly of {date}, its preceding month, and the month preceding that.
Within the trailing block of three months ending at {date}, how far apart are the least and greatest numbers recorded for {series_name}?
For {series_name}, subtract the bottom reading from the top reading over the three-month window with {date} in its last slot.
Give the breadth of the smallest numeric envelope covering {series_name} at {date} and the immediately preceding two monthly observations.
Over the three consecutive months terminating in {date}, compute the maximum of {series_name} minus its minimum, returning only that difference.
"""),
    "peak3": lines("""
Among {series_name} in {date} and the two immediately earlier months, return the one reading that no other reading exceeds.
Choose the largest numerical observation from the consecutive three-month block of {series_name} whose final month is {date}.
For the three {series_name} values ending at {date}, give the upper bound that is actually attained by one of those values.
Which value wins a largest-number comparison across {date} and the prior two months of {series_name}? Return the winning number.
Take the most elevated reading in {series_name} over the inclusive three-month window ending with {date}.
I need the maximum of the {series_name} measurements at calendar offsets zero, minus one, and minus two from {date}.
From {series_name}'s reference-month reading at {date} and its two immediate monthly predecessors, select the numerically greatest.
Report the single highest recorded amount in the {series_name} trio whose newest member is dated {date}.
For {series_name}, put the three readings ending at {date} in order by size and give only the largest value.
Give the largest scalar present in the three-row monthly block of {series_name} that concludes at {date}.
Use {date} as the third month in a three-month sequence of {series_name}; select the maximum value across that sequence.
What is the highest level among the {series_name} readings from two months before {date} through {date}, with both endpoints included?
The sample consists of the {date} value of {series_name} and the previous two monthly values. Return its maximum numeric member.
For the latest three calendar months through {date}, which recorded {series_name} number is greatest? Give the number itself.
Select the uppermost value reached by {series_name} in the three-month block containing {date} and the two months before it.
Across the reference month {date} and its first two monthly lags, return the greatest observed value of {series_name}.
The requested number is the maximum measurement in the trailing three-month sample of {series_name} anchored at {date}.
Read {series_name} for {date} and the preceding two calendar months, then keep only the greatest of those readings as the answer.
Give the ceiling of the observed values, meaning their actual maximum, for the three {series_name} months ending in {date}.
Find the numerically largest entry in the trailing three monthly records of {series_name}, counting {date} as the final record.
"""),
}

UNSUPPORTED = {
    "direction_or_derived_difference": lines("""
For {series_name}, subtract the {date} level from the immediately preceding month's level, so a fall produces a positive result.
Compute earlier minus later for the adjacent monthly {series_name} pair whose later month is {date}.
Give the magnitude of the change between the prior month and {date} in {series_name}, discarding whether it rose or fell.
Subtract the {series_name} observation two calendar months before {date} from the observation at {date}.
Return {series_name} at {date} minus its arithmetic mean over the three months ending there.
"""),
    "different_window_length": lines("""
Compute the ordinary average of {series_name} over the four consecutive months ending with {date}.
Take the maximum of just the two monthly {series_name} readings ending at {date}.
Give the high minus low range of {series_name} over the six-month window that finishes at {date}.
Calculate a twelve-month trailing arithmetic mean of {series_name} at {date}.
Compute the maximum of the singleton window containing only the {date} observation of {series_name}.
"""),
    "different_window_alignment": lines("""
Average the three {series_name} observations immediately before {date}, explicitly leaving the {date} value out.
For {series_name}, report the maximum over the three-month window starting with {date} and extending into the next two months.
Calculate maximum minus minimum of {series_name} over a centered three-month window: the month before {date}, {date}, and the month after it.
Compute the arithmetic mean for {series_name} over {date} and its two following calendar months.
Return the greatest {series_name} reading in the three months strictly earlier than {date}, excluding the reference month itself.
"""),
    "different_statistic": lines("""
Among {series_name} at {date} and the two prior months, return the smallest value.
Find the median of the three monthly {series_name} values ending at {date}.
Give the total of {series_name} over the three months ending with {date}, without dividing the total.
Calculate the population standard deviation of {series_name} across {date} and its two preceding months.
Count the number of positive readings in the trailing three-month {series_name} window at {date}.
"""),
    "relative_or_normalized_output": lines("""
Express the change in {series_name} from the preceding month into {date} as a percentage of the preceding month's value.
For {series_name}, divide the observation at {date} by the immediately prior monthly observation.
Compute the natural logarithm of current divided by previous for {series_name}, with current fixed at {date}.
Report the {date} value of {series_name} divided by its trailing three-month arithmetic mean.
Scale the three-month range of {series_name} ending at {date} by the maximum in that same window.
"""),
    "different_output_shape": lines("""
For the three {series_name} readings ending at {date}, name the calendar month at which the maximum occurred.
Return the chronological list of all three {series_name} values ending with {date}.
Answer yes or no: is {series_name} at {date} greater than its immediately preceding monthly value?
Draw a line chart of the three monthly {series_name} observations ending at {date}.
Return the rank of the {date} {series_name} observation within its three-month trailing window, rather than a measurement value.
"""),
    "multiple_requested_results": lines("""
Provide both {series_name} at {date} and its value in the preceding month as two separate numbers.
For the three months of {series_name} ending at {date}, return the arithmetic mean and the maximum together.
Give the maximum {series_name} value over the trailing three months at {date} along with the month that attained it.
Report the signed one-month change in {series_name} at {date} and also the current month's stored value.
For {date} and the preceding two months of {series_name}, return the lowest value and highest value in two labeled fields.
"""),
    "different_lookup_address": lines("""
Look up {series_name} for the calendar month immediately after {date}.
Retrieve the recorded {series_name} from two calendar months before the anchor {date}.
Read the {series_name} value for the same calendar month one year earlier than {date}.
Return the daily {series_name} measurement from the fifteenth day of the month {date}.
Using {date} as the anchor, fetch {series_name} for the month three calendar steps farther into the past.
"""),
    "different_mean_definition": lines("""
Average the three {series_name} values ending at {date}, giving half the weight to {date} and one quarter to each of the prior two months.
Find the geometric mean of {series_name} over {date} and the two preceding months.
Return the harmonic mean of the three {series_name} observations ending at {date}.
Compute the root mean square of {series_name} in the trailing three-month window through {date}.
Take the midpoint between the maximum and minimum {series_name} values in the three months ending at {date}.
"""),
    "inference_or_explanation": lines("""
Forecast {series_name} for the calendar month after {date} from the preceding observations.
Explain the cause of the change in {series_name} between the prior month and {date}.
Estimate an absent {series_name} observation at {date} by interpolating between neighboring months.
Test whether the one-month change of {series_name} into {date} is statistically significant.
Give a confidence interval for the mean of {series_name} across {date} and its two preceding months.
"""),
    "data_mutation": lines("""
Replace the stored {series_name} observation for {date} with zero and save the revised record.
Delete the {date} entry from the historical monthly series {series_name}.
Multiply the archived {series_name} value at {date} by two and write the result back into its original cell.
Append a new observation to {series_name} for the month after {date}, setting that new value to 100.
Erase the three {series_name} records ending at {date} from the data store.
"""),
    "cross_series_computation": lines("""
Subtract monthly comparison series Z99 at {date} from {series_name} at {date}.
Average {series_name} and monthly comparison series Z99 for the month {date}.
Compute the correlation between {series_name} and monthly comparison series Z99 over the three months ending at {date}.
Return whichever is larger at {date}: {series_name} or monthly comparison series Z99.
Find the difference between the trailing three-month means of {series_name} and monthly comparison series Z99, both ending at {date}.
"""),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalized(request):
    text = request["utterance"].casefold()
    text = text.replace(request["series_name"].casefold(), " [series] ")
    text = text.replace(request["date"], " [date] ")
    return " ".join(text.split())


def make_rows():
    assert set(SUPPORTED) == set(INTENTS)
    assert all(len(values) == 20 for values in SUPPORTED.values())
    assert len(UNSUPPORTED) == 12
    assert all(len(values) == 5 for values in UNSUPPORTED.values())
    rows = []
    for label, templates in SUPPORTED.items():
        for index, template in enumerate(templates):
            rows.append({"template": template, "expected_intent": label,
                         "family": "supported-" + label, "family_item": index})
    for family, templates in UNSUPPORTED.items():
        for index, template in enumerate(templates):
            rows.append({"template": template, "expected_intent": REJECT,
                         "family": family, "family_item": index})
    rng = random.Random(SEED)
    slots = [(series, date) for series in SERIES for date in DATES] * 5
    rng.shuffle(slots)
    rng.shuffle(rows)
    requests, labels = [], []
    for index, (row, (series, date)) in enumerate(zip(rows, slots, strict=True)):
        request = {"utterance": row["template"].format(series_name=series, date=date),
                   "series_name": series, "date": date}
        identity = sha256(canonical(request))
        requests.append(request)
        labels.append({"index": index, "request_sha256": identity, "id": identity[:24],
                       "expected_intent": row["expected_intent"], "family": row["family"],
                       "family_item": row["family_item"]})
    assert len(requests) == len(labels) == 180
    assert len({normalized(row) for row in requests}) == 180
    return requests, labels


def verify_public_disjoint(requests, source):
    # Only public language is imported. Candidate and old-held modules are absent.
    sys.path.insert(0, str(source))
    from v5.corpus import build_public_corpus
    folds, _ = build_public_corpus()
    public = {normalized({key: row[key] for key in ("utterance", "series_name", "date")})
              for rows in folds.values() for row in rows}
    overlap = [i for i, request in enumerate(requests) if normalized(request) in public]
    if overlap:
        raise ValueError("Exact normalized duplicate of public language: " + repr(overlap))
    return {"public_rows_checked": sum(len(rows) for rows in folds.values()),
            "exact_normalized_duplicates": 0,
            "does_not_establish_semantic_independence": True}


def write_once(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Frozen output already exists with different bytes: " + str(path))
        return
    with path.open("xb") as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    requests, labels = make_rows()
    public_audit = verify_public_disjoint(requests, root / "source")
    request_bytes = b"".join(canonical(row) + b"\n" for row in requests)
    label_bytes = b"".join(canonical(row) + b"\n" for row in labels)
    manifest = {
        "schema": "hepta.cell-v7.independent-synthetic-held.v1",
        "authorship": "independent holdout-side assistant; synthetic authored English",
        "author_task": "/root/semantic_holdout_v7",
        "not_human_or_business_samples": True,
        "candidate_prompt_read": False,
        "candidate_outputs_read": False,
        "previous_independent_held_text_read": False,
        "candidate_guided_edits": False,
        "seed": SEED,
        "rows": 180,
        "supported_rows": 120,
        "ood_rows": 60,
        "by_intent": dict(sorted(Counter(row["expected_intent"] for row in labels).items())),
        "by_family": dict(sorted(Counter(row["family"] for row in labels).items())),
        "serving_fields_exactly": ["date", "series_name", "utterance"],
        "evaluator_only_fields": ["index", "request_sha256", "id", "expected_intent", "family", "family_item"],
        "requests": {"file": "requests.jsonl", "bytes": len(request_bytes), "sha256": sha256(request_bytes)},
        "labels": {"file": "labels.jsonl", "bytes": len(label_bytes), "sha256": sha256(label_bytes)},
        "generator_sha256": sha256(Path(__file__).read_bytes()),
        "sources_manifest_sha256": sha256((root / "SOURCES.json").read_bytes()),
        "public_duplicate_audit": public_audit,
        "limits": ["Finite routing labels only; no numeric execution or production trace is evaluated here.",
                   "Only exact normalized overlap with public language is checked; paraphrase overlap is possible.",
                   "One assistant authored both inputs and expected labels; no independent human annotation audit.",
                   "Unsupported tasks remain rejected even if a special numeric dataset could yield a coincidentally equal answer."],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_once(args.output / "requests.jsonl", request_bytes)
    write_once(args.output / "labels.jsonl", label_bytes)
    write_once(args.output / "MANIFEST.json", canonical(manifest) + b"\n")
    print(json.dumps(manifest, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
