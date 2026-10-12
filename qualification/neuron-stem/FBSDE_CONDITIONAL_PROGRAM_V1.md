# Infer a state-dependent program, not one constant effect per sentence

Parent `4e38615f7821fa350ebc8e5214f22852fdfe0428`, Draft PR #1550.
The original study entry gains `conditional_program_induction_v1`. All older
families, cheap controls, neural models, Riccati kernels and owners stay intact.
This is finite Bayesian program induction within an explicit grammar, NOT
new neural training, arbitrary-language acquisition or production admission.

## Coupled state and program uncertainty

A frame has one latent program: one of six constant permutations, or one of
27 rules of the form `if role r holds colour c, apply transposition t; else
identity`. The 33 rules are uniform before observation. Names are alpha-renamed
using the existing exact-frame boundary. Words, conditions, colours, punctuation
and event order are NOT discarded. At most 8192 complete program assignments
are admitted before allocation; one/two-frame tasks have 33/1089 assignments.

For assignment theta, each candidate evolves ITS OWN predecessor state:

    x_(i+1)(theta) = F_(theta[group(i)])(x_i(theta), roles_i).

A selected verification reveals only its realized effect, as in the parent
six-effect observation interface. Neither the true predecessor, guard truth,
source program identifier nor final answer is given to the policy. The posterior
filters whole candidate trajectories by ALL selected effects. Substituting the
true state into the candidate guard would leak unqueried information; substituting
the initial state at every step would solve the wrong dynamics. Both distinctions
have regression coverage. Existing PlanningWorkspace performs the bounded finite
Bellman/BSDE recursion on this observation law; no new acceptance evaluator exists.

Checking a frame once need not identify its conditional rule. All still-informative
unqueried instances remain eligible. Different effects at two states can agree with
one conditional rule, rather than requiring a model split. This implementation does
not change its family after evidence: a joint zero-support observation is retained
and refused, never normalized; copying is refused rather than projected onto a
permutation. Original two checks, 20k nodes and 100ms process CPU per decision remain.
Construction has its own measured 100ms post-call bound, not free preparation.

## Fixed controlled experiment

Six strata, six name orders, three queries and lengths 2/3/4 give 324 stories and
36 distinct instruction strings. No case was filtered by error or disagreement.
Eight arms independently execute their own selected observations. Each arm's
outer simulator computes source effects at actual predecessors; its preparation
cost is counted separately. The exact registered-source control pays this execution
itself. This is logical information separation, not OS-isolated source authority.
All 2592 outputs are saved before final scoring. Replays are not independent data.

First complete local result (correct/answered out of 54):

| Stratum | Constant-frame two | Previous expand/audit | Conditional one | Conditional two | Cheap conditional probe |
| --- | ---: | ---: | ---: | ---: | ---: |
| Constant | 54/54 | 54/54 | 54/54 | 54/54 | 54/54 |
| Self guard | 46/54 | 42/42 | 54/54 | 54/54 | 54/54 |
| Observer guard | 54/54 | 54/54 | 54/54 | 54/54 | 54/54 |
| Mixed guards | 44/54 | 28/30 | 50/50 | 54/54 | 38/38 |
| Copy outside | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 |
| Time outside | 30/54 | 24/36 | 30/54 | 30/54 | 30/54 |

On mixed guards, same-prior two-step adds four correct answers relative to one
step and sixteen relative to cheap probing; each uses 108 checks. It costs more:
1.979s vs .773s vs .412s component CPU in the first batch. Exact source execution
is 54/54 in every stratum and remains much cheaper. There is no universal NDU or
full-lifecycle advantage, independent risk bound or new pretrained-model result.

Time-dependent instructions are deliberately outside this state-only family.
All conditional methods make 24 errors there: unobserved family misspecification
need not cause a zero-support observation. Copy refusal does NOT imply all unseen
semantics can be detected. Never label family agreement a semantic certificate.

Furthermore none of the first run's two-step final posteriors identifies a unique
program for every frame. In a concrete case, 33 candidates shrink to two and agree
on the current answer, but disagree at initial state (0,2,1). Successful current
reasoning is NOT proof that the correct general transition rule was learned. No
cross-episode deployment of a guessed singleton is introduced.

## Audit and reproduction

    python fbsde_study.py --profile conditional_program_induction_v1 --output /new/conditional
    python fbsde_conditional_artifact_checks.py -v /new/conditional

The independent reference compiles tables over all six predecessor states, then
enumerates conditional trajectories and Bellman actions. Source truth uses separate
regex interpretation rather than renderer lookup. It imports neither the runtime
conditional family, its transition function nor planner. Rehashed mutations must
reject fake program identification, added oracle states, erased/changed observations,
removed refusal cases, invented costs and semantic certification. Construction,
source preparation, recording and audit stay separately visible. Tests and final
source/merge CI qualify separately; no full native/Rust build is claimed.
