# Unique color × joint-spatial source prior — literal qualification

SOURCE ONLY. Exactlyonefixed partition:attrs(k)=(k//4,k%4), factor sizes3 and4.
No generalpartition selector, axis/split/hyperparameter sweep or tunedmixture.
This is a post-result representation hypothesis following failed original gates,
not a retrospectively prespecified confirmation or a claim the oldprior was a bug.
The renderer source constructs a mask from(shape,position), then assigns a color
channel. That source recipe motivates preserving jointshape-position while separating
color, but DOES NOT prove posteriorindependence, improvegeneration or constitute a
new statisticalfinding. Renderer/data.py is NOT imported or allowlisted in this
qualification; onlyhandcodedcanonical label schema is consumed.

## Model and mathematical boundary
Same202->32->two12rawlogits/192pixel learneddecoder andcommandblind source mask,
exacttensorcount andinitialtensors. Newprofile/mode/schema is distinct fromdirect
andfull3x2x2. No newlabels: sourceclass already determinesbothattributes; stronger
semanticstructure prior is explicit. Equalparams notsamefunctionclass/predictions.
Rawpositive normalized p yields color mC andFOUR-statejointspatial mS;
q(c,s)=mC(c)mS(s), explicitlynormalized. Color andentirejointspatial marginals are
preserved. Shape-position dependence survives, unlike full3x2x2, but color-spatial
correlations arediscarded. Outputdegrees5 versusfullfactor4 versusdirect11;
no claim ofcapacityexpansion ordecodedsemantic correctness.

Bothnormalizations and strictpositive/finite/noepsilon/underflow refusal mirror
qualifiedfullfactor. Fixednormalization/marginalclosure tolerance1e-12, strictouter
canonicaltuple12/innerexacttuple2/exactPythonintegers; float/bool/listaliases rejected.
Incomingvirtualfactorlogitgrad g requiresfinite shape androw-sumabs<=1e-12.
h=g-qsum(g) retains finiteproductnormalization residuals;
G[a,v]=sum_{k:attr_a(k)=v}h_k;
chain_k=sum_{a in color,spatial}(p_k/m[a,attr_a(k)])G[a,attr_a(k)];
rawlogitgrad=chain-p sum(chain). Boundedp/m, no standalone1/m. Upstreamalreadymean,
no extrabatchdivision. Exactanalytic real-valuedchain, not roundingderivative.
Ordinaryanchor passes throughchain unchanged aspartofupstream selectedobjective.
Qualifiedfullfactor helpers/tests are immutable and retained asreference.

ColorSpatialSourceModel overrides forward/gradients only; each callsraw
JointModel._forward once with inheritedinputmask. No recursive/doubleprojection.
SupervisedCE andA+ordinaryanchor route through projectedheads andanalyticpullback;
decoder unchanged. Originalsupervised loss's1e-300 floor convention retained,
FDinteriorfixtures avoidits nondifferentiableextreme. Cleanclone retainsmode/tensors,
newprofilekey-bounddigest, checkpointsdisabledbeforeI/O. Projection/pullback/raw
counts recorded; sameparams notartifactcompatibility. No target/renderer at inference.
Actual learneddecoder must still beobserved beforeoriginaltransport/coupling/
FITcalibration. Later science will requirebothobservedmaps canonical0..11 for EVERY
representationbase, recordmaps andwholeabortotherwise; no remap/relabel/selection.

## Seventeen literal tests, no scientificmodels/data
OldSource5 plusqualifiedfullfactor6 BYTE EXACT, and6color-spatialtests:
1 normalized/color+FOURspatialmarginalpreservation/productfixedpoint/idempotence;
  explicitcolor(.2,.3,.5) xspatial(.4,.1,.1,.4) isCSfixed whilefullfactor changes
  jointshape-position dependence; correlatedcolor-spatial handpolicy changesjoint.
2 full48rawlogitcoordinates FD forfixedzero-sumvirtualcotangent.
3 bothheads partialtransportA+.2ordinaryanchor FD8coordinates plusallkeep/fullset.
4 actualmodel encoder/bias/text/imageparams FD7supervisedCE +7fullAanchor.
5 exacttensorinit/count, commandblind/inputimmutable, decoderimmutable, clone/
  mode/digest/checkpoint, one rawforward percall andprojection/pullbackwork.
6 strictcanonicaltype/mode/shape/nonfinite/rawzero/probgrad/mixedoldprofile and
  extremestrictpositive-productunderflow rejection, noepsilon/repair.
FixedFDstep1e-6/helper3e-8/model2e-7 andalgebraic2e-15; no bitwiseclaims for
nonzero-rho or reorderednormalization. Toyinitializations andliteralupdates real,
counted separately/includedwholeCPU;0restores/scientificmodels/datasetrows.

5CPU/30wall/512MiB/4MiB,CPU0singlethread, existingnonblockingoriginallock;
fullwait4/no retry/no descendants/network. Exactsourceallowlist excludesdata.py,
renderer andpayloads. Imports/tests/hashes/toymodelupdates/outputinsidechild;
source/review/supervisortailadditional/notzero. ProducerSOURCE/ASTonly, noexecution.
Independentstaticreview andseparateonce-run admission required.

## Future science outline NOT included
DirectA/fullfactorA/colorSpatialA xfourfixedfold/seedcells=12ownbases/12clones.
Same300decoder/500sourceCE/300static64adapt/oldFITcalibration/knownnoise/oldgates.
Allarms compute3laws+3paramgradaux, selectone; discardedothergradients computational
work, notvalidotherobjectiveestimates. Exacthistoricaldirect ANDfullfactor8bases/
8models/fullmetrics/profile/datasets. Additionalallprep/aux cost explicit; prospective
60CPU180wall budget requires its ownfreeze/review/launch. No newNDU orspeedclaim.

## v2 fixed forward-algebra fixture, no added test or experiment
For the SAME raw p, setting shape ORposition makes transportedCS(p) equal to
transportedfullfactor(p): summing thejointspatial factor over the setaxis leaves
the same remainingaxis marginal. Allsuchcommands checked on twoliteralpolicies
with2e-15 tolerance. Color-only command preserves the correlated(.4,.1,.1,.4)
spatialjoint underCS butnotfullfactor, giving a fixed differencewitness. This is
forwardalgebra, not an observedcause; trainingchangesrawp, so it doesNOT imply
empiricaldifferences can occur onlyoncolor-only commands. Laterdescriptive strata
may be preregistered withoutnewmodelcalls/gates; no rescue ofwholepartialgate.
Unexecutedv1 retainedimmutable; onlysamepartialtestextended, still17total.
