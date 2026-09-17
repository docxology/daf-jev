> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Class: InternalServerError

HTTP 5xx: the server failed to handle the request.

## Extends

* [`APIError`](/sdk/javascript/api/classes/APIError)

## Constructors

<a id="sdk-constructor" />

### Constructor

```ts theme={null}
new InternalServerError(
   status, 
   body, 
   headers, 
   message?
): InternalServerError;
```

#### Parameters

##### status

`number`

##### body

`unknown`

##### headers

`Headers`

##### message?

`string`

#### Returns

`InternalServerError`

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`constructor`](/sdk/javascript/api/classes/APIError#sdk-constructor)

## Properties

<a id="sdk-body" />

### body

```ts theme={null}
readonly body: unknown;
```

Parsed JSON, response text, or `undefined` for an empty body.

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`body`](/sdk/javascript/api/classes/APIError#sdk-body)

***

<a id="sdk-headers" />

### headers

```ts theme={null}
readonly headers: Headers;
```

HTTP response headers.

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`headers`](/sdk/javascript/api/classes/APIError#sdk-headers)

***

<a id="sdk-requestid" />

### requestId

```ts theme={null}
readonly requestId: string | undefined;
```

Request ID from `x-typesafe-request-id`, or `undefined` when absent.

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`requestId`](/sdk/javascript/api/classes/APIError#sdk-requestid)

***

<a id="sdk-status" />

### status

```ts theme={null}
readonly status: number;
```

HTTP response status code.

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`status`](/sdk/javascript/api/classes/APIError#sdk-status)

## Methods

<a id="sdk-fromresponse" />

### fromResponse()

```ts theme={null}
static fromResponse(
   status, 
   body, 
   headers
): APIError;
```

Create the error subclass for an HTTP status code.

#### Parameters

##### status

`number`

##### body

`unknown`

##### headers

`Headers`

#### Returns

[`APIError`](/sdk/javascript/api/classes/APIError)

#### Inherited from

[`APIError`](/sdk/javascript/api/classes/APIError).[`fromResponse`](/sdk/javascript/api/classes/APIError#sdk-fromresponse)
