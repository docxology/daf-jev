> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Class: TypeSafeError

Base class for SDK errors.

## Extends

* `Error`

## Extended by

* [`APIConnectionError`](/sdk/javascript/api/classes/APIConnectionError)
* [`APIError`](/sdk/javascript/api/classes/APIError)
* [`APIUserAbortError`](/sdk/javascript/api/classes/APIUserAbortError)

## Constructors

<a id="sdk-constructor" />

### Constructor

```ts theme={null}
new TypeSafeError(message, options?): TypeSafeError;
```

#### Parameters

##### message

`string`

##### options?

`ErrorOptions`

#### Returns

`TypeSafeError`

#### Overrides

```ts theme={null}
Error.constructor
```
