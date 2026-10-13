# Frozen Reader premise-citation prompt experiment

**Research-only intervention, no source or parameter learning.** Original
controlled events contain a four-condition, eight-question plan. The locked
Qwen Reader sees exactly the same selected original evidence, deterministically
derived schema expansions and greedy decoding limits within each pair. The
only changed input is the model-facing system instruction: it now asks for a
citation to each *used* premise, not a citation to every provided document.

This experiment addresses a precise observed source-delivery discrepancy:
the original Qwen program-supported full-path answers were correct on 8/8
authored cases; four multi-hop cases delivered both formally necessary
sources yet failed to cite both. This program-declared support set is a
privileged diagnostic, not a deployable retrieval algorithm and not independent
human entailment.

The new \`event_citation_prompt_trial.py\` commits every raw answer and native
citation request before loading the benchmark targets for scoring. It compares
**original** and **premise_chain** instructions in each unchanged \`hybrid\`,
\`organized\`, \`program_support\` and \`without_prerequisite\` arrangement.
It does not add source IDs, gold support sets, answers, relation requirements
or task-specific solutions to any prompt. The frozen Reader, tokenizer, Qwen
files, selected evidence, context budget, 64-token greedy decode and same
procedural worker are retained. The prompt-length and generation costs are
recorded as actual costs rather than assumed equal just because ceilings match.

Report separately: final strict task success, strict success with every
program-declared necessary source cited, necessary sources actually delivered,
delivered-but-uncited sources, unbound citation labels, unanswered/missing
pairs, unchanged/changed answer text and all-planned missing-result bounds.
An increased number of labels is **not** semantic entailment or an automatic
quality gain; extra/nonnecessary labels remain visible. Human-independent
sufficiency, natural-language transfer, future source families, >=99% semantic
citation precision and production qualification remain unobserved.

Run the test contracts without any model:

\`\`\`sh
PYTHONPATH=scripts/memory_cell python3 -m unittest discover \
  -s scripts/memory_cell -p 'test_event_citation_prompt_trial.py' -v
\`\`\`

The pinned hosted workflow \`hepta-memory-citation-premises-trial.yml\` then
restores the prior source plan and model inventory, performs 64 real frozen
Qwen generations with two registered prompts on four source arrangements,
runs the original executable procedure verifier, preserves failed attempts,
and ships immutable raw answers. This workflow cannot promote a candidate
or waive \`blocking-ci\`. Historical read-only replay results are not
misreported as new generations.
