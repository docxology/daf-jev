> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: ScoreQuestion<T>

A question that assigns a score using an ordered rubric.

## Type Parameters

### T

`T` *extends* [`ScoreCriteria`](/sdk/javascript/api/type-aliases/ScoreCriteria) = [`ScoreCriteria`](/sdk/javascript/api/type-aliases/ScoreCriteria)

## Properties

<a id="sdk-criteria" />

### criteria

```ts theme={null}
criteria: T;
```

Descriptions of the available outcomes.

***

<a id="sdk-instructions" />

### instructions?

```ts theme={null}
optional instructions?: EntryType;
```

The question as text, a JSON object, or an array; optional or `null`.

***

<a id="sdk-type" />

### type

```ts theme={null}
type: "score";
```
