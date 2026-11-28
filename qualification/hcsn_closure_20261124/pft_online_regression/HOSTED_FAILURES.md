# Initial hosted configuration failures

The first three automatic workflow evaluations failed before creating a job.
They are retained independently of the successful local driver rehearsal.

| Run | Source | Event | Result | Jobs |
| --- | --- | --- | --- | ---: |
| [46095000214](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/46095000214) | `11634adcaca2cc21110b1efa6ea038054e6769f4` | push | failure | 0 |
| [46095044222](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/46095044222) | `a2d8f9c794bebb0e6b4d085fa2b07babc33c550d` | push | failure | 0 |
| [46095276745](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/46095276745) | `b13eec0a12a1320a8295fff99d85953c249fa1c5` | push | failure | 0 |

Source inspection identified `runner.temp` in job-level `env`, where the
[official context availability table](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability)
does not permit the runner context. The API exposes failure and zero jobs;
the connector did not expose a service error annotation. The diagnosis follows
from that documented source violation, rather than an invented error message.

The correction constructs the evidence path from RUNNER_TEMP inside the
runner step and exports it through GITHUB_ENV for subsequent steps. No Python
implementation, fixture, count or numerical threshold changes. The local
17-control suite is not repeated for this workflow-only correction.

`hosted-initial-failures.tar.gz` retains the raw run/job API observations,
original workflow, correction formatting record and SHA-256 inventory.
Archive: 5,171 bytes; SHA-256
`c8518e1481072f6b6d7c008d64ad4137f007fdf0d0c104de58efcc6b88f05fc0`.
The corrected workflow's hosted result is a separate observation; no failure
here is renamed a test pass or omitted from the delivery history.
