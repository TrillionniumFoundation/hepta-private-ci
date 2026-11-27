"""Render compact aggregate results from the independently reconstructed scores."""
import argparse
import json
from pathlib import Path
from statistics import mean

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('summary',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    raw=json.loads(a.summary.read_bytes())
    names=['forward','fp_hcsn','fp_relu8','fp_relu32','fp_flat32','fp_shuffle','bp','hybrid_bp','frozen','raw','fourier']
    out={k:raw[k] for k in ('late_rows','late_batch_sizes','model_milestones','score_entries','late_rows_duplicated_with_train_or_dev','unique_late_feature_ids','seal_sha256','same_quality_targets','bootstrap_draws')}
    out['last_rung']={k:raw['quality'][k]['24'] for k in names}
    out['contrasts_24s']={k:v for k,v in raw['paired_comparisons'].items() if k.endswith('_24')}
    out['quality_curves']={k:{r:{'mean_recall':v['mean_external_recall'],'full_pipeline_wall':mean(v['end_to_end_upper_wall'])} for r,v in ss.items()} for k,ss in raw['quality'].items()}
    a.out.write_text(json.dumps(out,indent=1,sort_keys=True)+'\n')
