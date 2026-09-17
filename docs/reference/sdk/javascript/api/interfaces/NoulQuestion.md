> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: NoulQuestion

A yes/no question with optional descriptions for either outcome.

## Properties

<a id="sdk-criteria" />

### criteria?

```ts theme={null}
optional criteria?: 
  | {
  false?: EntryType;
  true?: EntryType;
}
  | null;
```

Optional descriptions of the yes and no outcomes.

#### Union Members

##### Type Literal

```ts theme={null}
{
  false?: EntryType;
  true?: EntryType;
}
```

##### false?

```ts theme={null}
optional false?: EntryType;
```

Description of the no outcome.

##### true?

```ts theme={null}
optional true?: EntryType;
```

Description of the yes outcome.

***

`null`

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
type: "noul";
```
