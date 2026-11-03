"""Public author-created diagnostic fold, excluded from model selection."""

from .training_language import lines


KNOWN = {
    "at": lines("""
What number was entered in {series_name} under month {date}?
At {date}, what does the {series_name} record actually say?
Bring back the archived observation for {series_name} dated {date}.
The lookup key is {date}; return that month's {series_name} figure.
Read one value from {series_name}: the one assigned to {date}.
State the recorded amount in the {date} slot of {series_name}.
Which historical {series_name} measurement is attached to {date}?
Please quote {series_name} for the indicated calendar month {date}.
Find the original number in {series_name}'s monthly record for {date}.
Return the stored {date} measurement from {series_name} without any calculation.
Consult {series_name} at the given month {date} and report the value.
I am interested only in the single {series_name} reading from {date}.
"""),
    "previous": lines("""
What number was entered for {series_name} in the month right before {date}?
Back up from {date} by one month, then fetch {series_name}.
Give {series_name} from the earlier calendar neighbor of {date}.
The anchor is {date}, but the lookup should use the immediately previous month's {series_name}.
Read the {series_name} observation in the monthly cell immediately left of the {date} cell.
Find {series_name} after subtracting one calendar month from the timestamp {date}.
I need the preceding month's recorded {series_name}, not a difference, relative to {date}.
Quote the monthly {series_name} number that comes directly before {date}.
Taking {date} as the present month, what did the preceding month record for {series_name}?
Choose the predecessor of {date} in the monthly {series_name} archive.
Locate the monthly entry immediately earlier than {date} and return its {series_name} value.
For {series_name}, use one month before the specified {date} as the read address.
"""),
    "change": lines("""
How many units did {series_name} gain or lose upon moving from the prior month into {date}?
From the {date} figure of {series_name}, take away its figure for the preceding month.
Use the later minus earlier convention for the monthly {series_name} pair ending with {date}.
Report the signed amount by which {series_name} at {date} exceeds its prior-month value.
The target is {date}; calculate current less previous for {series_name}.
Give the increase in {series_name} between last month and {date}, negative when it dropped.
Subtract the one-month-old {series_name} reading from the observation dated {date}.
Compute the month-on-month advance of {series_name} into {date} in measurement units.
Find the signed step from the immediately preceding {series_name} month to {date}.
For {series_name}, what is the {date} observation minus the observation one month earlier?
Calculate the difference from prior to current for {series_name} at {date} without taking an absolute value.
Return the original-unit change in {series_name} over the one-month interval ending in {date}.
"""),
    "mean3": lines("""
Combine the three {series_name} monthly readings ending at {date} by adding them and dividing by three.
Read {series_name} in {date} and in each of the prior two months, then take their ordinary average.
I want an arithmetic three-month moving mean for {series_name} whose last month is {date}.
What is one third of the total of the final three {series_name} entries through {date}?
Give equal weight to {date} and its two predecessor months when averaging {series_name}.
For the trio of consecutive {series_name} months finishing at {date}, calculate the arithmetic mean.
Compute the simple mean of {series_name} over the trailing monthly trio at {date}.
The rightmost month is {date}; average it and the two months before it in {series_name}.
Report the equally weighted average of three consecutive {series_name} observations concluding with {date}.
For {series_name}, sum the observations at {date} and at lags one and two months, then divide by 3.
Obtain a smoothed {series_name} level by the ordinary average over the three months through {date}.
Take an arithmetic average across the monthly {series_name} window running from two months before {date} to {date}.
"""),
    "range3": lines("""
Within the three {series_name} months ending in {date}, how big is the largest-minus-smallest gap?
Find the breadth of the value interval occupied by {series_name} in {date} and its two prior months.
Take away the minimum from the maximum in the last three monthly {series_name} observations through {date}.
Report the range width of {series_name} over the trailing monthly trio at {date}.
The window contains {date} and the preceding two months; return the high less low of {series_name}.
Give the numerical distance from lowest to highest across the three {series_name} months concluding at {date}.
Compute the upper bound minus the lower bound of {series_name}'s last three observed monthly values through {date}.
Across the final three months through {date}, what is the maximum-to-minimum span of {series_name}?
For {series_name}, subtract the smallest of the three months ending at {date} from the largest of them.
How much room between the floor and ceiling of the three monthly {series_name} values ending at {date}?
Find the peak-to-trough separation of {series_name} for {date} plus the preceding pair of months.
Return maximum less minimum over the consecutive three-month {series_name} window with endpoint {date}.
"""),
    "peak3": lines("""
Choose the greatest number from {series_name} in {date} and the preceding pair of months.
What is the numerical top of {series_name} over the three-month period finishing with {date}?
Find the largest of the final trio of monthly {series_name} values through {date}.
For the three {series_name} months up to {date}, inclusive, return the uppermost observation.
Report the ceiling value reached by {series_name} across {date} and its preceding two months.
Take the highest monthly level of {series_name} in the three-month block terminating at {date}.
Read three consecutive {series_name} values ending in {date}; keep the greatest one.
Return the numerical peak of {series_name} over the trailing monthly trio anchored at {date}.
Among {date} and its two monthly predecessors, give the biggest {series_name} measurement.
Supply the maximum amount from the three latest {series_name} observations at {date}.
What number is at the top of the three-month {series_name} readings through {date}?
Keep only the highest recorded {series_name} value from the window of three months ending in {date}.
"""),
}

