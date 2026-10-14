# Completed frozen-answer review preparation and content decomposition

Date: 2026-10-14. PR #1697. Executed source:
a56774891df6236dd8a6aa83a7eaa156c47ee277.
Tree:72c6c38e9f792cc67f8d3425eae8fc8227271580.
Run38510513152 / job115677688128 completed SUCCESS. Final job status, complete
decoded logs and all three output artifact records were inspected. This result
note does not change the executed implementation, run an optimizer, issue a
human review or select a serving model.

## 1. Actual completed work

All36 new answer-review integrity/decomposition tests passed, as did31 inherited
SELECT-inventory tests and25 source-time input tests:92 passing invocations,
92 distinct identities,zero skips. Compilation passed. This stdlib-only scoped
run did not rerun the prior387-test neural suite, train models or assert full
repository/Rust/target-device acceptance.

Only the existing completed SELECT result archive11863981474 was downloaded.
Its original external SHA was checked, then all498 listed members (499 files
including SHA256SUMS) passed the existing verification routine before extraction.
Source identity, original plan, inventory/raw hashes, all three arm-level raw
seals and exact input/answer joins were checked. No archived code was imported.

36 original slots are retained:33 historical successful answers plus3 original
unavailable donor slots. They became11 unique question/evidence contexts and29
unique question/evidence/answer review items. Four identical answer instances
were deduplicated for review, not removed from the model-level denominators.
There were ZERO new model calls, teacher-forcing calls or optimizer updates.
Packaging/verification and tests still have recorded process cost.

The evidence-first artifact contains sources and blank sufficiency forms only.
The answer-second artifact adds unchanged answers and blank quality forms.
The separate custodian artifact contains assignment identities, diagnostics and
raw inspection; reviewers meant to be masked must not receive it or the full
job log. Three uploaded artifacts are not a repository access-control boundary.
No external reviewers or filled reviews exist in this run:reviews_received=0.
Masking/quote checks are not proof of independent humans or semantic entailment.

Packet SHA:
9f5d800c688db6dd343309b64c80261d6e8ced2035e3c2169453db16d4f4989d.
Original immutable raw-generation SHA:
df6b77484d73ceda023e946d791d8244d1777506eeaf211a5c450a7dc8280adf.

## 2. New descriptive decomposition of existing scores

The statistic is I=m_own-m_donor. Relative to the same frozen Reader, the observed
changes on the SAME3 scoreable SELECT recipient/donor pairs are:

| Candidate | Own answer logp change | Own rival logp change | Own margin change | Donor margin change | I change |
| --- | ---: | ---: | ---: | ---: | ---: |
| Aligned8, task mean |2.532798|-0.932102|3.464900|0.652818|2.812081|
| Shuffled8, task mean |1.540665|0.796714|0.743950|0.840690|-0.096739|
| Aligned8, family macro |2.640855|-0.814149|3.455004|0.552078|2.902925|
| Shuffled8, family macro |1.617836|1.040735|0.577101|0.976614|-0.399512|

Both candidates prefer the reference over the rival under original sources on
all3 scored comparisons; the frozen model already does too. Aligned8 improves
own-context margins by4.604584,2.364799,3.425316 on the three comparisons, so the
larger interaction is NOT exclusively an effect created on the donor side.
Its own-reference mean score increases while its own-context rival mean decreases.
Shuffled8 increases both means, distinguishing the two saved candidates on this
narrow diagnostic. These are mean-token log scores, not correctness probabilities.
The fourth planned recipient remains unscored. The means condition on3 cases
and two source families; no confidence interval, significance or universal
transfer claim. This decomposition is explicitly post hoc and preserves the
old preregistered readout rather than replacing it.

## 3. Direct raw-output inspection: useful answers AND a regression

The following observations were made by the current assistant after reading the
model identities and all supplied source texts in the custodian log. They are
NOT blinded, independent human ratings and were NOT filled into reviewer forms,
converted into a benchmark accuracy, or used to change any model/threshold.
They show why neither zero exact match nor a positive likelihood difference is
sufficient to judge generated answers.

