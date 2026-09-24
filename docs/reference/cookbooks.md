> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Cookbooks

> End-to-end recipes that show TypeSafe in real problems, from a few questions to full pipelines.

Each cookbook is a worked example: a real dataset, the TypeSafe questions that decide something about it, and the code that turns those decisions into a working system. Read one when you want to see how the [primitives](/primitives) and [patterns](/patterns) come together on a concrete problem, or copy one as the starting point for your own.

This section assumes you know the [TypeSafe primitives](/primitives) and understand [how confidence works](/confidence). If not, read those first.

## Self-consistency

Repeat a decision and use the agreement across runs as a signal.

| Cookbook                                                            | What it does                                                                                                      | Level    |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------- |
| [Self-consistency: nouls](/cookbooks/consistency_noul_cookbook)     | Route uncertain probabilities to human review while keeping the underlying noul values visible.                   | Beginner |
| [Self-consistency: choices](/cookbooks/consistency_choice_cookbook) | Add an uncertain outcome to moderation decisions and compare label agreement with the share of automatic actions. | Beginner |

## Batching

Pack many questions into a single request.

| Cookbook                                            | What it does                                                                                                                                                                                     | Level    |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------- |
| [Parallel questions](/cookbooks/parallel_questions) | Runs a 13-question regulatory briefing over the GDPR Wikipedia article, showing that batching every question into one TypeSafe call is 12.2x cheaper and 10.0x faster with no change in answers. | Beginner |

## How-to

Recipes for common tasks: search, formatting, tool selection, guardrails.

| Cookbook                                                        | What it does                                                                                                                                                                                                             | Level        |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------ |
| [Re-ranking](/cookbooks/rerank_typesafe)                        | Builds 30-passage BM25 shortlists for 40 CLERC legal queries, then uses one TypeSafe question per query-candidate pair to raise top-1 accuracy from 5% to 18% and top-10 accuracy from 38% to 62%.                       | Beginner     |
| [Line-by-line search](/cookbooks/semantic_find)                 | Build semantic search for GitHub's Terms of Service. In one request, score 218 line ids against a plain-language query with a Choice question, and use a Noul question to check whether the document contains an answer. | Beginner     |
| [Structure recovery](/cookbooks/autoformat)                     | Reconstructs Markdown from plain text that lost its formatting in two requests: one stitches hard-wrapped lines back together, one classifies every block (heading, list, code, callout).                                | Beginner     |
| [Function calling](/cookbooks/function_calling)                 | Turns natural-language trading requests into calls to ordinary typed functions by mapping function names and closed-set arguments to confidence-aware TypeSafe questions.                                                | Intermediate |
| [Skill suggestion](/cookbooks/skill_suggestion)                 | Picks at most one skill for an agent turn out of the 182 in Nous Research's Hermes catalog, using two TypeSafe requests to rank and re-check the top candidates.                                                         | Intermediate |
| [Knowledge graph entity alignment](/cookbooks/entity_alignment) | Decides which of 450 candidate pairs from two beer catalogues describe the same product using one Score question plus three companion Nouls that surface which fields disagree.                                          | Beginner     |
| [Classifying RAG passages](/cookbooks/classifying_rag_passages) | Score each retrieved passage with one TypeSafe request, then decide in code which ones reach the answering model.                                                                                                        | Intermediate |
| [Double-checking citations](/cookbooks/citation_check)          | Catch wrong or hallucinated citations by checking against the source document. One Choice question decides whether the quote's context supports the claim.                                                               | Beginner     |
| [Guardrails for LLMs](/cookbooks/llm_guardrails)                | Screen every message going into and out of an LLM app with one TypeSafe request, thresholding hazard probabilities and severity to pass, review, block, or route.                                                        | Intermediate |

## Extraction

Pull typed values out of messy text.

| Cookbook                                                                       | What it does                                                                                                                                                        | Level        |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| [SDE cascade](/cookbooks/sde_cascade)                                          | Uses a 2-stage structured-data-extraction cascade (mini → verify → reasoning) to get most of the quality of a big reasoning model at a fraction of the cost.        | Intermediate |
| [Date extraction](/cookbooks/date_extraction_cookbook)                         | Extracts absolute and relative dates by asking TypeSafe for the parts named in a document, then resolving and validating them in code with confidence-based review. | Beginner     |
| [Pre-parsed value extraction](/cookbooks/pre_parsed_value_extraction_cookbook) | Uses regexes to find candidate emails, phone numbers, and amounts, then has TypeSafe select the requested span so code can normalize a verbatim value.              | Beginner     |

## Classification

Assign inputs to categories at any depth.

| Cookbook                                                                      | What it does                                                                                                                                                                             | Level        |
| ----------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| [Hierarchical classification](/cookbooks/hierarchical_classification)         | Classifies documents through deep patent, retail product, biomedical, and source-code hierarchies using parallel beam search over TypeSafe Choice probabilities.                         | Intermediate |
| [Autoresearch feature discovery](/cookbooks/autoresearch_feature_discovery)   | Runs an autoresearch loop that proposes TypeSafe questions, converts free text into numeric features, and uses model errors to improve a supervised CatBoost regressor.                  | Advanced     |
| [Classification using confidence](/cookbooks/classification_using_confidence) | Classify SEC annual reports into 75 industry groups with one Choice each, then read the answer's own confidence to decide whether to report that group or the broader division above it. | Beginner     |

<Tip>
  We're always keen to learn how people are making use of our primitives. If you've built something worth a cookbook, drop us a note!
</Tip>
