# TypeSafe System One models and Jev — technical reference

Technical background for `daf-jev`: what System One models are, how Jev is built and
trained, how calibration works, and where the vendor's claims have (and have not) been
corroborated. This page is documentation, not a benchmark; every factual claim carries a
source link and its access date.

> **Canonical cite keys.** The BibTeX entries in `manuscript/references.bib` use the keys
> referenced throughout this page (`typesafe2026systemone`, `typesafe2026systemoneconcept`,
> `typesafe2026apidocs`, `typesafe2026confidence`, `typesafe2026patterns`, `register2026jev`,
> `orcarouter2026jev`, `elsolitario2026jev`, …); see the crosswalk table at the bottom.

**Provenance legend.**

- **Primary** = authored or hosted by TypeSafe (the launch post, `docs.typesafe.ai`, the
  team page). Docs claims are verified against the local 108-page snapshot in
  `docs/reference/` — **snapshot id `b79c9cd6008489f1`**, scraped 2026-09-16T21:19:06Z;
  each link points to the live page, and the local path is given in the crosswalk.
- **Third-party-reported** = claim found only in independent coverage or analysis;
  flagged inline. Independently measured results (e.g. Every's hands-on tests) are marked
  as such.
- **All sources accessed 2026-09-16**; each citation below names that access date.

---

## 1. What a System One model is

System One models are a class of AI models built to make fast, structured decisions that
software can use directly: the model evaluates a *state* and returns typed answers and
probabilities ([TypeSafe docs — System One](https://docs.typesafe.ai/concepts/system-one.md), 2026-09-16).
Like an LLM, a System One model understands natural-language input; unlike an LLM it
returns typed decisions and probability distributions rather than generated text — no
replies, no code, no explanations of its reasoning
([System One docs](https://docs.typesafe.ai/concepts/system-one.md), 2026-09-16).
TypeSafe calls the design goal "Machine Native Intelligence": AI with software-like
properties — structure, reliability, observability, testability, speed, consistency, low
cost ([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16).

Jev is TypeSafe's flagship model and the first System One model
([System One docs](https://docs.typesafe.ai/concepts/system-one.md), 2026-09-16).
System One models are trained for calibrated decisions: probabilities are optimized
against outcomes to reflect uncertainty, and calibration holds across *groups* of
predictions, not as a guarantee about any single answer
([System One docs](https://docs.typesafe.ai/concepts/system-one.md), 2026-09-16).

Jev opened in early access on **September 15, 2026** (launch post dateline;
[TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16;
independently corroborated by [El Solitario, 2026-09-16](https://elsolitario.org/en/2026/09/16/typesafe-ai-jev-structured-decision-model/),
[The Register, 2026-09-16](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711),
and [Every, 2026-09-15](https://every.to/also-true-for-humans/mini-vibe-check-typesafe-s-jev-judged-everything-i-ve-written-in-0-7-seconds);
the blog page's HTML frontmatter carries a later "Sep 16, 2026 10:07 PM UTC" publish timestamp).

## 2. Architecture: a specialized stack with a parallel sampler

TypeSafe describes building "a new stack entirely focused on automation: with a new model
architecture, parallel sampler for maximum efficiency, and training method we call
Reinforcement Learning for Calibrated Decisions (RLCD)"
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).

The sampler is the load-bearing difference. Where an LLM samples *sequentially* — one
token at a time, each conditioned on the last — the System One architecture "generates
all outputs in a single query," which TypeSafe describes as "incredibly efficient and
hardware-aware" ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
The Register explains the contrast the same way: GPT-5.6 Terra predicts the next token in
a sequence and thus operates sequentially, while the System One architecture returns all
outputs to a query at once
([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711), 2026-09-16).
At the question level, all three question types can be mixed in one API call; every
question is evaluated "in parallel and in isolation against the same *state* in one go";
adding questions "barely changes the response time," and independent evaluation means
adding questions does not create context-rot
([TypeSafe docs — Introduction](https://docs.typesafe.ai/introduction.md), 2026-09-16).

**Latency envelope.** End-to-end response time is **70–500 ms** for TypeSafe, which the
company frames as 40x–200x faster "for the same levels of frontier intelligence for
System One shaped queries"; it contrasts this with frontier LLMs at **3–329 seconds**
end-to-end (a figure TypeSafe cites from the third-party benchmark
[llm-benchmarks.diegoromero.es](https://llm-benchmarks.diegoromero.es/))
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
The 70–500 ms envelope and the 40x–200x claim are independently repeated by
[The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711)
(2026-09-16) and [The Decoder](https://the-decoder.com/former-openai-researcher-builds-an-ai-model-that-judges-options-instead-of-writing-text/) (2026-09-16).
TypeSafe's recorded side-by-side demo shows Jev answering in 0.114 s against 8.566 s for
GPT-5.6 Terra ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16;
corroborated by The Register, 2026-09-16).

**Efficiency claim.** TypeSafe claims Jev "achieves similar levels of intelligence on
System One tasks compared to existing LLMs, while being **two orders of magnitude faster
and more efficient**" ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
Its homepage headline numbers — 193.6x faster, 444.6x cheaper — come from its workflow
evals, and TypeSafe itself cautions these "are on the higher end of real world gains"
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).

**Cost.** Input tokens cost **$0.042 / MTok ($42 per billion tokens)** and output tokens
are free — "too cheap to meter" — versus LLM input pricing of $0.20–$10 / MTok with
output typically ~5x the input price
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
The Register independently repeats the $0.042 / free-output price and adds comparisons:
GPT-5.6 Terra at $2.00 / $12.00 per MTok, and Jev 238x cheaper than Fable 5.1
([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711), 2026-09-16).
Third-party-reported: the free output is mechanically explained by the absence of
autoregressive decoding — there are no output tokens to meter
([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16).
TypeSafe itself flags the caveats: published evals were run from the team's West-Coast
laptops, and it "can't prove it isn't subsidized"
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).

**Request budget and cardinality.** The number of questions in one request is limited
only by a shared token budget: "around 32,000 tokens, roughly 150,000 characters of
English text" ([TypeSafe docs — Primitives](https://docs.typesafe.ai/primitives.md), 2026-09-16).
Choice cardinality is capped at 255; for higher-cardinality choices TypeSafe uses a
two-stage system of scoring independently then making an explicit choice
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).

**Hallucination / type safety.** TypeSafe claims Jev "can't hallucinate" because possible
outputs are defined in advance and "the model never makes type errors"; it argues a
counter-example would be easy to falsify but that avoiding type errors is "mathematically
impossible" to violate ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
Independent writeups uniformly narrow the claim: the guarantee is structural (outputs
outside the declared answer space cannot occur) and says nothing about being *correct* —
a schema-valid answer can still be wrong
([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711),
[The Decoder](https://the-decoder.com/former-openai-researcher-builds-an-ai-model-that-judges-options-instead-of-writing-text/),
[OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), all 2026-09-16).

## 3. Training: RLCD vs RLHF/RLVR

TypeSafe positions RLCD as a third post-training approach alongside two established ones
([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16;
[TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16):

| Approach | Optimizes for | Typical result |
| --- | --- | --- |
| **RLHF** — Reinforcement Learning from Human Feedback | Responses human raters prefer | Chatbots (InstructGPT, ChatGPT) |
| **RLVR** — Reinforcement Learning with Verifiable Rewards | Outputs that can be programmatically verified | Reasoning models (strong at e.g. math, but slower and more expensive) |
| **RLCD** — Reinforcement Learning for Calibrated Decisions | **Calibrated decisions: answers with epistemically honest probabilities** on System One tasks | Decision models (Jev) |

RLCD's output contract: the model does not generate text; it returns decisions and
probabilities, with higher probability corresponding to a greater chance the answer is
correct ([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16).
The distinction from RLHF/RLVR is that RLCD optimizes *calibration / epistemic honesty*,
not just correctness or preference: TypeSafe argues RLHF "can also reward sycophancy and
confident-sounding hallucinations," and that preference optimization causes **mode
dropping** — the model narrows its output distribution toward the preferred style
([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16).
Third-party-reported: the RLCD acronym was expanded inconsistently by early coverage,
and the implementation details (reward/scoring rule, calibration measurement) are
unpublished ([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16).
Third-party-reported: El Solitario explains the objective as "if Jev says 87% confidence
in a category, that 87% should match the actual accuracy rate"
([El Solitario](https://elsolitario.org/en/2026/09/16/typesafe-ai-jev-structured-decision-model/), 2026-09-16).

## 4. Calibration methodology

**Definition.** Across many predictions from a well-calibrated model: outcomes assigned
probability 0.2 occur about 20% of the time, 0.8 about 80%, 1.0 100% — group rates, not
per-answer guarantees
([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16).

**Confidence bands.** Every Choice and Score answer carries a `probabilities` distribution
plus a `confidence` in 0–1 derived from it (a convenience statistic; Noul answers do not
carry one) ([Confidence docs](https://docs.typesafe.ai/confidence.md), 2026-09-16).
The recommended pattern divides confidence into three bands with different behavior —
**high: act automatically; medium: proceed with caution / confirm / flag; low: do not
act, route to a human or another system**
([Confidence docs](https://docs.typesafe.ai/confidence.md), 2026-09-16).
Cookbooks illustrate a concrete band (e.g. Noul values in [0.30, 0.70] treated as an
uncertainty band) and stress that the band is "illustrative, not a calibrated guarantee
or optimized threshold"
([TypeSafe docs — consistency noul cookbook](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md), 2026-09-16).
Thresholds scale with risk: different actions in the same system gate at different
confidence levels depending on the cost of being wrong
([Confidence docs](https://docs.typesafe.ai/confidence.md), 2026-09-16).

**Validation with labeled cases.** TypeSafe's own guidance is that the correct thresholds
"depend on your domain and the performance of the model for your use case. Start with
conservative thresholds, test with your own data, and adjust as you observe results"
([Confidence docs](https://docs.typesafe.ai/confidence.md), 2026-09-16), and its cookbooks
repeat "Set production thresholds using labeled examples and the cost of incorrect actions
and human review" ([consistency choice cookbook](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md), 2026-09-16).

**Diagonal calibration curve.** Third-party-reported: the practical audit is to bucket
predictions by reported confidence and compare each bucket against its realized accuracy —
"a well-calibrated model traces a diagonal line," while an overconfident model clusters
everything above 0.9 and is right only 70% of the time
([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16).
Kingy AI makes the same point: TypeSafe publishes no calibration metrics against
independent ground truth, so calibration is something buyers must measure themselves
([Kingy AI review](https://kingy.ai/blog/typesafe-jev-review-the-ai-model-that-doesnt-generate-text/), 2026-09-16).

## 5. The three primitives and their typed answers

A `Question` is one of three types sharing `type` and `instructions`; each adds its own
`criteria` ([API reference](https://docs.typesafe.ai/api.md), 2026-09-16). Answers come
back under caller-chosen ids, which "is not sent to the underlying model and is not used
in inference" ([API reference](https://docs.typesafe.ai/api.md), 2026-09-16).

| Primitive | Question shape | Criteria | Typed answer |
| --- | --- | --- | --- |
| **Noul** | yes/no: "Returns the probability the answer is yes" | optional `{true, false}` descriptions | `noul`: number 0–1 (0 = no, 1 = yes); **no `confidence` property** ([API](https://docs.typesafe.ai/api.md), [Confidence](https://docs.typesafe.ai/confidence.md), 2026-09-16) |
| **Choice** | pick one option | required map of option → rubric description (`string \| null`) | `choice` (highest-probability option), `probabilities` (floats summing to 1), `confidence` 0–1 ([API reference](https://docs.typesafe.ai/api.md), 2026-09-16) |
| **Score** | rate on an ordered rubric | required ordered array of level descriptions (≥ 2 levels) | `score` (probability-weighted value; can land between levels), `legend` (level → description), `probabilities`, `confidence` ([API reference](https://docs.typesafe.ai/api.md), 2026-09-16) |

Responses also carry `model` and `usage` (`input_tokens`, `output_tokens`)
([API reference](https://docs.typesafe.ai/api.md), 2026-09-16). Third-party-reported:
"Noul" is a portmanteau of "no" and "null" ([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16);
this etymology does not appear in TypeSafe's docs.

Design guidance: each question should be one atomic, well-scoped judgment ("the kind of
judgment a highly knowledgeable person could make in a few seconds given the right
context"); decompose multi-factor questions and combine answers with code
([TypeSafe docs — Introduction](https://docs.typesafe.ai/introduction.md), 2026-09-16).
Composable patterns (confidence routing, composite scoring, fan-out, intent routing) are
documented under Patterns
([TypeSafe docs — Patterns](https://docs.typesafe.ai/patterns.md), 2026-09-16).

## 6. Model versioning

- Requests select the model via the required `model` field on `POST /v1/systemone`;
  the docs and SDKs default to **`jev-latest`** ([System One docs](https://docs.typesafe.ai/concepts/system-one.md); [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), 2026-09-16).
- `jev-latest` is an **alias that resolves server-side and can drift**: TypeSafe's
  consistency cookbooks record `jev-latest` requests resolving to `jev-1.13.0`
  (production API, sampled 2026-09-11) and instruct: "Preserve the returned model because
  an alias can resolve to a different version later"
  ([consistency choice cookbook](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md), 2026-09-16;
  [consistency noul cookbook](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md), 2026-09-16).
- Pinned versions exist and are used for reproducibility; many TypeSafe cookbooks pin
  **`jev-1.12`** with pricing noted as of 2026-09
  ([e.g. the autoformat cookbook](https://docs.typesafe.ai/cookbooks/autoformat.md), 2026-09-16).
- The response's `model` field reports the version that actually performed the evaluation
  ([API reference](https://docs.typesafe.ai/api.md), 2026-09-16).
- Third-party-reported: Kingy AI flags "alias drift" as a reproducibility risk in its spec
  table ([Kingy AI review](https://kingy.ai/blog/typesafe-jev-review-the-ai-model-that-doesnt-generate-text/), 2026-09-16).

## 7. Naming origins

- **System One** comes from Daniel Kahneman's *Thinking, Fast and Slow*: System 1
  thinking is fast and intuitive, System 2 slower and more deliberate; TypeSafe stresses
  fast, focused judgments ([System One docs note](https://docs.typesafe.ai/concepts/system-one.md), 2026-09-16;
  [TypeSafe blog FAQ](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
  The blog adds that "System 1 thinking" has also connoted error-prone, and TypeSafe
  believes System One Models can be made more reliable than their alternatives
  ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
- **Jev** is named after William Stanley Jevons: TypeSafe expects machine intelligence to
  follow the Jevons-paradox path — steam-engine efficiency increased coal demand, and
  "every order of magnitude drop in the cost of intelligence unlocks orders of magnitude
  more use cases" ([TypeSafe blog FAQ](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
  The Register elaborates the paradox: technology efficiency related to coal usage
  *increased* consumption rather than reducing it
  ([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711), 2026-09-16).

## 8. Company background

- **Founders** ([TypeSafe team page](https://typesafe.ai/team), 2026-09-16):
  - **Diogo Almeida** — CEO. "Diogo co-invented RLHF and InstructGPT, the methods that
    lead to ChatGPT and GPT-4. Previously, he was at Google Brain."
  - **Sasha Sheng** — COO. Ex-research engineer at Meta/FAIR (News Feed, AI Experiences,
    AI Research); publications at NeurIPS and ECCV.
  - **Erik Gafni** — CTO. Repeat founder (Ravel), early employee at Invitae and Freenome.
  - The broader team comes "from OpenAI, Google Brain, Meta/FAIR, Stripe, Airbnb, Plaid,
    Docker, and more" ([TypeSafe team page](https://typesafe.ai/team), 2026-09-16).
- **Diogo / RLHF verification.** The claim survives multi-source checking: TypeSafe's
  own AI primer states RLHF "was co-invented by Diogo Almeida, cofounder of TypeSafe,"
  linking his Google Scholar profile
  ([AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md), 2026-09-16);
  Every reports he coauthored the 2022 InstructGPT paper (arXiv:2203.02155)
  ([Every](https://every.to/also-true-for-humans/mini-vibe-check-typesafe-s-jev-judged-everything-i-ve-written-in-0-7-seconds), 2026-09-16);
  The Register calls him "a former OpenAI researcher and one of the co-inventors of
  reinforcement learning for human feedback" and links ChatGPT
  ([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711), 2026-09-16).
  The launch post itself: "At OpenAI, I helped build the methods that made language
  models useful at following instructions and talking with people. That work ended up as
  the research behind ChatGPT"
  ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
- **Funding.** Third-party-reported: The Register reports TypeSafe AI was "bestowed with
  $40 million in funding" at launch
  ([The Register](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711), 2026-09-16);
  business-wire coverage describes a $40M seed round led by DCVC for the San
  Francisco-based lab founded in 2024
  ([Tech Startups summarizing the Sept 15, 2026 press release](https://techstartups.com/2026/09/16/typesafe-ai-an-ai-startup-founded-by-chatgpt-co-inventor-emerges-from-stealth-with-40m-to-build-ai-thats-100x-faster-and-cheaper/), 2026-09-16).
- Almeida says TypeSafe spent two years in stealth before launch
  ([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).

## 9. Evidence: vendor claims vs independent measurement

**Vendor-reported, unreproduced** — the headline speed/cost figures (70–500 ms;
40x–200x; two orders of magnitude), TypeSafe's workflow evals (four workflows; reference
answers = the average judgment of GPT-6 Astra and Fable 5.1 rather than ground truth;
TypeSafe acknowledges possible harness bias), and the no-type-error guarantee
([TypeSafe blog](https://typesafe.ai/blog/introducing-system-one-models-and-jev), 2026-09-16).
The Decoder notes GPT-6 Astra is absent from the published evals
([The Decoder](https://the-decoder.com/former-openai-researcher-builds-an-ai-model-that-judges-options-instead-of-writing-text/), 2026-09-16).

**Independently measured (small sample)** — Every's hands-on tests
([Every](https://every.to/also-true-for-humans/mini-vibe-check-typesafe-s-jev-judged-everything-i-ve-written-in-0-7-seconds), 2026-09-16):
777 judgments (27 real articles + 10 AI-styled counterparts × 21 questions) in under
0.7 seconds for an estimated quarter of a cent; 1,709 judgments across 11 experiments for
under a cent total; and a 12-passage defect test by Every's CEO Dan Shipper where Jev ran
a median 0.35 s per passage vs 8.83 s for Claude Fable 5.1 at high effort (~25x faster,
~580x cheaper) and caught 6 of 7 planted defects while Fable caught all 7. OrcaRouter's
read: "the speed and cost claims survive contact with a third party, the accuracy claim
sits a notch below the frontier, and the sample is small"
([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16).

**Still unknown** — third-party-reported: no published architecture paper, parameter
count, training-compute disclosure, or weights at launch
([OrcaRouter](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know), 2026-09-16).

## 10. Sibling System One servers: jeff and kev

daf-jev ships multi-provider dispatch for self-hostable servers that speak
the same wire contract as TypeSafe's hosted API (`POST /v1/systemone`,
`GET /v1/models`, the noul/choice/score primitives, strict calibrated
answers). The two reference sibling implementations differ on the model
family — GLiFormer (jeff) versus the Qwen3.5 family (kev) — but both are
drop-in wire-compatible, so daf-jev needs no adapter: its strict
`parse_response` already tolerates unknown top-level fields (kev adds a
top-level `latency_ms`; daf-jev parses it and ignores it).

Facts below are as pinned by the provider-dispatch contract (2026-09-22);
unlike the sections above, they have not been re-verified against each
project's public documentation, so no external links beyond the two pinned
repositories are asserted.

| | jeff | kev |
| --- | --- | --- |
| Project | [logan-markewich/jeff](https://github.com/logan-markewich/jeff) | [jaredpalmer/kev](https://github.com/jaredpalmer/kev) |
| Model family | GLiFormer | Qwen3.5, 0.8B/4B/9B |
| Default base URL | `http://localhost:8000` | `http://localhost:8009` |
| Default model | `jev-latest` (also accepts the alias `jev`) | `kev-latest` |
| Client key env var | `JEFF_API_KEY` (server auth var: `JEFF_API_KEYS`); falls back to `TYPESAFE_API_KEY` | `KEV_API_KEY`; falls back to `TYPESAFE_API_KEY` |
| Base-URL / model env vars | `JEFF_BASE_URL` / `JEFF_MODEL` | `KEV_BASE_URL` / `KEV_MODEL` |
| Behavioral caveats | temperature-scaled probabilities; nominal output tokens | responses add a top-level `latency_ms` field; legend keys are strings (`"0"`, `"1"`, `"2"`) |

Naming note (verified): the official TypeSafe SDK convention is
`TYPESAFE_API_KEY` / `TYPESAFE_BASE_URL` / `TYPESAFE_DEFAULT_MODEL`;
daf-jev keeps `JEV_*` as its own primary names with `TYPESAFE_*` fallbacks,
and the provider registry extends the same pattern per provider
(provider-prefixed vars first, `TYPESAFE_*` fallbacks last).

## 11. Sibling ecosystem (second tier)

Catalogued during the same provider-dispatch effort (2026-09-22) and listed
exactly as verified — identifiers only. daf-jev ships first-class dispatch
for its six-provider registry (jev, jeff, kev, localjev,
openthai-systemone, openrouter — see README's Providers section); none of
the entries below are wired in.

Catalog-tier servers (with caveats):

- `razorback16/openjev` — DiffusionGemma 26B on vLLM; `OPENJEV_API_KEY`;
  hosted at `api.codiv.ai`; port per its Docker setup.
- `ekzhang/openjev-sglang` — Qwen3.6-35B on SGLang; instructions required;
  restricted license.
- `Rizzo-AI-Academy/rizzo-flow` — Spark-X2.5-4B on llama.cpp; serves
  `/v1/models` with honest alias text; numeric legend keys (deviation).
- `featherless-ai/simple-jev` — no license file; no `/v1/models`; free
  demo API.
- `hawkymisc` typed-decision-bert.
- `Argos1111/jev_local`; `hunkim/solar-mini4-jev`; `taeold/djev-run`.
- PyPI packages: `fastjev`, `poorjev`, `any2jev`.
- `SiliconLabAI/OpenJev`; `sabeel111/OpenSourceJev`.

Adjacent model families without confirmed wire servers:
`TheoLeeCJ/SemIf` (3.7k), `NandhaKishorM/laya` (15k),
`TianyuCodings/NanoJev` (2k), `bespokelabsai/nimble`, `wfzyx/von`,
`vinnylarouge/jevlike`, `Mapika/decider`.

Trackers: mrjev.com, awesomejev.com, systemonemodels.org.

## Sources

Primary (TypeSafe):

| Cite key | Source | Used for |
| --- | --- | --- |
| `typesafe2026systemone` | [Introducing System One Models & Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) (2026-09-16) | launch claims: architecture, parallel sampler, RLCD, latency/cost, naming, team provenance, early access |
| `typesafe2026systemoneconcept` | [System One concept page](https://docs.typesafe.ai/concepts/system-one.md) — local: `docs/reference/concepts/system-one.md` (2026-09-16) | System One definition, calibrated-decision training, Kahneman naming, `jev-latest` default |
| `typesafe2026apidocs` | [API reference](https://docs.typesafe.ai/api.md) — local: `docs/reference/api.md` (2026-09-16) | endpoint, question/answer shapes, usage, errors |
| `typesafe2026confidence` | [Confidence](https://docs.typesafe.ai/confidence.md) — local: `docs/reference/confidence.md` (2026-09-16) | confidence derivation, three bands, risk-scaled thresholds, Noul has no confidence |
| `typesafe2026patterns` | [Patterns](https://docs.typesafe.ai/patterns.md) — local: `docs/reference/patterns/` (2026-09-16) | composable patterns (confidence routing, composite scoring) |
| `typesafe2026primitives` | [Primitives (Questions)](https://docs.typesafe.ai/primitives.md) — local: `docs/reference/primitives.md` (2026-09-16) | parallel isolated questions, 32K-token/150K-char request budget |
| `typesafe2026aiprimer` | [AI primer](https://docs.typesafe.ai/introduction/machine-learning-primer.md) — local: `docs/reference/introduction/machine-learning-primer.md` (2026-09-16) | RLHF/RLVR/RLCD contrast, calibration definition, mode dropping, Almeida/RLHF |
| `typesafe2026team` | [Team](https://typesafe.ai/team) (2026-09-16) | founders and backgrounds |
| *(cookbooks, within the same snapshot `b79c9cd6008489f1`)* | [consistency choice](https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook.md), [consistency noul](https://docs.typesafe.ai/cookbooks/consistency_noul_cookbook.md), [autoformat](https://docs.typesafe.ai/cookbooks/autoformat.md) | alias→`jev-1.13.0`, pinned `jev-1.12`, labeled-example threshold guidance, uncertainty band |
| *(intro/quickstart, within the same snapshot)* | [Introduction](https://docs.typesafe.ai/introduction.md), [Quick start](https://docs.typesafe.ai/introduction/quickstart.md) | parallel isolated evaluation, no context-rot, SDK `jev-latest` default |

Third-party (independent):

| Cite key | Source | Used for |
| --- | --- | --- |
| `register2026jev` | [The Register — Claburn, 2026-09-16](https://www.theregister.com/ai-and-ml/2026/09/16/typesafe-ai-debuts-model-for-machines-that-plays-doom/5296711) | corroborates latency/pricing, naming, funding; skeptical framing of "hallucination-free" |
| `orcarouter2026jev` | [OrcaRouter — Corvin, 2026-09-16](https://www.orcarouter.ai/blog/jev-typesafe-system-one-what-we-know) | vendor-vs-independent number sorting, Noul etymology, diagonal calibration-curve method |
| `elsolitario2026jev` | [El Solitario — Morales, 2026-09-16](https://elsolitario.org/en/2026/09/16/typesafe-ai-jev-structured-decision-model/) | independent RLCD/sampling explainer, launch timeline, pricing-sustainability caveat |
| `thedecoder2026jev` | [The Decoder — Schreiner, 2026-09-16](https://the-decoder.com/former-openai-researcher-builds-an-ai-model-that-judges-options-instead-of-writing-text/) | Almeida/InstructGPT, limits of vendor evals, "no hallucinations ≠ no mistakes" |
| `every2026minivibecheck` | [Every — Taylor, 2026-09-15](https://every.to/also-true-for-humans/mini-vibe-check-typesafe-s-jev-judged-everything-i-ve-written-in-0-7-seconds) | independent hands-on measurements (777 judgments, defect test) |
| *(additional, cited above)* | [Kingy AI review](https://kingy.ai/blog/typesafe-jev-review-the-ai-model-that-doesnt-generate-text/) (2026-09-16); [Tech Startups press-release coverage](https://techstartups.com/2026/09/16/typesafe-ai-an-ai-startup-founded-by-chatgpt-co-inventor-emerges-from-stealth-with-40m-to-build-ai-thats-100x-faster-and-cheaper/) (2026-09-16); [workflow evals](https://evals.typesafe.ai/) | versioning reproducibility note; DCVC-led $40M seed (press-release summary); TypeSafe's eval dashboard |
