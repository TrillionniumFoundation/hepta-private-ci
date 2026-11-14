# Retained local development RED

Before source freeze, the first local analytic comparison failed on the final
discounted-occupation output:

- candidate interval output: `3fd2a94b7d104d44`
- initial reference output: `3fd2a94b7d104d43`
- difference: one binary64 ULP

The initial reference used ordinary binary64 intermediate values for the
closed-form expression. A 100-digit Decimal evaluation of the same independent
closed form rounds to `3fd2a94b7d104d44`, matching the candidate's uniquely
rounded exact rational interval. The candidate propagation source was not
changed by this correction; only the independent test reference was changed to
avoid intermediate binary64 rounding.

This record is local development evidence, not a precommitted execution result.
