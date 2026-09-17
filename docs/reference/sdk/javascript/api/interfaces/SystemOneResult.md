> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: SystemOneResult<Q>

Answers keyed by question name, with model and usage metadata.

## Type Parameters

### Q

`Q` *extends* [`Questions`](/sdk/javascript/api/interfaces/Questions)

## Properties

<a id="sdk-answers" />

### answers

```ts theme={null}
readonly answers: { readonly [K in string | number | symbol]: ResultFor<Q[K]> };
```

Answers with types inferred from the supplied questions.

***

<a id="sdk-model" />

### model

```ts theme={null}
readonly model: string;
```

The model used to answer the request.

***

<a id="sdk-usage" />

### usage

```ts theme={null}
readonly usage: Usage;
```

Token usage for the request.
