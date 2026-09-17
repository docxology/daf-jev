> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: RequestOptions

Per-call options that override client settings.

## Properties

<a id="sdk-headers" />

### headers?

```ts theme={null}
optional headers?: Record<string, string>;
```

Additional headers, merged over `defaultHeaders`.

***

<a id="sdk-retry" />

### retry?

```ts theme={null}
optional retry?: Partial<RetryPolicy>;
```

Retry overrides for this call; omitted fields inherit client settings.

***

<a id="sdk-signal" />

### signal?

```ts theme={null}
optional signal?: AbortSignal;
```

Cancellation signal for the request and pending retries.

***

<a id="sdk-timeout" />

### timeout?

```ts theme={null}
optional timeout?: number;
```

Timeout per attempt in milliseconds; there is no total retry budget.
