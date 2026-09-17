> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Class: APIConnectionError

The request or response-body delivery failed (DNS, TLS, connection closed, etc.).

## Extends

* [`TypeSafeError`](/sdk/javascript/api/classes/TypeSafeError)

## Extended by

* [`APITimeoutError`](/sdk/javascript/api/classes/APITimeoutError)

## Constructors

<a id="sdk-constructor" />

### Constructor

```ts theme={null}
new APIConnectionError(message?, options?): APIConnectionError;
```

#### Parameters

##### message?

`string` = `"Connection error."`

##### options?

`ErrorOptions`

#### Returns

`APIConnectionError`

#### Overrides

[`TypeSafeError`](/sdk/javascript/api/classes/TypeSafeError).[`constructor`](/sdk/javascript/api/classes/TypeSafeError#sdk-constructor)
