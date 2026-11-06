# Exact policy-mixture repair: independent follow-up

The previously failing budget `5928486/1000000007` was rerun against frontier.py SHA-256 `50e2dca0fc76c9dc254bd20d27d47556f03334df840c44033b4828f642792a6c`.

The `mix<1` repair is now incorporated into the returned root policy before exact evaluation. Every prior failure is closed: returned policy errors/resources exactly equal the reported values, both expected resources equal the declared budget, total terminal mass equals one under each hypothesis, and the returned root probabilities sum to one. Exact lower and upper risk coincide at `6525721169/14000000098`. The unchanged repair multiplier is `1167398181655056199102600/1167398181655056214382883`.

All seven targeted checks pass in `POLICY_REPAIR_POSTFIX_REVIEW.json`. This is an independent rerun of the concrete bug, not a repeat of the larger frontier study. No remaining issue was found in this repair's stated scope.
