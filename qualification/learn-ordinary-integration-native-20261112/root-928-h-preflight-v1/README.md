# Actual ai395 native preflight failure, attempt v1

Durable job `1a1cf244b03-2564-19a8`, key `ci-native-root92817b2f-20261112-ff41-v1`, exited 1 at preflight. The actual exception was `FileNotFoundError` while checking `/home/qq/hepta-learn-ff41-target`. No Cargo process or native stage was launched; `stages` is empty and there is no JUnit. UID 1000 was observed, but the failed attempt did not retain a completed sudo / occupancy / disk preflight receipt. None is inferred here.

The intended exact source was `92817b2fee9f088a44831ee894d973eff3333853`, tree `c73fae7021766799925e38d6e4ef9268fc5c61f0`. The complete original stdout, empty stderr, durable terminal metadata, executed driver / request, and exact incremental source bundle are retained. The bundle requires original local `82c895ceb49732ccd7097cde39d1c4da232e8507`; its SHA-256 is `647fabd11063b9f420232a075a438a7d6471d079ddf5100c48ec81c7759a6f93`.

A later v2 was requested with a new exclusive target and separate checkout / records. Its launch or eventual result is a separate observation, not a successful result for v1. Complete positive / NoUpdate / daemon-plus-Root cold-restart counts remain 0 / 0 / 0.
