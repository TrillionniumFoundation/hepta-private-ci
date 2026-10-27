# V4 interrupted-delivery recovery

Workspace maintenance removed the local research checkout and complete V4 evidence archive before the delivery branch was updated. This branch anchors the two bundle parts and one figure whose uploads were confirmed beforehand. The original PR #4004 remains at its complete V3 delivery.

This is an incomplete 16,000,002-byte prefix of the 217,549,454-byte V4 history bundle. It must not be described as a complete V4 source or evidence release. Parts 3 and 28 were checked and were absent from the remote object store at recovery start. Library searches did not locate a complete backup.

Known prior identities, retained as recovery targets (not proof that the full artifacts remain available):

- Original executed V4 source: 6206dfba0a3219534dd1a0274431bf48fd23673c
- Original final V4 evidence: 3c509f9bb9a9724cddbe6a917c728e022582fefe
- Complete V4 bundle SHA-256: 9e5f6702eea7a0e9679885323278e61f8f08f8237c655220ecaf81e88d2fda93
- Part 1: 8,000,001 bytes; SHA-256 0bcc3ffd312ce256dce8cb6c40ba694004e475f1891823861987ccaf5a011626
- Part 2: 8,000,001 bytes; SHA-256 127c4989b832059e92bb88a4587454ee1dd0b12b4b69c6ebfde132840bcc0a1a

Recovery must verify any salvaged object against its original Git identity and report missing objects explicitly. No old result may be reconstructed from reported metrics and presented as the original raw experiment. The scientific qualification was all_blockers_closed=false and production_admitted=false even before the interruption.
