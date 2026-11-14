from pathlib import Path
import shutil, subprocess
base=Path('/mnt/data/hcsn_fullspeed_20261030')
out=base/'repo_overlay'
(out/'experiments/hcsn_hx_unified_v3').mkdir(parents=True,exist_ok=True)
(out/'experiments/hcsn_distributional_v2').mkdir(parents=True,exist_ok=True)
(out/'docs/research').mkdir(parents=True,exist_ok=True)

moves=[
 ('p0_discount_loss/independent_discount_loss.py', 'experiments/hcsn_hx_unified_v3/independent_discount_loss_reference.py',[]),
 ('p0_discount_loss/test_discount_loss.py','experiments/hcsn_hx_unified_v3/test_independent_discount_loss_reference.py',[('from .independent_discount_loss import','from .independent_discount_loss_reference import')]),
 ('p1_mechanism_gate/paired_gate.py','experiments/hcsn_hx_unified_v3/p1_paired_mechanism_gate.py',[]),
 ('p1_mechanism_gate/test_paired_gate.py','experiments/hcsn_hx_unified_v3/test_p1_paired_mechanism_gate.py',[('from .paired_gate import','from .p1_paired_mechanism_gate import')]),
 ('p2_renewal_adversarial/test_piecewise_ctmc.py','experiments/hcsn_distributional_v2/test_piecewise_ctmc_independent.py',[]),
 ('p0_p5_gatebook/admission.py','experiments/hcsn_hx_unified_v3/p0_p5_evidence_gatebook.py',[]),
 ('p0_p5_gatebook/test_admission.py','experiments/hcsn_hx_unified_v3/test_p0_p5_evidence_gatebook.py',[('from .admission import','from .p0_p5_evidence_gatebook import')]),
]
for src,dst,repls in moves:
    s=(base/src).read_text()
    for a,b in repls:s=s.replace(a,b)
    (out/dst).write_text(s)

(out/'docs/research/HCSN_LOCAL_WAVE_20261030.md').write_text('''# HCSN P0–P5 offline research delivery (2026-10-30 local / 2026-10-31 UTC)

Source repository: `TrillionniumFoundation/hepta-private-ci`.

**Not merged. Not pushed. Not deployed.** GitHub connector returned 403 (account suspended) for repository metadata, main branch and PR metadata. Consequently no exact latest main SHA, head/base comparison, Actions result or production qualification could be established during this turn. These files are an *additive research patch only*; check for path/algorithm conflicts against exact current source before applying.

## Additive implementation

- **P0**: finite-horizon Brownian constant-barrier first-passage `(F,G,L)` with `L = E[(1-exp(-q*tau)) 1(tau<=T)]` calculated by positive hitting-time density, independent reflection crosscheck and float32 output refusal when positive loss collapses. Python mpmath quadrature is not a rigorous interval/error certificate; scalar frozen-coefficient Brownian is not full He–Xiong coupled HX equilibrium.
- **P1**: four-panel paired mechanism statistical/metadata diagnostic. Exact two-sided sign-flips (10–16 paired seeds), Holm p adjustment and Bonferroni lower bound with explicit practical magnitude, matched actual trainable params, value/slope, input batches, training CPU and full worker CPU/Joule accounting. Tests use synthetic examples only; no new real-seed effect claimed, no proof of preregistration.
- **P2**: independently compare varying-rate two-state renewal transitions and expected event counts against matrix exponential over three switched segments; checks semigroup and repeated-fire count. Model is CTMC, not full HCSN dynamic boundary or long-recall quality.
- **P3**: no new four-modal encoder was trained. Existing local 22-test *structural source-integrity* suite replayed separately in bundle, not copied into this additive patch.
- **P4/P5**: deny-by-default offline evidence ledger explicitly demands four hardware scales, direct energy measurement, and all upstream scientific gates; it NEVER grants production authority. Rust/GPU/4096 Cell run and equal-quality net benefit are not evidenced.

## Additive research test commands (when applied to compatible existing research tree)

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_independent_discount_loss_reference
python -m unittest -v experiments.hcsn_hx_unified_v3.test_p1_paired_mechanism_gate
python -m unittest -v experiments.hcsn_distributional_v2.test_piecewise_ctmc_independent
python -m unittest -v experiments.hcsn_hx_unified_v3.test_p0_p5_evidence_gatebook
```

All test outcomes must be rerun after real integration; no existing frozen negative content results may be relabeled or modified. Current known mechanism and content acceptance remain negative per prior research PR #4255 / #4362. Keep draft research and `DENY_ALL`.
''',encoding='utf-8')
print('wrote overlay',len(moves)+1,'files')
