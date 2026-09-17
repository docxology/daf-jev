> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: SystemOneRequest<Q>

State and named questions for `systemOne`.

Additional properties on a request variable are forwarded, including `null` values.

## Extended by

* [`SystemOneRequestPayload`](/sdk/javascript/api/interfaces/SystemOneRequestPayload)

## Type Parameters

### Q

`Q` *extends* [`Questions`](/sdk/javascript/api/interfaces/Questions) = [`Questions`](/sdk/javascript/api/interfaces/Questions)

## Properties

<a id="sdk-model" />

### model?

```ts theme={null}
optional model?: string;
```

Model override; omitted values inherit `defaultModel`.

***

<a id="sdk-questions" />

### questions

```ts theme={null}
questions: Q;
```

Nonempty questions keyed by the names used to identify their answers.

***

<a id="sdk-state" />

### state

```ts theme={null}
state: EntryType;
```

Text, a JSON object or array, or `null` to evaluate.
