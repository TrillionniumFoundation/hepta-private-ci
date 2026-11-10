# Candidate delivery subcriterion readback

This post-hoc readback identifies the single paired correct-text delivery failure
in the original 108-episode candidate-retention campaign. Both arms selected and
wrote the correct text, preserved prior output, and have an original independent
receipt confirming source-image pixels. Both then delivered the same crop with
target coverage **0.888021778584392**, below the frozen **0.95** requirement.
Image IoU is 0.8660483556940068, above its 0.5 requirement. The failed subcriterion
is image target coverage.

The original crop is `[84, 842, 783, 878]`; the frozen reference target box is
`[67, 843, 792, 881]`. Geometry was recomputed from bound source annotations.
The report, plan, evidence chain, result, trajectory, public packet, delivery,
reference, source image and delivered image bytes passed their recorded
identity checks. The evaluator source matched its frozen SHA-256.

The 14 pairs with correct candidates available in both arms have selected-event
transitions: 2 true-to-true and 12 false-to-false. All nine newly available pairs
remain false-to-false. This is a descriptive common-availability subset; the
offered rosters are not fixed and these data are not independent confirmation.

`delivery_readback.py` ran read-only on the original ai395 assets through
`/usr/bin/python3 -`, with exit 0, empty stderr and complete 10,448-byte stdout.
The source SHA-256 before execution was
`7b6abff360c434fb0fa45075bfa38a8b8312c230977eb9b0fd2650d05ae10dd9`.
The exact output SHA-256 is
`7f4579eb4cb6115b48e2a5df2854a81ece9f2072020dde8feb24fd8b35cd43b9`.
The durable job was `1a1c341a0d0-e62c-408`; its terminal status is retained.

No actor, scorer or pixel decoder was rerun. No model was trained, no evaluation
rule changed, and no original execution artifact was modified. The output
rechecks geometry and bound image bytes, while retaining the original pixel
verification receipt. Provider/execution authenticity remains unqualified.
Scientific acceptance remains HOLD; production adoption remains false.
