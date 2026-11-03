"""Public, author-written V5 selection templates; used for model calibration.

These are synthetic queries written for this small contract, not user dialogue.
They are disclosed development material and never called independent held data.
"""

from .training_language import lines


KNOWN = {
    "at": lines("""
Please read off {series_name} from the record for {date}.
I am asking for the stored {series_name} figure for {date} alone.
Which value does the archive assign to {series_name} in {date}?
Get me the monthly {series_name} number under the label {date}.
For {date}, quote the observed level of {series_name}.
Consult the record and return the {date} entry in {series_name}.
Supply the original {series_name} observation associated with {date}.
Pull the value out of the {series_name} cell for {date}.
What numeric entry appears for {series_name} at month {date}?
Read {series_name} where the month equals {date}.
State the archived monthly amount of {series_name} dated {date}.
I need a direct lookup of {series_name} for {date}.
Find the numerical observation of {series_name} bearing the month {date}.
Give me {series_name}'s recorded level in {date}, with no aggregation.
Use the specified month {date} to fetch one {series_name} reading.
For the chosen timestamp {date}, provide the recorded {series_name} value itself.
"""),
    "previous": lines("""
Read off {series_name} from the month that directly precedes {date}.
Find the {series_name} entry after moving the {date} calendar position one step back.
I need {series_name} for the month immediately earlier than {date}.
Fetch the recorded {series_name} from exactly one month before the anchor {date}.
Which {series_name} figure belongs to the predecessor of month {date}?
Use a backward shift of one month from {date} to locate the {series_name} value.
For reference month {date}, provide the one-month-prior {series_name} reading.
Get the {series_name} observation in the calendar slot immediately left of {date}.
Take {date} as now and read {series_name} for last month.
Quote the earlier member of the consecutive monthly pair ending at {date} in {series_name}.
Step from {date} to the previous calendar month and read {series_name} there.
The value requested is {series_name} one month before the indicated {date}.
Retrieve the {series_name} datum directly before the reference month's entry at {date}.
Look up the preceding month of {date} in the {series_name} record.
Give the prior monthly level of {series_name}; the anchor month is {date}.
Move the date back by one calendar month from {date} and return that {series_name} measurement.
"""),
    "change": lines("""
Report {series_name}'s current reading at {date} less its immediately earlier monthly reading.
Calculate the net gain in {series_name} between the preceding month and {date}.
Use the {date} {series_name} level as the minuend and the previous month as the subtrahend.
What is the signed one-month increment of {series_name} into {date}?
Deduct the previous observation from the current {series_name} observation at {date}.
In original measurement units, how much did {series_name} rise or fall at {date}?
Take {series_name} for the reference month {date} and subtract its predecessor month's level.
Give the signed displacement from last month's {series_name} to this month's, where this month is {date}.
Find the net difference with {date} first and the month before it second for {series_name}.
Compute latest less preceding for the {series_name} pair that ends at {date}.
How many units separate {series_name} at {date} from one month before, positive if the latest is larger?
Return the monthly delta of {series_name} at {date} without converting it to a percentage.
What amount must be added to last month's {series_name} to reach the reading at {date}?
Measure the increase of {series_name} from the month before {date} to {date}, allowing a negative answer.
For {series_name}, subtract the older from the newer of the two monthly entries ending at {date}.
Calculate the signed month-over-month difference in {series_name} for the reference {date}.
"""),
    "mean3": lines("""
Add the three {series_name} figures ending with {date} and divide the result by their number.
I need the simple average of {series_name} for {date} together with the prior two months.
Give the equal-weight arithmetic mean of the final three monthly {series_name} records through {date}.
Calculate a three-entry trailing average in {series_name}, using {date} as the last entry.
What is the ordinary mean level of {series_name} across the three months up to {date}, inclusive?
Average the reference month {date} and its two immediate predecessor months in {series_name}.
Report the mean formed with one-third weight on each of the three {series_name} months ending at {date}.
For the three-month window whose right edge is {date}, compute the arithmetic average of {series_name}.
Sum {series_name} in the indicated month {date} and the two months before it, then take one third.
Smooth the {date} {series_name} reading by averaging it with its two monthly predecessors.
Give the mean of the latest trio of consecutive {series_name} observations through {date}.
Find the arithmetic center of {series_name}'s three monthly values ending with {date}.
Compute the equally weighted mean for {series_name} from two months before {date} through {date}.
Return the ordinary three-period moving average of the monthly {series_name} series at {date}.
For {series_name}, use the last three months including {date} and average all three numbers.
Take the total of the three latest monthly readings in {series_name} at {date} and divide by 3.
"""),
    "range3": lines("""
How large is maximum minus minimum for {series_name} across the three months ending with {date}?
Return the difference between the greatest and least {series_name} readings in the trailing three-month window at {date}.
Find the numerical span covered by {series_name} in {date} and its two previous months.
Deduct the minimum from the maximum of the last three monthly {series_name} entries through {date}.
Give the high-to-low distance of {series_name} over the three consecutive months ending in {date}.
Compute the width between the upper and lower extremes of the three {series_name} months through {date}.
Measure the range of the latest three {series_name} observations, with the last one dated {date}.
For {date} and the previous two months, how far apart are the highest and lowest {series_name} values?
Take the greatest less the least {series_name} across the three-month period finishing at {date}.
Calculate the full low-to-high span of {series_name} in the three months through {date}, inclusive.
What is the separation of the minimum and maximum {series_name} among {date} and its two predecessor months?
Report the amplitude of {series_name}, defined as maximum minus minimum, over the three months ending at {date}.
Read the extremes of the trailing three {series_name} months at {date} and subtract the lower from the upper.
Find the interval width from smallest to largest for the three monthly {series_name} numbers ending with {date}.
I need the three-month high-low range of {series_name} up to and including {date}.
Give the peak minus trough of {series_name} across {date} and the previous two calendar months.
"""),
    "peak3": lines("""
Of the three {series_name} observations ending with {date}, return the biggest number.
What maximum level does {series_name} reach in {date} and the two months just before it?
Read the upper extreme of the three latest monthly {series_name} entries through {date}.
Pick the greatest {series_name} measurement from the three-month period concluding with {date}.
I need the high point as a number for {series_name} across the trailing three months at {date}.
Return the largest recorded amount in the last three {series_name} months, including {date}.
Choose the maximum among the reference month's {series_name} at {date} and its two predecessors.
Report only the highest value of {series_name} in the three-month window ending at {date}.
For {series_name}, take the greatest of the three monthly numbers up to and including {date}.
Give the top reading from {series_name} over {date} and its two immediate earlier months.
Which numerical level is highest among the three {series_name} entries finishing in {date}?
Find the ceiling of {series_name}'s three-month trailing values at {date}.
Read off the maximum value from the three-month block of {series_name} ending with {date}.
Select the greatest observation across the last three months in {series_name}, using {date} as the endpoint.
Take the three consecutive {series_name} monthly observations through {date} and return their maximum.
What is the largest number attained by {series_name} from two months before {date} through {date}?
"""),
}

