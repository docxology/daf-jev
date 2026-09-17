> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Class: APIPromise<T>

A promise for the parsed result with access to the HTTP response.

Non-2xx responses reject with an `APIError`, including through `asResponse()`.

## Extends

* `Promise`\<`T`>

## Type Parameters

### T

`T`

## Constructors

<a id="sdk-constructor" />

### Constructor

```ts theme={null}
new APIPromise<T>(responsePromise, parseResponse): APIPromise<T>;
```

#### Parameters

##### responsePromise

`Promise`\<`Response`>

##### parseResponse

(`response`) => `Promise`\<`T`>

#### Returns

`APIPromise`\<`T`>

#### Overrides

```ts theme={null}
Promise<T>.constructor
```

## Methods

<a id="sdk-asresponse" />

### asResponse()

```ts theme={null}
asResponse(): Promise<Response>;
```

Resolves to the raw `Response` without parsing the body. SDK requests buffer the full
body under the request timeout before handoff; reading it afterwards is caller-owned.
The caller owns the body; don't also `await` the parsed result on the same promise.

#### Returns

`Promise`\<`Response`>

***

<a id="sdk-catch" />

### catch()

```ts theme={null}
catch<TResult>(onrejected?): Promise<T | TResult>;
```

Attaches a callback for only the rejection of the Promise.

#### Type Parameters

##### TResult

`TResult` = `never`

#### Parameters

##### onrejected?

((`reason`) => `TResult` | `PromiseLike`\<`TResult`>) | `null`

The callback to execute when the Promise is rejected.

#### Returns

`Promise`\<`T` | `TResult`>

A Promise for the completion of the callback.

#### Overrides

```ts theme={null}
Promise.catch
```

***

<a id="sdk-finally" />

### finally()

```ts theme={null}
finally(onfinally?): Promise<T>;
```

Attaches a callback that is invoked when the Promise is settled (fulfilled or rejected). The
resolved value cannot be modified from the callback.

#### Parameters

##### onfinally?

(() => `void`) | `null`

The callback to execute when the Promise is settled (fulfilled or rejected).

#### Returns

`Promise`\<`T`>

A Promise for the completion of the callback.

#### Overrides

```ts theme={null}
Promise.finally
```

***

<a id="sdk-map" />

### map()

```ts theme={null}
map<U>(fn): APIPromise<U>;
```

Transform the parsed result, sharing the HTTP response and a single body parse.

#### Type Parameters

##### U

`U`

#### Parameters

##### fn

(`data`) => `U`

#### Returns

`APIPromise`\<`U`>

***

<a id="sdk-then" />

### then()

```ts theme={null}
then<TResult1, TResult2>(onfulfilled?, onrejected?): Promise<TResult1 | TResult2>;
```

Attaches callbacks for the resolution and/or rejection of the Promise.

#### Type Parameters

##### TResult1

`TResult1` = `T`

##### TResult2

`TResult2` = `never`

#### Parameters

##### onfulfilled?

((`value`) => `TResult1` | `PromiseLike`\<`TResult1`>) | `null`

The callback to execute when the Promise is resolved.

##### onrejected?

((`reason`) => `TResult2` | `PromiseLike`\<`TResult2`>) | `null`

The callback to execute when the Promise is rejected.

#### Returns

`Promise`\<`TResult1` | `TResult2`>

A Promise for the completion of which ever callback is executed.

#### Overrides

```ts theme={null}
Promise.then
```

***

<a id="sdk-withresponse" />

### withResponse()

```ts theme={null}
withResponse(): Promise<WithResponse<T>>;
```

Return the parsed result, HTTP response, and request ID.

#### Returns

`Promise`\<[`WithResponse`](/sdk/javascript/api/interfaces/WithResponse)\<`T`>>
