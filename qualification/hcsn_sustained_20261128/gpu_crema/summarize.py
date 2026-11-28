"""Aggregate the registered three-seed endpoints without mixing hardware clocks."""
import json
from pathlib import Path
import statistics

root=Path(__file__).resolve().parent
d=json.loads((root/'result.json').read_text())
rows=[]
for tag in ('updates78','time12'):
    cells=[]
    for arm in ('literal','smooth','lif','sdpa'):
        seeds=(137,311,557)
        cold=[d['cold'][f'{arm}-{s}-{tag}-normal'] for s in seeds]
        fit=[d['fits'][f'{arm}-{s}']['checkpoints'][tag] for s in seeds]
        cells.append({'arm':arm,'mean_nll':statistics.mean(x['nll'] for x in cold),
             'seed_nll':[x['nll'] for x in cold],'mean_top1':statistics.mean(x['top1'] for x in cold),
             'steps':[x['steps'] for x in fit],'mean_opt_seconds':statistics.mean(x['train_seconds'] for x in fit),
             'mean_examples':statistics.mean(x['samples'] for x in fit),
             'development_nll':statistics.mean(x['development']['nll'] for x in fit)})
    rows.append({'endpoint':tag,'neural':cells})
summary={'model_source_request':d['request_id'],'preparation_s':d['data_setup_s'],'all_cold_s':d['all_cold_s'],
      'total_wall_s':d['total_s'],'actors':d['actor_counts'],'ridge':d['cold']['ridge-normal'],
      'fits':rows,'contrasts':d['paired']}
(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
lines=['# Full-cohort CREMA-D on a private Tesla T4','',
       f"The frozen panel retained all {sum(d['split']):,} clips and the original {d['actor_counts'][0]}/{d['actor_counts'][1]}/{d['actor_counts'][2]} training, development and held-out actors. The 72 candidate label strings and four-atom financial table kept their original contents. A 4-bit summary reduced 12 video and acoustic frames to four time blocks, each with four image quadrants and four audio bands. The model receives quantized features and uses the archived actor identifier only for evaluating the split and confidence intervals.",'',
       '| Endpoint | Model | Mean cold NLL | Mean cold top-1 | Steps by seed | Mean charged optimization, s |',
       '|---|---|---:|---:|---|---:|']
for r in rows:
    for x in r['neural']:
        steps='/'.join(map(str,x['steps']))
        lines.append(f"| {r['endpoint']} | {x['arm']} | {x['mean_nll']:.5f} | {100*x['mean_top1']:.2f}% | {steps} | {x['mean_opt_seconds']:.3f} |")
lines+=['',f"The 32-coordinate ridge selected on development scored {d['cold']['ridge-normal']['nll']:.5f} NLL and {100*d['cold']['ridge-normal']['top1']:.2f}% top-1. Its train plus development search took {d['ridge']['fit_dev_s']:.3f} s. Every 78-update neural checkpoint processed all 4,984 training clips twice. The 12-second endpoint charges synchronized optimization. Setup, saving, dev evaluation and cold inference are recorded separately. The total panel time was {d['total_s']:.2f} s.",'',
       '| Endpoint | Actor-paired literal minus control NLL | Mean difference | 95% actor interval |','|---|---|---:|---:|']
for key,rec in d['paired'].items():
    if 'literal-minus-' in key:
        tag,control=key.split(':literal-minus-');lo,hi=rec['actor_cluster_ci95']
        lines.append(f"| {tag} | {control} | {rec['delta']:+.5f} | [{lo:+.5f}, {hi:+.5f}] |")
lines+=['','| Endpoint | Intervention on literal model | Mean NLL increase | Actor-cluster 95% interval |','|---|---|---:|---:|']
for key,rec in d['paired'].items():
    if ':literal:' in key:
        tag,_,cond=key.split(':');lo,hi=rec['actor_cluster_ci95']
        lines.append(f"| {tag} | {cond.split('-minus-normal')[0]} | {rec['delta']:+.5f} | [{lo:+.5f}, {hi:+.5f}] |")
lines += ['','Higher NLL indicates worse log probability for the correct class. Actor intervals condition on the realized three seeds and test cohort. Permutations preserve the marginal distribution of each modality and reassign its clips across this held-out cohort. The no-wire intervention removes the second layer’s received boundary. Existing content/residual paths remain active. The fixed prompts define a supervised 72-way audiovisual retrieval task, with no free-form caption-generation endpoint.',
          '', 'The quantized signal retains about 34.1% of raw grey-level pixel variance and 20.5% of train-standardized acoustic variance on the held-out inputs under piecewise-constant reconstruction. In original grey levels, video RMSE is 21.57. Audio RMSE is .878 standardized units. These reconstruction metrics reflect lost fine structure. Task-relevant information loss may differ.',
          '', 'The registered study contains 24 SHA-identified neural states and a selected ridge solution. The artifact bundle preserves checkpoint bytes, every original clip identity, exact primary 72-way cold logits and all per-clip intervention scores. Colab’s returned file hashes and release receipt are separate from statistical qualification.']
(root/'RESULTS.md').write_text('\n'.join(lines)+'\n')
