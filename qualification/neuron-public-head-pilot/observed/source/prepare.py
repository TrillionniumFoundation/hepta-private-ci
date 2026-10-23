import csv, hashlib, json, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
P=Path(__file__).resolve().parent
H=lambda b:hashlib.sha256(b).hexdigest()
def save(name,x):
    p=P/name;p.write_text(json.dumps(x,indent=2,sort_keys=True)+'\n');return H(p.read_bytes())
assert H((P/'ag_news_csv.tar.gz').read_bytes())=='4e2fc37d369e6e317a8b62d0d2f11d379f8c3dde60c07c35a46b069a246498ad'
allgroups={}; stats={}
for split in ['train','test']:
    groups=defaultdict(list)
    with (P/f'{split}.csv').open(newline='') as f:
        for i,row in enumerate(csv.reader(f)):
            assert len(row)==3 and row[0] in ['1','2','3','4']
            text=' '.join(unicodedata.normalize('NFKC',row[1]+'\n'+row[2]).split())
            key=H(text.casefold().encode())
            groups[key].append({'source_split':split,'row_index_zero_based':i,'label':int(row[0])-1,'text':text,'normalized_text_sha256':H(text.encode()),'group_sha256':key})
    allgroups[split]=groups
    stats[split]={'raw_rows':sum(map(len,groups.values())),'unique_groups':len(groups),'duplicate_rows':sum(len(v)-1 for v in groups.values()),'conflicting_groups':sum(len({r['label'] for r in v})>1 for v in groups.values())}
cross=set(allgroups['train'])&set(allgroups['test']);stats['cross_official_split_groups_removed_from_both']=len(cross)
selected={}
for source,parts in [('train',[('head_train',320),('temperature',160),('conformal',160)]),('test',[('test',320)])]:
    candidates=[v[0] for k,v in allgroups[source].items() if k not in cross and len({r['label'] for r in v})==1]
    candidates.sort(key=lambda r:H(('hepta-public-head-pilot-v1|'+source+'|'+r['group_sha256']).encode()))
    stats[source]['eligible_unique_groups']=len(candidates)
    offset=0
    for name,n in parts:
        selected[name]=candidates[offset:offset+n];offset+=n
        assert len(selected[name])==n
        stats['selected_'+name]={'count':n,'class_counts':dict(sorted(Counter(r['label'] for r in selected[name]).items()))}
