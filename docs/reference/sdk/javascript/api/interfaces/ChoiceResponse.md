> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: ChoiceResponse<T>

A selected label and its probabilities.

## Type Parameters

### T

`T` *extends* [`ChoiceCriteria`](/sdk/javascript/api/type-aliases/ChoiceCriteria) = [`ChoiceCriteria`](/sdk/javascript/api/type-aliases/ChoiceCriteria)

## Properties

<a id="sdk-choice" />

### choice

```ts theme={null}
readonly choice: keyof T & string;
```

The selected label.

***

<a id="sdk-confidence" />

### confidence

```ts theme={null}
readonly confidence: number;
```

Reported confidence in the selected label.

***

<a id="sdk-probabilities" />

### probabilities

```ts theme={null}
readonly probabilities: { readonly [label in string | number | symbol]: number };
```

Probabilities keyed by label.

***

<a id="sdk-type" />

### type

```ts theme={null}
readonly type: "choice";
```
