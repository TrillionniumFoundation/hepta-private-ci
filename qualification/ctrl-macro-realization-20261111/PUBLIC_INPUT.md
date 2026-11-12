# Retain actual acquisition input in new pair collection

The native pair collector now records `public-input.json` from the exact host
reply immediately before WRITE_TEXT, after the registered READ intervention.
It returns those same bytes to the actor, creates the file once, and leaves the
native callback hash binding available to the strict realization observer.
No private reference is added to this public projection.

Seven collector fixture methods passed, including exact post-intervention bytes,
no early capture and refusal to overwrite a second finalizer input. The existing
failure, missing outcome, deadline and original source checks remain active.
This changes only new collection code. Historical missing replies stay missing;
the original V4 operation is not replayed or rebound to this implementation.
Acquisition and policy benefit still require their separate original witnesses.

A shared manufactured collection fixture is retained for the following converter
stage. Its source bytes and scores are test data, not native observations.
