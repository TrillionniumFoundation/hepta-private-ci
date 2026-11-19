# Prospective fixed reward-consistency repair comparison

A fixed literal test proved an original objective incentive: under a legal two-
support command, the leading text modality's correctness derivative can be negative
because its isolated correct class credit is−.05 versus0 for consistentbothwrong.
That is not proof of the prior trained-model failure's cause. This new experiment
tests the least upward class-only repair,not a tuned reward sweep. All previous
negative runs and numerical aborts remain final andunchanged.

## Fixed new treatment and controls

Train with Rrepair=Roriginal+(.35−.3)*XOR(correcttext,correctimage), explicitly opt-in.
The increment is algebraically determined by the originalclasscredits,not selected
from validation. It leaves bothwrong,bothcorrect andallpixelquality terms unchanged.
The fixed originalreward profile is validated before correction. The change removes
the negative leading-text incentive tozero,not a promised positive gradient.

Eight cells,eachseed11/23:
1. independent-product original-reward NDU;
2. coupled original-reward NDU;
3. coupled repaired-reward additive;
4. coupled repaired-reward NDU.

Allstart from the same two previously supervised bases,300updates,batch64,lr.003,
anchor.2,rho1.5,originalAdam/normclip5,seed+9000 sampler/full-low choices,andfrozen
decoders. Allarms compute originalfourutility branches/twoanchors plus ALLFOUR
coupled originalA/N andrepairedA/N derivatives on every batch. Newreward tables
prepared exactlyonce perseed andsharedread-only. Only selectedgradient varies.
Both originalN families must exactly reproduce allfour alreadyfixed tensor digests.
This prevents repaired arms from silently using changed controls. No additional
hyperparameter,seed,allocation,precision,serving oroptimizer changes.

## Unchanged original evaluation and fixed primary

All8finals/fourcontrolchecks before validation. Same previously qualified explicit
normalized-longdouble coupled service inallarms; original numericguards unchanged.
Use ORIGINALreward for every evaluation certainty equivalent andoriginal textmass,
greedytext,jointsuccess,pixelMSE criteria. Repairedtrainingreward is NOT substituted
into the score. Allold ancillarymetrics andfull/low/all/partial reports retained.
Profile roundtrips andfixedfirstrow scalarreference tablescheckedasbefore (helper
may compute additionalgradients; allCPUcharged). Reused exploratory validation only;
noTEST ormodel selection,new checkpoints orper-row public outputs.

Primary partialmacro contrasts in BOTHseeds: repairedcoupledN−originalindependentN,
repairedcoupledN−originalcoupledN,andrepairedcoupledN−repairedcoupledA. Each must meet
unchangedfivegates:CEgain>=.005,textmass/greedytext/jointsuccess no regression within
1e-10,pixelMSEincrease<=1e-10. Allsixprimarycontrasts mustpass. OriginalcoupledN−
independentN negativecontrol reported too. InternalN>A alone cannot establish overall
improvement. No jointMAP substitution,reward-based gate relaxation orposthoc cellchoice.

## Fixed accounting and termination

One child,existing syntheticlock,CPU0/singlethread,30CPU90wall512MiB4MiB,fullwait4,
no retry/extensions. Both12numericqualification and4incentive tests run before model
access andare charged. Twoexactbasepayloads only; allsource/qualification/control
metadata frozen. Expected2restores8clones2400updates7220forwards471120rows,
2decoderobservations24images,2rewardrepairtablecalls3456entries,
9600attempted/completedcoupledgradientcalls614400rows,20servingcalls10320tables/
1486080entries20640CDFmarginalchecks20scalarreferencechecks10profile roundtrips.
Equal plannedwork is not identical actualspend; per-arm/wholechildcosts retained.

Any numericdomainexception abortswholecampaign. Exactlyone wholebatch aggregate
forward-law diagnostic attempt is countedthenre-raised; no rowmask orlaterupdate.
Successfulrun diagnosticcounters0. Trainingdomain aggregates include allfour
auxiliarycalls. Prior qualification,mechanism,diagnosis,oldnegative runs andbase
preparation remain separatelychargedhistory; source/review/supervisortailsadditional.
