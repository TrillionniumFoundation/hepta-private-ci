# C4 independent strategy cost accounting

This directory retains the independently frozen recalculation of the complete C4 legal-v3, reused-v3 and full-limb from-zero raw records. The original native measurements are not rerun or replaced. Source is Chain `8df4b21d893906570d48f5beafabb3b31e0aefbc`, tree `6f5aaa2af0432e27e24b6bd2ad18013ab4423d14`. All joint qualification gates remain HOLD.

Start with [the independent review](independent-review.md), [cost tables](cost-tables.md), and [the frozen delivery manifest](delivery-manifest.json). The manifest binds twelve exact files, including both recalculation programs and the failed first postprocessing log. That failure was a missing closing dictionary brace in the summarizer, after the first raw recalculation had succeeded. It did not change native inputs, outcomes or original reader records.

The parser checks 32 original JSONL files totaling 882441044 bytes. The complete original strategy archive, three retained executable images, index and lossless transport reconstruction are available under [complete raw evidence](../complete-raw/README.md). Input and source bindings here retain the original absolute provenance paths; those paths are not instructions to access a different source or run a new native campaign.

## Reproduce without overwriting frozen evidence

Create a fresh scratch directory with `pq_recovery/strategy-C4-independent/` and `w1/C4-strategy-receipts/`. Reconstruct and verify the original strategy archive using the complete-raw instructions, then extract its contents into the latter directory. Copy only `recompute_strategy_raw.py` and `summarize_strategy_costs.py` into the former directory. Run the raw recomputation first, then the summarizer. Both programs derive their input locations from that layout and create new output in the scratch directory. Compare the resulting measured quantities, original input hashes and verdicts with the frozen outputs here. The programs do not invoke Cargo, the production reader, a remote worker or a new native measurement.

Root also used [a separately written from-zero arithmetic checker](../recalculate_from_zero_totals.py). Its [retained result](root-from-zero-review.json) binds the final `cost-findings.json` SHA-256 `484496eac9d873092fa53b37f66a5ec2e485a4cb922d57f3194f6c0369b7e8b0`. The checker independently joins all 288 candidate proof hashes and 1440 recorded verdicts, sums the 72 measured cohort denominators, and checks all nine class totals. It computes exact rational ratios before presenting decimal values. Invoke it with the extracted raw from-zero campaign, this findings file, and a fresh output path.

## Material finding and scope

The 288 from-zero invalid candidates require no valid-winner acquisition. Their inclusive measured setup/search/clone CPU is 20.182415 ms, versus 427.969566 ms for the production verifier alone: a ratio of 21.205072. Charging the entire separately timed campaign material generation once to the attacker raises that denominator to 21.862656 ms and leaves a ratio of 19.575369. Production and the explicitly named full-limb verifier share arithmetic and are not added together.

These measurements exclude wire/JSON transport, sending, public admission, queueing and storage. Unmeasured phases are not treated as zero. The existing-winner mutation comparison has a different, marginal denominator and remains separate. Legal factorial horizons share prefixes; specialized arms include paid unsupported setup; different suites have different challenge domains and timer scopes. None establishes a universal cheapest-work lower bound, the original public-service resource gate, an authentic learning gain or a release qualification.
