> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Exceptions

> Handle TypeSafe API errors, rate limits, connection failures, and timeouts.

export function SdkSignature({children}) {
  async function copy(event) {
    const button = event.currentTarget;
    const code = button.parentElement.querySelector("pre code");
    try {
      await navigator.clipboard.writeText(code.textContent);
      button.setAttribute("aria-label", "Signature copied");
      button.dataset.copied = "true";
    } catch {
      button.setAttribute("aria-label", "Copy failed; select the signature to copy");
    }
    setTimeout(() => {
      button.setAttribute("aria-label", "Copy signature");
      delete button.dataset.copied;
    }, 2000);
  }
  return <div className="sdk-signature not-prose">
      <button type="button" className="sdk-signature-copy" aria-label="Copy signature" onClick={copy}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="8" y="8" width="12" height="12" rx="2" />
          <path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" />
        </svg>
      </button>
      <pre tabIndex={0} aria-label="SDK signature"><code>{children}</code></pre>
    </div>;
}

<a id="exceptions" />

<h2 id="base-exception">
  Base exception
</h2>

<h2 id="typesafe_sdk.TypeSafeError">
  typesafe\_sdk.TypeSafeError
</h2>

Bases: <code><a href="https://docs.python.org/3/builtins/exceptions.html#Exception">Exception</a></code>

Base exception for SDK failures.

<h2 id="http-errors">
  HTTP errors
</h2>

<h2 id="typesafe_sdk.TypeSafeAPIError">
  typesafe\_sdk.TypeSafeAPIError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeError">TypeSafeError</a></code>

An unsuccessful HTTP response with its body and request metadata.

<h3 id="typesafe_sdk.TypeSafeAPIError.status">
  status
</h3>

`instance-attribute`

```python theme={null}
status = status
```

HTTP response status code.

<h3 id="typesafe_sdk.TypeSafeAPIError.body">
  body
</h3>

`instance-attribute`

```python theme={null}
body = body
```

The server's JSON error body, plain response text, or `None` for an empty body.

<h3 id="typesafe_sdk.TypeSafeAPIError.headers">
  headers
</h3>

`instance-attribute`

```python theme={null}
headers = headers
```

HTTP response headers.

<h3 id="typesafe_sdk.TypeSafeAPIError.endpoint">
  endpoint
</h3>

`instance-attribute`

```python theme={null}
endpoint = endpoint
```

The request method and URL, without credentials, query parameters, or fragment, when available.

<h3 id="typesafe_sdk.TypeSafeAPIError.request_id">
  request\_id
</h3>

`property`

<SdkSignature>
  <span className="n">
    {"request_id"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"|"}
  </span>

  {" "}

  <span className="kc">
    {"None"}
  </span>

  {"\n"}
</SdkSignature>

The `x-typesafe-request-id` response header, or `None` if absent.

<h2 id="typesafe_sdk.TypeSafeBadRequestError">
  typesafe\_sdk.TypeSafeBadRequestError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

The request was invalid (400).

<h2 id="typesafe_sdk.TypeSafeAuthenticationError">
  typesafe\_sdk.TypeSafeAuthenticationError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

Authentication failed (401).

<h2 id="typesafe_sdk.TypeSafePermissionDeniedError">
  typesafe\_sdk.TypeSafePermissionDeniedError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

Access was denied (403).

<h2 id="typesafe_sdk.TypeSafeNotFoundError">
  typesafe\_sdk.TypeSafeNotFoundError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

The resource was not found (404).

<h2 id="typesafe_sdk.TypeSafeUnprocessableEntityError">
  typesafe\_sdk.TypeSafeUnprocessableEntityError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

The request failed server validation (422).

<h2 id="typesafe_sdk.TypeSafeRateLimitError">
  typesafe\_sdk.TypeSafeRateLimitError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

The rate limit was exceeded (429).

<h3 id="typesafe_sdk.TypeSafeRateLimitError.retry_after_ms">
  retry\_after\_ms
</h3>

`instance-attribute`

```python theme={null}
retry_after_ms = parse_retry_after(headers)
```

The server's requested wait in milliseconds, or `None` if unavailable.

<h2 id="typesafe_sdk.TypeSafeInternalServerError">
  typesafe\_sdk.TypeSafeInternalServerError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

The server failed to process the request (5xx).

<h2 id="connection-errors">
  Connection errors
</h2>

<h2 id="typesafe_sdk.TypeSafeAPIConnectionError">
  typesafe\_sdk.TypeSafeAPIConnectionError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeError">TypeSafeError</a></code>, <code><a href="https://docs.python.org/3/builtins/exceptions.html#ConnectionError">ConnectionError</a></code>

A request failed without an HTTP response.

<h2 id="typesafe_sdk.TypeSafeAPITimeoutError">
  typesafe\_sdk.TypeSafeAPITimeoutError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIConnectionError">TypeSafeAPIConnectionError</a></code>, <code><a href="https://docs.python.org/3/builtins/exceptions.html#TimeoutError">TimeoutError</a></code>

A request exceeded its configured timeout.

<h3 id="typesafe_sdk.TypeSafeAPITimeoutError.timeout">
  timeout
</h3>

`instance-attribute`

```python theme={null}
timeout = timeout
```

The timeout setting used for the request, in seconds or as an `httpx2.Timeout`.

<h2 id="response-validation">
  Response validation
</h2>

<h2 id="typesafe_sdk.TypeSafeAPIResponseValidationError">
  typesafe\_sdk.TypeSafeAPIResponseValidationError
</h2>

Bases: <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code>

A successful HTTP response whose body was missing or structurally invalid required data.

<h3 id="typesafe_sdk.TypeSafeAPIResponseValidationError.field_path">
  field\_path
</h3>

`instance-attribute`

```python theme={null}
field_path = field_path
```

Dotted path to the offending field, such as `answers.tone.confidence`.

<h3 id="typesafe_sdk.TypeSafeAPIResponseValidationError.args">
  args
</h3>

`instance-attribute`

```python theme={null}
args = (
    status,
    body,
    headers,
    field_path,
    endpoint,
)
```
