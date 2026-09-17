> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Function: choice()

```ts theme={null}
function choice<T>(instructions, criteria): ChoiceQuestion<T>;
```

Create a question that selects between named alternatives.

## Type Parameters

### T

`T` *extends* [`ChoiceCriteria`](/sdk/javascript/api/type-aliases/ChoiceCriteria)

## Parameters

### instructions

[`EntryType`](/sdk/javascript/api/type-aliases/EntryType)

The question as text, a JSON object or array, or `null`.

### criteria

`T`

Labels mapped to descriptions, or `null` for undescribed labels.

## Returns

[`ChoiceQuestion`](/sdk/javascript/api/interfaces/ChoiceQuestion)\<`T`>
