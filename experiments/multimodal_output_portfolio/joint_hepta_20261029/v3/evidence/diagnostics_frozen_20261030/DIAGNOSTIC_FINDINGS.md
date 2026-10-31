# Frozen-prefix diagnostic findings

## Executed scope

The prespecified seed-17, width-32 dual joint/dynamic checkpoint was evaluated on eight fit sources and eight separate analysis sources. Both the encoder state and a one-shared-update prefix were frozen with exact content, budget, sunk cost and named random streams. Each source/prefix ran immediate-STOP and dynamic-continuation cohorts, four independent future draws, seven primary interventions and a repeated-verify challenge. All **2,048 actual four-media continuations** completed across **64 groups**, with **zero failures** and **zero excluded critic observations**. The full run took 69.317 seconds on this research host.

The raw tree retains each actual PNG/WAV/GIF/text bundle, independent readback NPZ, observed score, action/cost ledger, frozen prefix and public input. The source protocol and checkpoint identities are in `STUDY_PROTOCOL.json`; numerical comparisons and complete fitting results are in `STUDY_SUMMARY.json`.

## Main analysis results

The following CE differences compare an intervention with immediate STOP at the same frozen prefix. Units are the unchanged normalized utility/cost contract. Intervals are paired percentile bootstrap intervals over the eight original analysis sources; they are exploratory and not multiplicity-adjusted confirmation.

| Prefix | Intervention and subsequent behavior | CE difference | 95% source-bootstrap interval |
|---|---|---:|---|
| Encoder | shared update, then STOP | -0.005434 | [-0.021548, +0.012285] |
| Encoder | shared update, then sampled dynamic policy | -0.015666 | [-0.021450, -0.005281] |
| Encoder | verify, then STOP | -0.003014 | [-0.003038, -0.002989] |
| Encoder | verify twice, then STOP | -0.006019 | [-0.006054, -0.005993] |
| One shared update | another shared update, then STOP | -0.008445 | [-0.017321, -0.003198] |
| One shared update | another shared update, then dynamic policy | -0.014872 | [-0.031704, -0.001537] |
| One shared update | verify, then STOP | -0.003027 | [-0.003044, -0.003009] |
| One shared update | verify twice, then STOP | -0.006026 | [-0.006035, -0.006015] |

At the encoder prefix, all seven non-STOP interventions including the repeated-verify challenge followed by dynamic continuation had negative estimated CE differences; all their exploratory intervals were below zero. Some single modality updates followed immediately by STOP had positive point estimates, but their intervals crossed zero. This does not establish that arbitrary extra computation is beneficial.

## Verification

Across all 32 analysis conditioning groups, the first verify changed feedback in 32/32 cases and content in 0/32. With the clock held fixed, the mean actor-probability L1 change was 0.0013004. A second verify without content change produced new feedback in 0/32 cases.

For the immediate-STOP continuation, verification preserved the paired delivered content and utility while adding measured cost. The first verification may nevertheless influence subsequent decisions; the observed feedback/actor changes prevent calling it intrinsically information-free. In these cohorts, dynamic continuation did not recover its cost.

## Critic calibration and ranking

Before calibration, the critic-selected action differed substantially from the empirical best action. For encoder-prefix dynamic continuations the average empirical CE gap of the predicted choice was 0.014062; after a shared prefix it was 0.003740. For immediate STOP after the intervention those gaps were 0.019335 and 0.032258. These are retrospective finite-draw gaps, not oracle regret.

Only critic parameters were fitted on the fit sources, using 100 fixed full-batch Adam updates and the proper exponential-moment loss. Analysis sources and public-input hashes were disjoint; no validation result selected an update or checkpoint.

| Head | Analysis proper loss before | After | Aggregate CE error before | After |
|---|---:|---:|---:|---:|
| Continuing policy critic | 0.735481 | 0.734242 | -0.046767 | +0.013530 |
| Pre-STOP delivery critic | 0.731552 | 0.726992 | -0.045104 | +0.014229 |

The generator and actor remained byte-identical. These aggregate calibration improvements do not prove correct statewise action ordering or better deployed generation. The existing dynamic policy does not consume the fitted critic, so `policy_improvement_established` and `research_effect_qualified` remain false.

## Remaining interpretation limits

This is a small synthetic mechanism task under the fixed gamma-2 entropic profile. It is not natural multimodal semantic qualification, a general NDU solution, an exact global optimum, or a production latency result. Four future draws per prefix provide limited conditional tail precision. The retained negative findings do not relax any prior research gate.
