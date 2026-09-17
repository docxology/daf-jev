> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Retries

> Configure retries with RetryPolicy — attempt count, retryable statuses, backoff, and retry headers handling.

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

<a id="retries" />

<h2 id="typesafe_sdk.RetryPolicy">
  typesafe\_sdk.RetryPolicy
</h2>

`dataclass`

<SdkSignature>
  <span className="nf">{"RetryPolicy"}</span><span className="p">{"("}</span>{"\n"}{"    "}<span className="n">{"max_retries"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#int">{"int"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="mi">{"2"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"backoff_initial"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="mf">{"0.5"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"backoff_max"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="mf">{"5.0"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"backoff_jitter"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="mf">{"0.25"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"http_statuses"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/functions.html#int">{"int"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="p">{"("}</span>{"\n"}{"        "}<span className="k">{"lambda"}</span><span className="p">{":"}</span>{" "}<span className="p">{"{"}</span><span className="mi">{"408"}</span><span className="p">{","}</span>{" "}<span className="mi">{"429"}</span><span className="p">{","}</span>{" "}<span className="o">{"*"}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#range">{"range"}</a></span><span className="p">{"("}</span><span className="mi">{"500"}</span><span className="p">{","}</span>{" "}<span className="mi">{"600"}</span><span className="p">{")}"}</span>{"\n"}{"    "}<span className="p">{")(),"}</span>{"\n"}{"    "}<span className="n">{"respect_retry_after"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#bool">{"bool"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"True"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"api_connection_error"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#bool">{"bool"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"True"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"api_timeout_error"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#bool">{"bool"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"True"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"exceptions"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span><span className="p">{"["}</span>{"\n"}{"        "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#type">{"type"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/exceptions.html#BaseException">{"BaseException"}</a></span><span className="p">{"]"}</span>{"\n"}{"    "}<span className="p">{"]"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span><span className="p">{"(),"}</span>{"\n"}{"    "}<span className="n">{"predicate"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable">{"Callable"}</a></span><span className="p">{"[["}</span><span className="n"><a href="https://docs.python.org/3/builtins/exceptions.html#BaseException">{"BaseException"}</a></span><span className="p">{"],"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#bool">{"bool"}</a></span><span className="p">{"]"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"timeout"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="mf">{"30.0"}</span><span className="p">{","}</span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

Configuration for SDK retry behavior.

Examples:

```python theme={null}
from typesafe_sdk import RetryPolicy, TypeSafeClient

client = TypeSafeClient(
    retry=RetryPolicy(
        max_retries=3, timeout=10.0, http_statuses={429, 500, 502, 503, 504}
    )
)
```

<h3 id="typesafe_sdk.RetryPolicy.max_retries">
  max\_retries
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"max_retries"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#int">
      {"int"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="mi">
    {"2"}
  </span>

  {"\n"}
</SdkSignature>

Maximum retries after the initial attempt; `0` disables retries.

<h3 id="typesafe_sdk.RetryPolicy.backoff_initial">
  backoff\_initial
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"backoff_initial"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="mf">
    {"0.5"}
  </span>

  {"\n"}
</SdkSignature>

First backoff delay in seconds, doubled each attempt up to `backoff_max`; zero disables backoff.

<h3 id="typesafe_sdk.RetryPolicy.backoff_max">
  backoff\_max
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"backoff_max"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="mf">
    {"5.0"}
  </span>

  {"\n"}
</SdkSignature>

Maximum backoff delay in seconds; zero disables backoff.

<h3 id="typesafe_sdk.RetryPolicy.backoff_jitter">
  backoff\_jitter
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"backoff_jitter"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="mf">
    {"0.25"}
  </span>

  {"\n"}
</SdkSignature>

Fraction of each backoff delay randomly subtracted, between 0 and 1.

<h3 id="typesafe_sdk.RetryPolicy.http_statuses">
  http\_statuses
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">{"http_statuses"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/functions.html#int">{"int"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/dataclasses.html#dataclasses.field">{"field"}</a></span><span className="p">{"("}</span>{"\n"}{"    "}<span className="n">{"default_factory"}</span><span className="o">{"="}</span><span className="k">{"lambda"}</span><span className="p">{":"}</span>{" "}<span className="p">{"{"}</span>{"\n"}{"        "}<span className="mi">{"408"}</span><span className="p">{","}</span>{"\n"}{"        "}<span className="mi">{"429"}</span><span className="p">{","}</span>{"\n"}{"        "}<span className="o">{"*"}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#range">{"range"}</a></span><span className="p">{"("}</span><span className="mi">{"500"}</span><span className="p">{","}</span>{" "}<span className="mi">{"600"}</span><span className="p">{"),"}</span>{"\n"}{"    "}<span className="p">{"}"}</span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

HTTP status codes that are retried.

<h3 id="typesafe_sdk.RetryPolicy.respect_retry_after">
  respect\_retry\_after
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"respect_retry_after"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#bool">
      {"bool"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="kc">
    {"True"}
  </span>

  {"\n"}
</SdkSignature>

Whether to honor `Retry-After` and `retry-after-ms` response headers.

<h3 id="typesafe_sdk.RetryPolicy.api_connection_error">
  api\_connection\_error
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"api_connection_error"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#bool">
      {"bool"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="kc">
    {"True"}
  </span>

  {"\n"}
</SdkSignature>

Whether to retry `TypeSafeAPIConnectionError`, raised when the request cannot reach or read from the server.

<h3 id="typesafe_sdk.RetryPolicy.api_timeout_error">
  api\_timeout\_error
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"api_timeout_error"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#bool">
      {"bool"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="kc">
    {"True"}
  </span>

  {"\n"}
</SdkSignature>

Whether to retry `TypeSafeAPITimeoutError`, raised when the request exceeds its timeout.

<h3 id="typesafe_sdk.RetryPolicy.exceptions">
  exceptions
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">{"exceptions"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/functions.html#type">{"type"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/exceptions.html#BaseException">{"BaseException"}</a></span><span className="p">{"]]"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/dataclasses.html#dataclasses.field">{"field"}</a></span><span className="p">{"("}</span>{"\n"}{"    "}<span className="n">{"default_factory"}</span><span className="o">{"="}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#set">{"set"}</a></span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

Additional exception types that trigger a retry, on top of the built-in rules.

<h3 id="typesafe_sdk.RetryPolicy.predicate">
  predicate
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">{"predicate"}</span><span className="p">{":"}</span>{" "}<span className="p">{"("}</span>{"\n"}{"    "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Callable">{"Callable"}</a></span><span className="p">{"[["}</span><span className="n"><a href="https://docs.python.org/3/builtins/exceptions.html#BaseException">{"BaseException"}</a></span><span className="p">{"],"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#bool">{"bool"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{"\n"}<span className="p">{")"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span>{"\n"}
</SdkSignature>

An optional predicate called with the raised exception; returning `True` triggers a retry in addition to the other rules.

<h3 id="typesafe_sdk.RetryPolicy.timeout">
  timeout
</h3>

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">
    {"timeout"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
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

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="mf">
    {"30.0"}
  </span>

  {"\n"}
</SdkSignature>

Total retry budget in seconds per SDK call, including the initial attempt and delays; `None` disables the limit.

Stops before a retry whose delay would reach or exceed the budget, re-raising the last error.
