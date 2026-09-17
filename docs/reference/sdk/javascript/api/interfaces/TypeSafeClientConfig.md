> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Interface: TypeSafeClientConfig

Client options. Explicit values take precedence over environment variables, then SDK defaults.

## Properties

<a id="sdk-apikey" />

### apiKey?

```ts theme={null}
optional apiKey?: string;
```

Required API key; falls back to `TYPESAFE_API_KEY`.

***

<a id="sdk-baseurl" />

### baseURL?

```ts theme={null}
optional baseURL?: string;
```

API root; falls back to `TYPESAFE_BASE_URL`, then `https://api.typesafe.ai`.

***

<a id="sdk-dangerouslyallowbrowser" />

### dangerouslyAllowBrowser?

```ts theme={null}
optional dangerouslyAllowBrowser?: boolean;
```

Allow browser use, exposing the API key to page users. Default: false.

***

<a id="sdk-defaultheaders" />

### defaultHeaders?

```ts theme={null}
optional defaultHeaders?: Record<string, string>;
```

Additional request headers; per-call headers take precedence.

***

<a id="sdk-defaultmodel" />

### defaultModel?

```ts theme={null}
optional defaultModel?: string;
```

Default model; falls back to `TYPESAFE_DEFAULT_MODEL`, then `jev-latest`.

***

<a id="sdk-fetch" />

### fetch?

```ts theme={null}
optional fetch?: Fetch;
```

Custom HTTP fetch implementation for transport configuration or tests. Default: global `fetch`.

***

<a id="sdk-logger" />

### logger?

```ts theme={null}
optional logger?: Logger;
```

Logger filtered to `logLevel` and above. Default: prefixed `console`.

***

<a id="sdk-loglevel" />

### logLevel?

```ts theme={null}
optional logLevel?: LogLevel;
```

Log level; falls back to `TYPESAFE_LOG_LEVEL`, then `warn`.
`info` logs request summaries; `debug` adds headers and bodies.
Known credential headers are redacted; bodies are not.

***

<a id="sdk-retry" />

### retry?

```ts theme={null}
optional retry?: Partial<RetryPolicy>;
```

Retry overrides; omitted fields use the defaults in `RetryPolicy`.

***

<a id="sdk-timeout" />

### timeout?

```ts theme={null}
optional timeout?: number;
```

Timeout per attempt in milliseconds, without a total retry budget. Default: 10000.
