> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Type Alias: EntryType

```ts theme={null}
type EntryType = 
  | string
  | {
[key: string]: JsonValue;
}
  | JsonValue[]
  | null;
```

Text, a JSON object or array, or `null` for state, instructions, and criteria.
