> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Models resource

> List the models available to your account through the synchronous client's Models resource.

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

<a id="models-resource" />

Reached through [`TypeSafeClient.models`](/sdk/python/api/clients/sync/client).

<h2 id="typesafe_sdk.Models">
  typesafe\_sdk.Models
</h2>

Access to the models available to the account, reached through `TypeSafeClient.models`.

<h3 id="typesafe_sdk.Models.list">
  list
</h3>

<SdkSignature>
  <span className="nf">{"list"}</span><span className="p">{"("}</span>{"\n"}{"    "}<span className="o">{"*"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"retry"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">{"RetryPolicy"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"timeout"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#float">{"float"}</a></span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="n">{"httpx2"}</span><span className="o">{"."}</span><span className="n">{"Timeout"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"extra_headers"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">{"Mapping"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{"]"}</span>{"\n"}{"    "}<span className="o">{"|"}</span>{" "}<span className="kc">{"None"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="kc">{"None"}</span><span className="p">{","}</span>{"\n"}<span className="p">{")"}</span>{" "}<span className="o">{"->"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.ListModelsResponse">{"ListModelsResponse"}</a></span>{"\n"}
</SdkSignature>

List the models available to the account.

Parameters:

* **`retry`** (<code><a href="/sdk/python/api/retries#typesafe_sdk.RetryPolicy">RetryPolicy</a> | None</code>, default: `None` ) –

  An optional retry policy to override the client-level value for this call only.
* **`timeout`** (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a> | httpx2.Timeout | None</code>, default: `None` ) –

  Per-operation timeout override; `None` inherits the client setting.
* **`extra_headers`** (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>] | None</code>, default: `None` ) –

  Overrides for additional request headers; authentication, SDK identification, and `Accept` remain protected.

Returns:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ListModelsResponse">ListModelsResponse</a></code> –

  A `ListModelsResponse` whose `models` holds each model's name, description,
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ListModelsResponse">ListModelsResponse</a></code> –

  and release date.

Raises:

* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIError">TypeSafeAPIError</a></code> –

  The server returns an unsuccessful HTTP response after any retries.
* <code><a href="/sdk/python/api/exceptions#typesafe_sdk.TypeSafeAPIConnectionError">TypeSafeAPIConnectionError</a></code> –

  The request cannot connect or times out after any retries.

Examples:

```python theme={null}
from typesafe_sdk import TypeSafeClient

with TypeSafeClient() as client:
    models = client.models.list()
```
