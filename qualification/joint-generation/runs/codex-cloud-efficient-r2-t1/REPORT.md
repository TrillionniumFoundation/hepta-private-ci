# r2 training/validation t1 — not ready

This run actually executed in the selected configured Codex Cloud environment.
Source `32d17e85ef`, freeze commit `89d97ea727`, train exit **2**. The independent
formal test was not constructed or opened. Original r1 remains sealed.

All 15 selected models changed their encoder and both content heads; their decoder
remained fixed during adaptation (`parameter-updates.json`). All five systems
stayed within 12 billion declared operator units and 10 process-CPU seconds,
including full shared build, search, validation, critic and model exports.

Validation mean differences (not formal confidence-interval acceptance):

| Comparison | Task utility | Joint success |
|---|---:|---:|
| additive − same-weight CE anchor | +0.019041 | +0.019647 |
| NDU − additive | +0.000679 | +0.000463 |
| control − cheaper random one-view | +0.020388 | +0.021886 |

The effective reference was additive/full. Control minus that reference in
complete CPU-net utility was **−0.009623**. Its raw utility was 0.949248 versus
0.955484, with mean request CPU attribution 141212 versus 118774 ns in the fixed
batch profile. Control content training received fewer useful updates because
of its reserved critic/validation CPU and actual training overhead. These facts
remain a real first-goal blocker; positive comparisons elsewhere do not replace
this failed readiness condition. Maximum greedy drop 0.018229 passed 0.02;
budget violations were zero and decoder corruption reduced score.

The standalone native bundle generated `blue cross right` plus a real PNG from
an external handmade RGB input and instruction. Reload reproduced the model,
caption, choices and PNG hash exactly; checkpoint/cost receipts are retained.
This proves executable artifact delivery only, not benefit acceptance, batch
throughput qualification or audio/video generation.

Follow-up is restricted to training/validation and mathematical/runtime fixes.
Any revised source will receive a new immutable freeze receipt; neither r1 nor
an opened r2 test may be reused to tune it. The unchanged formal gates remain.
