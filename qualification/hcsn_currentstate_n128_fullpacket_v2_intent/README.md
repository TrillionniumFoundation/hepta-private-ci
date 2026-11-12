# N128 current-state full-packet v2 intent

**HOLD_NO_EXECUTION / all_closed=false.**

This evidence-only successor freezes the smallest honest N128 full-state denominator and the serializer/oracle requirements needed after #6251. It adds no candidate implementation and performs no dynamics.

Newly closed:

- authentic N128 law/input/source identities are explicit;
- the complete 14-capsule coordinate denominator is fixed at 4,623,492 binary64 coordinates;
- candidate and independent-oracle expm budgets are separately fixed at 460 each;
- the canonical structured serialization contract, comparison schedule, and refusal controls are explicit.

Still open:

- candidate v2 structured core;
- canonical binary serializer and cold loader;
- independent unreduced dense oracle;
- full-coordinate comparator;
- durable resource allocation and final execution-key freeze.

The point-in-time #6255 resource witness does not admit this run. No execution key is assigned, because assigning one before the source/oracle/serializer and resource closure would create an unsafe runnable intent. Historical negative results and UNKNOWN values remain unchanged.
