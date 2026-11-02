# What the matched finite-law comparison can identify

Fix the same initial joint belief p, finite row generator Q, READ/REFRESH emissions E, reset operator, public prices, deterministic controller and tie rule. Ordinary CTMC/HMM filtering and the financial-parameterized finite cell then share the maps

\[
 p\mapsto p e^{Q\Delta},\qquad
 p\mapsto \frac{p\odot E_o}{\sum_i p_iE_{io}},\qquad
 p\mapsto pR.
\]

Assume every executed observation has positive evidence and both implementations use these exact mathematical maps. Couple both actors to the same owner world tape. Inductively, equal owned beliefs and public histories produce the same action; that action requests the same observation at the same time and quality, incurs the same fee, and produces the same successor belief. RESET retains the same declared remaining-time semantics. Thus complete actions, rewards and utilities are pathwise equal. In the frozen matched-full-law subprofile, D minus the ordinary same-law HMM reference B is exactly zero in real arithmetic, for every owner tape.

This statement applies to the declared common finite model and controller, including a misspecified common model. It does not identify a generic GRU/SSM with the exact filter, nor compare independently fitted parameters, training algorithms or costs. Those require separately matched learning and resource experiments. A new core-quality claim needs a comparison in which a declared mechanism actually differs; changing the label on identical transition/filter equations is insufficient.

FP64 exponential versus truncated positive uniformization need not be bit-identical. Small numerical differences can change a near-tie action. Such differences require the preserved precision and execution contracts; an observed last-bit action change alone is not evidence of an exclusive financial mechanism. The R20 native constructor and durable runtime provide execution and recovery evidence, while ordinary-model context calibration provides separate content-reference evidence. Neither closes analytic-core D−B or full multimodal adoption.

The theorem is a diagnostic of the matched subprofile, not a claim that general trainable continuous boundary networks cannot improve a task. Continuous laws, parameter learning, information compression, approximation and full execution cost remain distinct research questions.