- conv-42/q139 asks which themes Joanna's book explores. The delivered source
  explicitly names loss, redemption and forgiveness. Aligned8 outputs
  `loss, redemption, forgiveness`, which directly reproduces those themes.
  Frozen output is truncated copied JSON; shuffled8 outputs `Joanna's new book`
  rather than identifying the requested themes. None of the aligned output's
  words provide the required formatted source citation, so format remains a
  separate missing capability.
- conv-42/q188 asks what Nate is creating for YouTube. The source says he is
  creating gaming content. Aligned8 outputs `creating gaming content for YouTube`,
  directly consistent with that source. Frozen calls it a video game; shuffled8
  outputs `a gaming video game`. Creating gaming videos/content is not necessarily
  creating a game. This is a source-level observation, not independent scoring.
- conv-44/q49 asks what Audrey views her pets as. The sources explicitly say
  pets are family and little family. Frozen outputs `Audrey views her pets as
  family.` Aligned8 outputs `her pets`, which does not answer the requested
  relationship; shuffled8 says flowers. Thus the aligned likelihood improvement
  coexists with an apparent generation regression on a clear original-source
  question. A better mean content interaction is not uniform answer improvement.
- conv-44/q155 has no reference answer in the old benchmark readout. It asks
  about a drink, whereas the delivered source reports a sushi restaurant visit.
  Aligned8 outputs `sushi\n[not observed pixels]`. The provided source does not
  establish the requested drink. The question, missing reference and generated
  bytes remain unchanged; no target repair or filtering was performed.

Irrelevant NONEMPTY evidence also remains an explicit failure mode in these
observed cases. For q139, the donor source is about a backyard dog play area,
while aligned8 outputs `"Sesame Street"`. For q188, the donor source is about
Audrey attending a dog-training class, while the unchanged question asks about
Nate's YouTube creation; aligned8 outputs `a positive reinforcement training
class`. These responses do not establish an answer to the recipient question
from its supplied donor text. Both trained models still output the prescribed
refusal for all four EMPTY inputs. The next distinction is relevance to the
question, not merely nonemptiness or finding a phrase that can be copied.

No complete semantic score is reported from this assistant inspection. All33
answers and their exact sources remain available to the separately authorized
reviewers. External evidence-first judgments are needed to quantify grounded
answering and appropriate abstention on nonempty insufficient inputs, alongside
future independent task families. Existing Reader qualification is not bypassed.

## 4. Output artifacts, separate custody and evidence limits

-11869457851:hepta-answer-review-custodian-and-checks,51,627 bytes,21 files.
 SHA256:0b55ddf2b52b21859695aadf4d0229f666c1d7edb18f6862fb751af8967ff5b8.
-11869647394:hepta-answer-review-1-evidence-first,3,801 bytes,3 files.
 SHA256:02faa90c99fda76ce17960388c2e6354b835aa68f74a857e7b238e2fa58ce98a.
-11869647396:hepta-answer-review-2-answer-second,6,471 bytes,3 files.
 SHA256:6a75052d7bbd403e051f5aa0ca6c684d449b9abf47a78e514f953bcdd5b19a27.

Sizes/hashes above are GitHub output metadata and decoded job observations.
The actual hosted run verified the INPUT archive/members. Local container and
Python failed with ClientError, so this increment does not claim local rehashing
of these NEW output ZIPs. All source and check logs are retained in custodian
outputs. The random assignment secret was not exported; the exact assignment
commitment prevents later grade-to-arm remapping without breaking packet pins.

Formal semantic reviews received:0. New fitting:0. New independent tasks:0.
Projection qualification remains failed under original tolerances and is not
used here. Group/NDU and multimodal/split have no new performance claim. No
main/CURRENT/serving change, force push or external gate modification occurred.
The next independent adjudication and future-task evaluation are still separate
from this completed preparation/diagnostic. Five formal experiments are not yet
complete; this result makes the final-answer bottleneck concrete rather than
replacing it with additional likelihood proxies.
