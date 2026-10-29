"use strict";
/* Fixed protocol: no heldout-based checkpoint selection or architecture tuning. */
function learnRRNetwork(N,M,C) {
  const teacher=[[.4,.35,.45,-.25,.3],[.2,-.25,.35,-.2,.25]];
  function dataset(first,count) {
    const byUnit=[[],[]],episodes=[];
    for(let seed=first;seed<first+count;seed++) {
      const net=N.diagnostic(M,C,teacher,seed);net.runUntil(4);
      const records=net.records();
      records.forEach((rs,i)=>byUnit[i].push(...rs));
      episodes.push({seed,pulses:net.pulses().length,regimes:records.map(x=>x.length)});
    }
    return {byUnit,episodes};
  }
  const train=dataset(10000,128);
  const fits=train.byUnit.map(rows=>N.fit([0,0,0,0,0],rows,
    {steps:300,learningRate:.03,l2:.01}));
  // First heldout generation occurs only after all fixed-budget fitting completes.
  const heldout=dataset(50000,128);
  const scores=heldout.byUnit.map((rows,i)=>({
    initialNllPerEpisode:N.likelihood([0,0,0,0,0],rows).loss/128,
    fittedNllPerEpisode:N.likelihood(fits[i].theta,rows).loss/128,
    teacherNllPerEpisode:N.likelihood(teacher[i],rows).loss/128,
    trainInitialNllPerEpisode:N.likelihood([0,0,0,0,0],train.byUnit[i]).loss/128,
    trainFittedNllPerEpisode:N.likelihood(fits[i].theta,train.byUnit[i]).loss/128
  }));
  return {schema:"rr-delayed-network-learning-1",protocol:"network_learning_protocol.json",
    architecture:"two finite CTMC spiking neurons with actual delayed recurrence",
    teacherWeights:teacher,learnedWeights:fits.map(x=>x.theta),scores,
    optimizer:fits.map(x=>({history:x.history,finalGradient:x.final.gradient,
      allFinite:x.theta.concat(x.final.gradient).every(Number.isFinite)})),
    trainEpisodes:train.episodes,heldoutEpisodes:heldout.episodes,
    scope:{fullPathLikelihood:true,initialResetAndCensoredIntervalsIncluded:true,
      trainableRecurrentSpikingModel:true,terminalUtilityPolicyOptimization:false,
      matchedArchitectureComparison:false,actualFutureWindow:false}};
}
if(typeof module!=="undefined")module.exports=learnRRNetwork;
if(typeof require!=="undefined"&&require.main===module)
  console.log(JSON.stringify(learnRRNetwork(require("./delayed_network.cjs"),
    require("./event_runtime.cjs"),require("./continuation_operator.cjs")),null,2));