OOD = {
    "ratio_and_normalization": lines("""
Express {series_name} in {date} as a fraction of the immediately preceding month's reading.
What percentage of last month's {series_name} is the {date} value?
Divide the {date} {series_name} figure by the mean of the preceding two months.
Give the month-on-month percentage gain in {series_name} ending with {date}.
Normalize the {date} {series_name} level using the largest of the three months ending there.
Return the ratio between maximum and minimum of {series_name} in the three months through {date}.
For {series_name}, report the logarithm of current divided by previous at {date}.
How many times as large is {series_name} in {date} as in the preceding month?
"""),
    "other_differences": lines("""
For {series_name}, deduct the current {date} reading from the preceding month's reading.
What is last month's {series_name} less this month's, if this month is {date}?
Give the unsigned magnitude of the monthly change of {series_name} at {date}.
Subtract the three-month mean from {series_name}'s {date} entry.
Compute {series_name} in {date} less its value two months earlier.
Take the minimum minus the maximum of the three monthly {series_name} observations through {date}.
Give the gap between {series_name} at {date} and the peak over the three months ending there.
How much did {series_name} fall from last month to {date}, with decreases returned as positive values?
"""),
    "different_window": lines("""
Average {series_name} across the two monthly records ending with {date}.
Find the highest {series_name} among the four months up to and including {date}.
Compute maximum minus minimum for {series_name} in the six months ending at {date}.
Give the arithmetic mean of {series_name} over the entire year ending in {date}.
Return the numerical range of {series_name} over {date} and its preceding three months.
Find the maximum of {series_name} over the single-month window {date}.
What is the average of the twelve monthly {series_name} readings ending at {date}?
Report the peak of {series_name} for the two months concluding in {date}.
"""),
    "different_alignment": lines("""
Give the three-month average of {series_name} beginning with {date}.
Find the highest {series_name} in the three months after {date}, excluding {date}.
Compute the range of {series_name} in the three months strictly before {date}.
Average {series_name} in the month before {date}, {date} itself and the month after it.
Return the peak of {series_name} for the three-month window centered on {date}.
Find the high-low range across {series_name} in {date} and the next two months.
Give the average of the three {series_name} months that precede the anchor {date}.
Use {date} as the first of three months and calculate maximum minus minimum of {series_name}.
"""),
    "future_or_other_lag": lines("""
Read the stored {series_name} observation in the month following {date}.
Go backward two calendar months from {date} and look up {series_name}.
Retrieve {series_name} for the same month one year earlier than {date}.
Fetch the {series_name} entry two monthly steps after {date}.
Take a three-month backward offset from {date} and report {series_name} there.
Give {series_name} for the next calendar month, treating {date} as the reference.
Read {series_name} six months before the month labeled {date}.
Move {date} forward by one month and quote that {series_name} measurement.
"""),
    "other_averages": lines("""
Calculate the geometric average of {series_name} in the three months ending with {date}.
Use unequal weights 1, 2 and 3 for the three-month {series_name} average through {date}.
Give the harmonic mean of the three {series_name} observations up to {date}.
Find the midpoint of the largest and smallest {series_name} values across the three months ending at {date}.
Average only the minimum and maximum {series_name} in the three-month block through {date}.
Compute a root-mean-square level of {series_name} for the three months ending at {date}.
Apply exponential weights to the three {series_name} months through {date} and report the weighted average.
What is the trimmed mean after dropping the highest {series_name} month from the trio ending at {date}?
"""),
    "rank_statistics": lines("""
Return the median of the three {series_name} months ending at {date}.
Which value ranks second highest among the three monthly {series_name} entries through {date}?
Select the lowest {series_name} observation in the three months concluding with {date}.
Give the middle value after sorting the three {series_name} numbers through {date}.
Compute the first quartile of {series_name} in the three-month window ending at {date}.
Rank all three {series_name} readings in the trailing three-month window at {date}.
Return the second-smallest of {date} and its two predecessor months in {series_name}.
Find the 90th percentile of the three monthly {series_name} observations through {date}.
"""),
    "dispersion_or_fit": lines("""
Estimate the standard deviation of {series_name} across the three months ending at {date}.
Compute the sample variance of the three {series_name} values through {date}.
Fit a straight line to the final three {series_name} months at {date} and report its slope.
Give the mean absolute deviation from the average of the three {series_name} months through {date}.
Find the coefficient of variation for {series_name} over the three months ending at {date}.
Return the squared deviations of {series_name} from its three-month mean through {date}.
Calculate the residual error of a linear fit to the three {series_name} entries ending at {date}.
Report a confidence interval around the three-month average of {series_name} at {date}.
"""),
    "sums_and_cumulative": lines("""
Add together the three {series_name} readings ending at {date} and return their total.
Give the cumulative sum of {series_name} up to and including {date}.
Compute the product of the three {series_name} months ending with {date}.
Count the number of positive {series_name} values among the last three months through {date}.
Return the year-to-date total of {series_name} at {date}.
How many of the three monthly {series_name} observations ending at {date} exceed their mean?
Give the sum of the maximum and minimum of {series_name} in the three months ending at {date}.
Accumulate all {series_name} readings from the start of the archive through {date}.
"""),
    "forecast_or_estimate": lines("""
Forecast {series_name} one month beyond {date} using the recorded history.
Fill in a missing {series_name} entry at {date} by interpolation.
Predict the next three-month average of {series_name} after {date}.
Explain the cause of the monthly change in {series_name} at {date}.
Extrapolate the recent trend of {series_name} to the month following {date}.
Estimate what {series_name} would have been at {date} without a policy intervention.
Prove that the peak in {series_name} over the three months through {date} has a causal explanation.
Test whether {series_name}'s rise at {date} is statistically significant.
"""),
    "non_numeric_result_or_mutation": lines("""
Name the month when {series_name} was largest in the three-month window ending at {date}.
List the three {series_name} values ending with {date} in chronological order.
Replace {series_name}'s stored {date} reading with the preceding month's value.
Remove the recorded {series_name} observation at {date}.
Return both the mean and the maximum of {series_name} in the three months through {date}.
Tell me whether {series_name} rose in {date} rather than giving the signed difference.
Give the date of the highest value, not the value, in {series_name} over the three months ending at {date}.
Report the {date} value of {series_name} together with its prior-month value.
"""),
    "cross_variable": lines("""
Average the {date} observations of {series_name} and another series called R23.
Subtract R23's {date} value from the {date} reading of {series_name}.
Which is larger at {date}, {series_name} or series R23?
Divide {series_name} at {date} by a second series R23 at the same date.
Take the maximum across {series_name} and R23 for the three months ending at {date}.
Find the difference between the trailing three-month means of {series_name} and R23 at {date}.
Add {series_name} and R23 in the month {date}.
Calculate the correlation of {series_name} with R23 over the three months ending at {date}.
"""),
}
