> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Asynchronous client

> Use AsyncTypeSafeClient to ask questions, list models, and configure asynchronous TypeSafe API requests.

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

<a id="asynchronous-client" />

<h2 id="typesafe_sdk.AsyncTypeSafeClient">
  typesafe\_sdk.AsyncTypeSafeClient
</h2>

<SdkSignature>
  <span className="nf">{"AsyncTypeSafeClient"}</span><span className="p">{"("}</span>{"\n"}{"    "}<span className="o">{"*"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"api_key"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"model"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"retry"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">{"RetryPolicy"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"timeout"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="n">{"httpx2"}</span><span className="o">{"."}</span><span className="n">{"Timeout"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"headers"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">{"Mapping"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"transport"}</span><span className="p">{":"}</span>{" "}<span className="n">{"httpx2"}</span><span className="o">{"."}</span><span className="n">{"AsyncBaseTransport"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"http_client"}</span><span className="p">{":"}</span>{" "}<span className="n">{"httpx2"}</span><span className="o">{"."}</span><span className="n"><a href="https://pydantic.dev/docs/httpx2/api/api/#httpx2.AsyncClient">{"AsyncClient"}</a></span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"base_url"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

Create an asynchronous HTTP client for [TypeSafe AI API](https://typesafe.ai).

Explicit options take precedence over environment variables; empty or whitespace-only environment values are ignored.

<Tip>
  **Logging setup**

  The SDK logs to the `typesafe_sdk` logger; configure it through standard logging, or set `TYPESAFE_LOG_LEVEL` (`debug`, `info`, ...) for a quick default. Secret headers are redacted from log output; request and response bodies are not.
</Tip>

Parameters:

* **`api_key`** (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a> | None</code>, default: `None` ) –

  Required API key; may be set via the `TYPESAFE_API_KEY` environment variable.
* **`model`** (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a> | None</code>, default: `None` ) –

  Model name; may be set via the `TYPESAFE_DEFAULT_MODEL` environment variable.
* **`retry`** (<code><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">RetryPolicy</a> | None</code>, default: `None` ) –

  A `RetryPolicy` controlling retry behavior; see `RetryPolicy` for the available options and their defaults. Pass `RetryPolicy(max_retries=0)` to disable retries.
* **`timeout`** (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a> | httpx2.Timeout | None</code>, default: `None` ) –

  Timeout for HTTP operations. Inherits `http_client.timeout` when supplied, otherwise the SDK default.
* **`headers`** (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>] | None</code>, default: `None` ) –

  Additional request headers to set.
* **`transport`** (`httpx2.AsyncBaseTransport | None`, default: `None` ) –

  Optional custom HTTP transport, closed when this SDK client closes.
* **`http_client`** (<code>httpx2.<a href="https://pydantic.dev/docs/httpx2/api/api/#httpx2.AsyncClient">AsyncClient</a> | None</code>, default: `None` ) –

  Optional `httpx2.AsyncClient`; mutually exclusive with `transport`. Closed when this SDK client closes.
* **`base_url`** (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a> | None</code>, default: `None` ) –

  API root; may be set via the `TYPESAFE_BASE_URL` environment variable.

Raises:

* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeError">TypeSafeError</a></code> –

  The API key is missing or the timeout is invalid.
* <code><a href="https://docs.python.org/3/builtins/exceptions.html#ValueError">ValueError</a></code> –

  Both `transport` and `http_client` are supplied.

Examples:

```python theme={null}
import asyncio

from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul


async def main() -> None:
    async with AsyncTypeSafeClient() as client:
        result = await client.system_one(
            state="I was charged twice. Please help.",
            questions={
                "billing": Noul(instructions="Is this about billing?"),
                "tone": Choice(
                    instructions="What is the tone?",
                    criteria={"calm": None, "angry": None},
                ),
            },
        )
        assert 0 <= result.nouls["billing"].noul <= 1
        assert result.choices["tone"].choice in {"calm", "angry"}


asyncio.run(main())
```

<h3 id="typesafe_sdk.AsyncTypeSafeClient.models">
  models
</h3>

`cached` `property`

<SdkSignature>
  <span className="n">
    {"models"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/clients/async/models#typesafe_sdk.AsyncModels">
      {"AsyncModels"}
    </a>
  </span>

  {"\n"}
</SdkSignature>

An accessor for the Models API resource.

Examples:

```python theme={null}
async def main() -> None:
    async with AsyncTypeSafeClient() as client:
        models = await client.models.list()
```

<h3 id="typesafe_sdk.AsyncTypeSafeClient.system_one">
  system\_one
</h3>

`async`

<SdkSignature>
  <span className="nf">{"system_one"}</span><span className="p">{"("}</span>{"\n"}{"    "}<span className="n">{"state"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">{"JSONContent"}</a></span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"questions"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">{"Mapping"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.Question">{"Question"}</a></span><span className="p">{"],"}</span>{"\n"}{"    "}<span className="o">{"*"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"model"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"retry"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">{"RetryPolicy"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"timeout"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="n">{"httpx2"}</span><span className="o">{"."}</span><span className="n">{"Timeout"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"extra_headers"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">{"Mapping"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{"]"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"extra_body"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">{"Mapping"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="/sdk/python/api/types/common#typesafe_sdk.JSONValue">{"JSONValue"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span><span className="p">{"]"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}<span className="p">{")"}</span>{" "}<span className="o">{"->"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.SystemOneResponse">{"SystemOneResponse"}</a></span>{"\n"}
</SdkSignature>

Answer named questions about text or structured state.

See [System One](https://docs.typesafe.ai/concepts/system-one) for details.

Parameters:

* **`state`** (<code><a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a></code>) –

  Text, a JSON object, or an array to evaluate. See [state](https://docs.typesafe.ai/concepts/state) for details.
* **`questions`** (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="/sdk/python/api/types/questions#typesafe_sdk.Question">Question</a>]</code>) –

  Nonempty mapping of names to question objects or raw dictionaries.
* **`model`** (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a> | None</code>, default: `None` ) –

  Model override; `None` inherits the client default.
* **`retry`** (<code><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">RetryPolicy</a> | None</code>, default: `None` ) –

  An optional retry policy to override the client-level value for this call only.
* **`timeout`** (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a> | httpx2.Timeout | None</code>, default: `None` ) –

  An optional timeout for http operations to override the client-level value for this call only, in seconds.
* **`extra_headers`** (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>] | None</code>, default: `None` ) –

  Additional request headers to set.
* **`extra_body`** (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="/sdk/python/api/types/common#typesafe_sdk.JSONValue">JSONValue</a> | None] | None</code>, default: `None` ) –

  Additional top-level request-body fields, shallow-merged over the body after `state`, `model`, and `questions` are set. Merging is last-write-wins: a key that collides with `state`, `model`, or `questions` overrides it, and object values are replaced rather than deep-merged.

Returns:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.SystemOneResponse">SystemOneResponse</a></code> –

  Answers keyed by question name, with model and token usage details.

Raises:

* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeError">TypeSafeError</a></code> –

  Questions are empty or a score question's criteria list is empty.
* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code> –

  The server returns an unsuccessful HTTP response after any retries.
* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIConnectionError">TypeSafeAPIConnectionError</a></code> –

  The request cannot connect or times out after any retries.

Examples:

Create questions with named arguments:

```python theme={null}
async def main() -> None:
    async with AsyncTypeSafeClient() as client:
        result = await client.system_one(
            state="I was charged twice. Please help.",
            questions={
                "billing": Noul(instructions="Is this about billing?"),
                "tone": Choice(
                    instructions="What is the tone?",
                    criteria={"calm": None, "angry": None},
                ),
            },
        )
        assert 0 <= result.nouls["billing"].noul <= 1
        assert result.choices["tone"].choice in {"calm", "angry"}
```

Pass questions as dictionaries:

```python theme={null}
async def main() -> None:
    async with AsyncTypeSafeClient() as client:
        result = await client.system_one(
            state={"message": "I was charged twice. Please help."},
            questions={
                "billing": {"type": "noul", "instructions": "Is this about billing?"},
                "tone": {
                    "type": "choice",
                    "instructions": "What is the tone?",
                    "criteria": {"calm": None, "angry": None},
                },
            },
        )
        assert 0 <= result.nouls["billing"].noul <= 1
        assert result.choices["tone"].choice in {"calm", "angry"}
```

<h3 id="typesafe_sdk.AsyncTypeSafeClient.aclose">
  aclose
</h3>

`async`

```python theme={null}
aclose() -> None
```

Release network resources and close the underlying HTTP client, including a supplied one.
