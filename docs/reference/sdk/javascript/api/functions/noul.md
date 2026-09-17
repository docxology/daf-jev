> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Function: noul()

```ts theme={null}
function noul(instructions?, criteria?): NoulQuestion;
```

Create a yes/no question with optional descriptions for either outcome.

## Parameters

### instructions?

[`EntryType`](/sdk/javascript/api/type-aliases/EntryType) = `null`

The question as text, a JSON object or array; defaults to `null`.

### criteria?

\| \{
`false?`: [`EntryType`](/sdk/javascript/api/type-aliases/EntryType);
`true?`: [`EntryType`](/sdk/javascript/api/type-aliases/EntryType);
}
\| `null`

Optional descriptions of the yes and no outcomes.

#### Type Literal

\{
`false?`: [`EntryType`](/sdk/javascript/api/type-aliases/EntryType);
`true?`: [`EntryType`](/sdk/javascript/api/type-aliases/EntryType);
}

Optional descriptions of the yes and no outcomes.

##### false?

[`EntryType`](/sdk/javascript/api/type-aliases/EntryType)

Description of the no outcome.

##### true?

[`EntryType`](/sdk/javascript/api/type-aliases/EntryType)

Description of the yes outcome.

***

`null`

## Returns

[`NoulQuestion`](/sdk/javascript/api/interfaces/NoulQuestion)