OOD = {
    "ratio_and_normalization": lines("""
Scale the {date} reading of {series_name} by the average of the preceding two months.
What is the relative month-to-month change of {series_name} at {date}, in percent?
Calculate the logarithmic return between last month's {series_name} and the {date} reading.
Divide the three-month {series_name} maximum through {date} by its three-month minimum.
Express {series_name} at {date} in units of its previous monthly value.
Return the ratio of the {date} {series_name} observation to its trailing three-month average.
"""),
    "other_differences": lines("""
For {series_name}, take the preceding month less {date}, with the earlier value first.
Deduct {series_name} in {date} from the value recorded one month before it.
Ignore direction and return the absolute distance between {date} and the preceding {series_name} month.
Subtract the lowest from the average of the three {series_name} months ending at {date}.
Return the difference between {series_name} in {date} and in the same month of the previous year.
Find the smallest less the largest {series_name} across the three-month window ending at {date}.
"""),
    "different_window": lines("""
Give the ordinary average of the four {series_name} months terminating in {date}.
Choose the maximum from the two monthly {series_name} observations ending with {date}.
Find the six-month range of {series_name} through {date}, inclusive.
Return the arithmetic mean for {series_name} over the singleton month {date}.
Take maximum minus minimum across the last twelve {series_name} months at {date}.
Find the largest {series_name} over {date} and the previous four months.
"""),
    "different_alignment": lines("""
Use the three months beginning with {date} to find {series_name}'s arithmetic mean.
Return the peak of {series_name} in the three months immediately preceding {date}, leaving {date} out.
Compute the high-low span of {series_name} in a three-month window centered at {date}.
Find the maximum of {series_name} in {date} and the next pair of months.
Average the three {series_name} months strictly prior to the anchor {date}.
Use the month before, the month {date}, and the month after to find the range of {series_name}.
"""),
    "future_or_other_lag": lines("""
Read the following month's archived {series_name}, using {date} as the anchor.
Step back two months from {date} and retrieve the recorded {series_name} number.
Look up {series_name} in the equivalent calendar month a year before {date}.
Go to the monthly cell immediately right of {date} and read {series_name}.
Fetch the {series_name} entry at a lag of three months from {date}.
Quote {series_name} at the timestamp six calendar months earlier than {date}.
"""),
    "other_averages": lines("""
Take the cube root of the product of the three {series_name} values through {date}.
Return a weighted average of {series_name} over the three months ending at {date}, weighting the latest month twice.
Compute the harmonic average of {series_name}'s last three monthly entries at {date}.
Average the maximum and minimum of {series_name} across the three months ending in {date}.
Give the square root of the mean of squares of {series_name} over the final three months through {date}.
Use an exponential moving average for {series_name} at {date} with weights decreasing into the past.
"""),
    "rank_statistics": lines("""
Choose the runner-up {series_name} value in the three months ending at {date}.
Sort the three monthly {series_name} readings through {date} and return the one in the middle.
Take the smallest of {series_name} in {date} and its preceding two months.
Find the lower quartile of {series_name} over the trailing three months at {date}.
Return the rank of the {date} {series_name} value among its three-month window.
What is the middle-ranked observation of {series_name} in the three months ending in {date}?
"""),
    "dispersion_or_fit": lines("""
Measure the variance of {series_name} among {date} and the preceding pair of months.
Give the root-mean-square deviation from the mean of the three {series_name} values through {date}.
Find a least-squares trend slope for {series_name} over the three months concluding at {date}.
Compute the mean absolute deviation of the latest three {series_name} months at {date}.
Report the residual variance of a straight-line fit to {series_name} through the last three months at {date}.
Estimate uncertainty in the mean of {series_name} over the trailing three-month window at {date}.
"""),
    "sums_and_cumulative": lines("""
Give the total of {series_name} in {date} and the two prior months, without dividing it.
Multiply together the three {series_name} observations ending at {date}.
Count the nonzero {series_name} observations in the three-month block ending with {date}.
Return the running total of {series_name} from the start of the calendar year through {date}.
Add the minimum and maximum of {series_name} from the three months through {date}.
How many of the last three {series_name} months ending at {date} are larger than the preceding month?
"""),
    "forecast_or_estimate": lines("""
Extrapolate {series_name} from {date} into the next monthly period.
Predict the highest {series_name} value in the three future months after {date}.
Infer the missing {series_name} record for {date} from its neighboring months.
What caused the recorded {series_name} change at {date}?
Estimate what {series_name} at {date} would be under a different scenario.
Test the significance of the month-on-month {series_name} movement into {date}.
"""),
    "non_numeric_result_or_mutation": lines("""
Which calendar month contains the three-month maximum of {series_name} through {date}?
Return an ordered list of the three {series_name} observations ending in {date}.
Change the stored {date} entry of {series_name} to match its three-month average.
Erase the {date} record from {series_name}.
Give the maximum value and the range of {series_name} for the three months ending at {date}.
Is {series_name}'s {date} value above its preceding monthly value?
"""),
    "cross_variable": lines("""
At {date}, take the mean of {series_name} and the separate series called Q88.
Compute {series_name} minus series Q88 in the month {date}.
Find the joint maximum over {series_name} and Q88 for the three months ending at {date}.
Give the ratio of the three-month means of {series_name} and Q88 through {date}.
Compare {series_name} with a different series Q88 at {date} and tell me which is greater.
Calculate the covariance of {series_name} with Q88 over the three months ending at {date}.
"""),
}
