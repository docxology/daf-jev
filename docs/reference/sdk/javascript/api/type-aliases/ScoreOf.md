> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Type Alias: ScoreOf<T>

```ts theme={null}
type ScoreOf<T> = number extends T["length"] ? number : Extract<keyof T, `${number}`>;
```

Score keys inferred from the rubric; a fixed-length tuple yields its indices, otherwise `number`.

## Type Parameters

### T

`T` *extends* [`ScoreCriteria`](/sdk/javascript/api/type-aliases/ScoreCriteria)
