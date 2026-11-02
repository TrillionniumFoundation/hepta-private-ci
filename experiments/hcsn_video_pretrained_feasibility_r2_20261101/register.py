"""Freeze official source/weights, preprocessing, estimator and data identities."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess

import numpy as np
import scipy
from PIL import __version__ as pillow_version
import torch

from . import encoder,study

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    commit=subprocess.check_output(['git','-C',str(encoder.UPSTREAM),'rev-parse','HEAD'],text=True).strip()
    assert commit=='0cc99fab046bd959578f2baac52e654746da4825'
    checkpoint=json.loads((HERE/'CHECKPOINT.json').read_text())
    assert sha(encoder.WEIGHTS)==checkpoint['sha256']=='c72c9d494ffdcb8616ce183b92393b17a8bdf1ad8b523c9ac42b0507824c214f'
    assert encoder.WEIGHTS.stat().st_size==checkpoint['bytes']==145630317
    paths=[*encoder.UPSTREAM.glob('lipreading/**/*.py'),encoder.UPSTREAM/'configs/lrw_resnet18_mstcn.json',encoder.UPSTREAM/'LICENSE',encoder.UPSTREAM/'requirements.txt',encoder.UPSTREAM/'main.py']
    source=dict(repository='https://github.com/mpc001/Lipreading_using_Temporal_Convolutional_Networks',commit=commit,tree=subprocess.check_output(['git','-C',str(encoder.UPSTREAM),'rev-parse','HEAD^{tree}'],text=True).strip(),upstream_files_sha256={str(p.relative_to(encoder.UPSTREAM)):sha(p) for p in sorted(paths)},
        checkpoint_sha256=checkpoint['sha256'],checkpoint_bytes=checkpoint['bytes'],model='Non-boundary resnet18_mstcn_video, frozen original-author LRW pretrained weights',
        original_author_model_url='https://bit.ly/3AQTFOG',pretraining_data='LRW per official repository; upstream reported LRW performance is not a CREMA result',
        license='Repository custom noncommercial research/comparative-benchmark conditions, including BBC-content restrictions; commercial/production permission not established. Preserve upstream terms and attribution. Third-party weights are not republished in this lane.',
        license_url=f'https://github.com/mpc001/Lipreading_using_Temporal_Convolutional_Networks/blob/{commit}/LICENSE',pretraining_actor_overlap='Unknown; no audited LRW-to-CREMA identity exclusion list is available',
        installed_inference_dependencies=dict(torch=torch.__version__,numpy=np.__version__,Pillow=pillow_version),minimum_code_dependency='Official model.py imports torch andnumpy; adapter addsPillow+ffmpeg/ffprobe. SciPy only fits newlogisticheads. No torchvision/torchaudio required.')
    study.write(HERE/'SOURCE_IDENTITY.json',source)
    protocol=dict(schema='hcsn-pretrained-visual-transfer.v2-offline',frozen_utc=datetime.now(timezone.utc).isoformat(),
        data='Exactly288originaltrainclips/24actors and72historicaldevelopmentclips/6actors from samepinnedCOHORT. Never oldtest/eightactorreevaluation/1019. SentenceDFA/IOM→0/1; inheritedemotionlabel is not the target.',
        upstream_commit=commit,checkpoint_sha256=checkpoint['sha256'],frozen_encoder='Original-author3Dconv+ResNet18+MS-TCN,36,361,396parameters; strict safeweights_only load, CPUevalmode, everyparameterfrozen',
        observations='Exactly1s presentationprefix frommax(audio.start,firstvideoPTS);25last-originalframes at/before origin+k/25,k1..25. Emitpixelsonlythroughlastselectedindex; B-frame compressedreferences mayrequirelaterpresentationmaterialduringofflinedecoding. Noaftercutoffpresentationpixel, duration, filename, identity or target enters encoder/head. Livecausal/streaminglatency is NOT qualified.',
        spatial='Training-onlygeometry priorfrom1007DFA_NEU frame~.7s: fixednative96square center(round(.53W),round(.54H)); RGBdecode, Pillowgray, upstream88center crop andfixed /255,(x-.421)/.165. No68landmarkaffinealignment; explicit adaptation, not upstreambenchmark reproduction.',
        descriptor='Fiveconsecutive5-frame512Dmeanbins flattened2560 plus frozen500DpretrainedTCNlogits =3060D. No descriptor/model/hyperparameter selection based on newCREMAoutcomes.',
        visual_head='C1L2logistic, fit-onlyfeaturemean/std,4sortedactorroundrobinfolds18fit/6held plus1full24actorfit; L-BFGS-Bmax1000,ftol1e-10,gtol1e-6. No neuralfinetune/earlystop.',
        audio_text='Reuse exactR1 frozenfinalA/T predictors and genuineactornestedtrainingOOF probabilities, with allsource/candidate/inputSHA guarded.',
        relation='Independently fit cleanAT_unique3basis[pA,pT,pA*pT] andAVT7nonemptymultilinearproductbasis, sameC1L2andfit-onlystandardization,L-BFGS-Bmax300,ftol1e-10,gtol1e-6, sameOOFdata/sampleweights.',
        evaluation='Afterremotesourceandcandidatefreeze: historical6actordevonly; videobinaryaccuracy; weightedAT/AVTaccuracy+Brier,6actorbootstrap10000seed20261103;100withinactorshufflesseed20261104. Frozenhead reverse-time andfirstacceptedframe-repeat diagnostics.',
        gate='Historicaldevelopment only: videoaccuracy>=.90 and AVT-AT_uniqueaccuracy actorbootstrap95lower>0. Externalpopulation, pretraining-actor exclusion, analyticcoreincrement and production/fullcost adoption remain separate.',
        cost='Meter checkpointacquisition,rawprefixfeatureextraction,classifierfits andheldoutevaluationincluding allbaseline/diagnostic work. PriorLRWpretraining,R1A/Tpreparationanddevelopmentsoftwarecost not silentlyzero. CPU is not deviceenergy.',
        runtime=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,scipy=scipy.__version__,Pillow=pillow_version,threads=1,ffmpeg=subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0]),
        pretrained_actor_overlap='unknown',external_independent_confirmation=False,all_blockers_closed=False,production_activation=False,energy_joules=None)
    study.write(HERE/'PROTOCOL.json',protocol)
    study.write(HERE/'SOURCE_FREEZE.json',dict(identity=study.identity(),frozen_utc=datetime.now(timezone.utc).isoformat(),validation_loaded=False,newheadfit_started=False))
    print(json.dumps(dict(protocol_sha256=sha(HERE/'PROTOCOL.json'),source_freeze_sha256=sha(HERE/'SOURCE_FREEZE.json'),identity=study.identity())),flush=True)


if __name__=='__main__':main()