assert len(set(r['group_sha256'] for rows in selected.values() for r in rows))==960
assert set(r['label'] for r in selected['head_train'])==set(range(4))
rawhash=save('selected-local-only.json',selected)
manifesthash=save('rows.json',{split:[{k:v for k,v in r.items() if k!='text'} for r in rows] for split,rows in selected.items()})
save('split-audit.json',stats)
plan={
 'profile':'harrier-native-public-agnews-head-calibration-pilot-v1',
 'frozen_before_feature_extraction_and_fitting':True,
 'dataset':{'original_archive_sha256':H((P/'ag_news_csv.tar.gz').read_bytes()),'source':'https://drive.google.com/uc?export=download&id=0Bz8a_Dbh9QhbUDNpeUdjb0wxRms','checksum_source':'https://raw.githubusercontent.com/tensorflow/datasets/master/tensorflow_datasets/datasets/ag_news_subset/checksums.tsv','train_csv_sha256':H((P/'train.csv').read_bytes()),'test_csv_sha256':H((P/'test.csv').read_bytes()),'license_note':'Original README permits academic research and non-commercial use. Raw text stays local. No commercial or redistribution permission inferred.'},
 'rows_sha256':manifesthash,'selected_local_sha256':rawhash,'splits':{k:len(v) for k,v in selected.items()},
 'selection':'NFKC and collapse whitespace of title plus description; casefolded normalized full-text SHA256 group. Remove all official train/test overlap groups from both pools and label-conflict groups. Choose first row of each remaining group. Globally sort SHA256(salt|officialsplit|group), not label-stratified. First 320/next160/next160 training groups; first320 official-test groups. Salt hepta-public-head-pilot-v1.',
 'encoder':{'repository':'microsoft/harrier-oss-v1-270m','revision':'31de22b673913c7d658c0f03f792d77c2dcf8ebd','pooling':'native last nonpadding token then L2 normalization','profile':'unprompted document mode; not claim optimal classification prompting','prompt':'','max_tokens':256,'dtype':'float32','device':'cpu','threads':2,'batch_size':8,'feature_width':640,'reuse_same_features_for_every_head':True},
 'heads':{'centroid':'normalize each class mean of normalized features; score cosine','logistic':{'init':'zero W and b','objective':'mean cross entropy + 0.001/2 * sum(W**2), bias unpenalized','optimizer':'Adam','lr':0.1,'steps':200,'seed':20261023,'dtype':'float64','selection':'primary adaptation comparator against centroid; no test-driven tuning'},'ridge':{'status':'secondary','objective':'centered one-hot least squares with lambda 1.0; unpenalized intercept','lambda':1.0,'dtype':'float64'}},
 'temperature':{'separate_split':'temperature','objective':'mean cross entropy of logits / exp(t)','algorithm':'deterministic 100-iteration golden-section search in log-temperature [-5,5]; include raw T=1 and endpoints as candidates','boundary_status':'record near-boundary optimum; no automatic repair','fits_for':['centroid','logistic','ridge'],'top1_invariance_required':True},
 'conformal':{'alpha':0.1,'split':'conformal','k':'ceil((n+1)*(1-alpha)); kth order statistic or infinity if k>n','LAC':'primary; score=1-p_y, include if score<=q','APS':'secondary; stable descending probability, class-index tie break; cumulative probability through candidate minus U*p_candidate; include if score<=q','random_uniforms':'PCG64 seed 20261024 for calibration and 20261025 for test; one U per row shared across candidate labels; identical uniforms across heads/raw-vs-TS','empty_sets_allowed':True,'single_label_rule':'accept iff set size=1, otherwise abstain'},
 'metrics':{'classification':['accuracy','NLL','multiclass Brier sum of squared class residuals','ECE 10 equal-width confidence bins'],'sets':['empirical coverage','mean set size','empty fraction','singleton acceptance','singleton conditional error and Wilson 95% interval','per-class coverage with denominators'],'paired_bootstrap':{'replicates':5000,'seed':20261026,'interval':'percentile 2.5%,97.5%; descriptive finite-sample uncertainty, not distribution-shift guarantee'}},
 'falsifiable_primary_hypotheses':{'adaptation':'logistic accuracy minus centroid accuracy >0 and paired 95% lower bound >0; point <=0 means no demonstrated benefit, otherwise uncertain','calibration':'logistic raw NLL minus TS NLL >0 and paired 95% lower bound >0; point <=0 means no demonstrated benefit, otherwise uncertain','pilot_utility':'logistic TS LAC singleton acceptance >=0.5 AND Wilson95 upper selective-error bound <=0.1; not qualification even if satisfied'},
 'invalidation':['overlapping normalized groups','nonfinite or wrong-shape features','native pooling parity failure','snapshot drift observed at guarded checkpoints','encoder modified','test labels influence any fitting or hyperparameter','positive scalar TS changes top1'],
 'limits':['960 historical sampled public texts; one fixed split; not full AG News score','exact full-text dedup cannot remove story/source or semantic overlap','training contamination unknown','official train/test exchangeability not guaranteed','90% marginal prediction-set coverage is not 90% accepted-label accuracy and not OOD guarantee','no future-family efficacy, original five-model parity, production resource/CAS/signature closure']}
save('plan.json',plan)
print(json.dumps({'plan_sha256':H((P/'plan.json').read_bytes()),'rows_sha256':manifesthash,'audit':stats},indent=2))
