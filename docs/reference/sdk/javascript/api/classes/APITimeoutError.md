> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Class: APITimeoutError

The full response did not arrive within the timeout. A kind of `APIConnectionError`.

## Extends

* [`APIConnectionError`](/sdk/javascript/api/classes/APIConnectionError)

## Constructors

<a id="sdk-constructor" />

### Constructor

```ts theme={null}
new APITimeoutError(timeoutMs, options?): APITimeoutError;
```

#### Parameters

##### timeoutMs

`number`

##### options?

`ErrorOptions`

#### Returns

`APITimeoutError`

#### Overrides

[`APIConnectionError`](/sdk/javascript/api/classes/APIConnectionError).[`constructor`](/sdk/javascript/api/classes/APIConnectionError#sdk-constructor)

## Properties

<a id="sdk-timeoutms" />

### timeoutMs

```ts theme={null}
readonly timeoutMs: number;
```

Configured timeout in milliseconds.
