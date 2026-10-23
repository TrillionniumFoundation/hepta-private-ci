# Independent joint-state / fresh-audit combination review

No blocking finding. Full four-file set reviewed against exact #3609 base `4ed40f768e466b3e526e25e9ac4da8f43cffecd8`, combining #3608 donor `25194eb730bd64fbfcf0275cefbf033c7dae0770` and narrowly extending admission at three existing fresh-only audit entrances. Full diff SHA256 `41b3a2574681e4b8258cd82da8b8ca3522f0a66fe2e044fbfe900a3746e14fc6`; tree `785997f524e837287906560c95d05f671ef7d435`. All file hashes in independent-review-manifest.json. Temporary index used for complete new-file tree calculation; repository source/index not modified by reviewer.

## Contract and independently reproduced defect

Unlike execute (documented trusted trajectory suffix), evaluate/evaluate_dependence and full_outcome_audit already reject nonzero initial steps and are full-episode fresh-input APIs. They assume State/JointState constructor validation but previously accepted ordinary immutable namedtuple structural lookalikes which had never run it. This is an actual finite Python API admission gap, not evidence of malicious-code sandbox escape, hardware budget theft or production vulnerability.

Reviewer independently executed both baseline modules loaded directly from git HEAD (the shared worktree was already being patched). With Config(activation_cost=5,risk_aversion=0), one text-unit action at step0 then STOP/EMIT: admitted State reports mean_paid_units10 under evaluate and evaluate_dependence; namedtuple with same levels/budget but step0 active_mask1 reports5. Full_outcome_audit nominal JointState reports mean_modeled_cost10; outer namedtuple wrapping that structural generation reports5. Thus validating only JointState.generation on constructor does not cover an outer structural object passed directly into fresh audit. Initial exploratory lookup used the wrong report key; corrected reproduction used mean_paid_units for counterfactual and mean_modeled_cost for joint audit.

## Source changes

JointState.__post_init__ now checks isinstance(generation,State) before dereferencing it; existing Fraction prior bounds, boolean witness and fresh-root witness checks remain. Counterfactual evaluate/evaluate_dependence check isinstance(initial,State) before prior step/reserve guards. full_outcome_audit similarly checks isinstance(initial,JointState) before generation access. Error contracts remain ValueError with existing message strings. No cost formula, action policy, probability law, prior admission, witness scoring or downstream verification changes.

The scope is appropriate: ordinary subclasses inheriting validation remain accepted; legitimate paid successors remain usable as continuations but not fresh audit roots. execute/rollout and their existing trust boundary are untouched. There is no attempt to secure against subclasses overriding admission, object.__new__, object.__setattr__, monkeypatching or hostile Python executing in-process; such hardening was not requested. Generic hypothetical Fraction priors remain model parameters rather than authenticated evidence and are not improperly restricted to a predefined few cases.

The donor test_joint_generation_admission.py is byte-for-byte identical to the donor. Its four tests cover structural/non-State generation rejection before field access, valid State subclasses/paid advance/fresh audit cost and continued generic priors. Three new fresh-audit tests cover both structural masks including otherwise-valid mask0, None rejection with precise errors, outer structural JointState rejection, and nominal State/JointState subclass positive cost10 under all three APIs. Valid dependence regime avoids a confounding rejection. No assertion weakens authorization or replaces actual execution with synthetic receipt-only validation.

## Validation

Reviewer command: `PYTHONPATH=experiments/multimodal_output_portfolio/v4 python3 -m unittest test_joint_generation_admission test_fresh_audit_admission test_execute_boundary test_fresh_root_custody -v`: **14 passed** in0.004s; independent-tests.log. This includes seven new cases plus seven existing continuation/fresh-root tests. git diff --check passed.

Independently inspected parent's tests.txt: all76 tests passed. Inspected negative-regressions.txt: reverting two production files to exact baseline with new tests retained produced failures5/errors7, exit1; preserved as negative evidence, not a passing run. The errors include before-field-access invalid-type behavior and are not additional security findings. Existing counterfactual Ruff failures F401(actions import) and E731(dynamic_policy lambda) are recorded in ruff-baseline.txt on unchanged lines, outside this minimal fix. No lint suppression or unrelated cleanup added; do not claim whole-file Ruff passed.

Exact remote commit verification and CI remain parent-owned subsequent work. These are finite synthetic experiment admission and modeled accounting tests, not verified checkpoint provenance, independent real witness, measured hardware efficiency, Runtime authorization or scientific closure.

Final file SHA256:

- experiments/multimodal_output_portfolio/v4/counterfactual_audit.py: `23a15a9574da00ba8272bbcaaf7988361c8a4190c5769d1ebe717ba0d3f228d9`
- experiments/multimodal_output_portfolio/v4/joint_evidence_generation.py: `6330363892fd78d5783b39dbb87e8d67d28da3992eefbc07ab82b404fa5b9307`
- experiments/multimodal_output_portfolio/v4/test_fresh_audit_admission.py: `b595413fe648c0d241b99d7855fbfdbe1e0b79f5356b053796f3abd41d74ee1e`
- experiments/multimodal_output_portfolio/v4/test_joint_generation_admission.py: `7fe66f3d2a56cd77c59fe39fee1c733c6f9b452ed6ce1c10c252e28134ab99c8`
