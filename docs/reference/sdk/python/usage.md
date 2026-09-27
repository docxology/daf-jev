> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Usage

> Guides and patterns for working with the TypeSafe Python SDK.

<a id="usage" />

<h2 id="calling-the-system-one-api">
  Calling the System One API
</h2>

<Tabs>
  <Tab title="Async">
    ```python theme={null}
    import asyncio

    from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score


    async def main() -> None:
        async with AsyncTypeSafeClient() as client:
            result = await client.system_one(
                "I was charged twice. Please help ASAP.",
                {
                    "billing": Noul(instructions="Is this about billing?"),
                    "tone": Choice(
                        instructions="What is the tone?",
                        criteria={"calm": None, "angry": None},
                    ),
                    "urgency": Score(
                        instructions="How urgent is this?",
                        criteria=["low", "medium", "high"],
                    ),
                },
            )
            print(
                result.nouls["billing"].noul,
                result.choices["tone"].choice,
                result.scores["urgency"].score,
            )


    asyncio.run(main())
    ```
  </Tab>

  <Tab title="Sync">
    ```python theme={null}
    from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

    client = TypeSafeClient()
    state = "I was charged twice. Please help ASAP."
    questions = {
        "billing": Noul(instructions="Is this about billing?"),
        "tone": Choice(
            instructions="What is the tone?", criteria={"calm": None, "angry": None}
        ),
        "urgency": Score(
            instructions="How urgent is this?", criteria=["low", "medium", "high"]
        ),
    }
    result = client.system_one(state, questions)
    print(
        result.nouls["billing"].noul,
        result.choices["tone"].choice,
        result.scores["urgency"].score,
    )
    ```
  </Tab>
</Tabs>

<h2 id="typed-system_one-responses">
  Typed <code>system\_one</code> responses
</h2>

It is possible to provide a response model to `system_one` to make using the response more *type-safe*:

```python theme={null}
from typesafe_sdk import Noul, NoulAnswer, SystemOneResponse, TypeSafeClient


class BillingResponse(SystemOneResponse):
    billing: NoulAnswer


with TypeSafeClient() as client:
    result = client.system_one(
        "I was charged twice.",
        {"billing": Noul(instructions="Is this about billing?")},
        response_model=BillingResponse,
    )
    assert 0 <= result.billing.noul <= 1
    assert result.billing == result.nouls["billing"]
    print(result.request_id)
```

<h3 id="custom-response-types">
  Custom response types
</h3>

It is also possible to define a completely new response model without inheriting from `SystemOneResponse`:

```python theme={null}
from pydantic import BaseModel

from typesafe_sdk import Noul, NoulAnswer, TypeSafeClient


class BillingAnswers(BaseModel):
    billing: NoulAnswer


class BillingResponse(BaseModel):
    answers: BillingAnswers


result = TypeSafeClient().system_one(
    "I was charged twice.",
    {"billing": Noul(instructions="Is this about billing?")},
    response_model=BillingResponse,
)
assert 0 <= result.answers.billing.noul <= 1
```

<h2 id="choosing-a-model">
  Choosing a model
</h2>

Inspect the available models:

```python theme={null}
from typesafe_sdk import TypeSafeClient

print(TypeSafeClient().models.list())
```

Select the model when constructing a client:

```python theme={null}
client = TypeSafeClient(model="jev")
```

See the [Models resource reference](/sdk/python/api/clients/sync#models-resource) for details.

<h2 id="configuring-the-base-url">
  Configuring the base URL
</h2>

In order to use the SDK with a different API url, set `base_url` on the client or the `TYPESAFE_BASE_URL` environment variable.

For example, connect through an AI gateway using its API key and model ID:

<Tabs>
  <Tab title="OpenRouter">
    Use an OpenRouter API key and an [OpenRouter model ID](https://openrouter.ai/~typesafe/jev-latest/):

    skip: next

    ```python theme={null}
    import os

    from typesafe_sdk import Noul, TypeSafeClient

    with TypeSafeClient(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api",
        model="~typesafe/jev-latest",
    ) as client:
        result = client.system_one(
            "I was charged twice.",
            {"billing": Noul(instructions="Is this about billing?")},
        )
        print(result.nouls["billing"].noul)
    ```
  </Tab>

  <Tab title="Vercel AI Gateway">
    [Vercel's TypeSafe-compatible API](https://vercel.com/docs/ai-gateway/sdks-and-apis/typesafe) can be used with the SDK:

    skip: next

    ```python theme={null}
    import os

    from typesafe_sdk import Noul, TypeSafeClient

    with TypeSafeClient(
        api_key=os.environ["AI_GATEWAY_API_KEY"],
        base_url="https://ai-gateway.vercel.sh/typesafe",
        model="typesafe-ai/jev",
    ) as client:
        result = client.system_one(
            "I was charged twice.",
            {"billing": Noul(instructions="Is this about billing?")},
        )
        print(result.nouls["billing"].noul)
    ```
  </Tab>
</Tabs>

This requires the alternative API to follow the [TypeSafe OpenAPI spec](https://api.typesafe.ai/docs/).

<h2 id="retries">
  Retries
</h2>

Pass a custom [`RetryPolicy`](/sdk/python/api/retries) as `retry` on the client or per call. Invalid API keys raise `TypeSafeError` during client creation, before any request or retry.

<Tabs>
  <Tab title="Client">
    ```python theme={null}
    from typesafe_sdk import RetryPolicy, TypeSafeClient

    client = TypeSafeClient(retry=RetryPolicy(max_retries=3, backoff_max=0.2, timeout=1.0))
    ```
  </Tab>

  <Tab title="Per-call">
    ```python theme={null}
    from typesafe_sdk import RetryPolicy

    client.system_one(
        state, questions, retry=RetryPolicy(max_retries=3, backoff_max=0.2, timeout=1.0)
    )
    ```
  </Tab>
</Tabs>

<h2 id="error-handling">
  Error handling
</h2>

Handle [exceptions](/sdk/python/api/exceptions) raised by the SDK:

```python theme={null}
from typesafe_sdk import TypeSafeAPIError

try:
    client.system_one(state, questions)
except TypeSafeAPIError as error:
    print(error.status, error.request_id)
```

<h2 id="logging">
  Logging
</h2>

The SDK logs to the `typesafe_sdk` logger. Configure it according to [standard logging](https://docs.python.org/3/library/logging.html) guide:

```python theme={null}
import logging

logging.getLogger("typesafe_sdk").setLevel(logging.DEBUG)
```

Or set `TYPESAFE_LOG_LEVEL` to one of `debug`, `info`, `warning`, `error`, or `off` before importing the SDK.

`info` logs one summary line per request; `debug` also logs request and response headers and bodies. Secret headers — authorization, API keys, cookies, and any header whose name contains `token` or `secret` — are redacted from log output. Request and response bodies are **not** redacted.

<h2 id="environment-variables">
  Environment variables
</h2>

The SDK reads and uses the following environment variables:

| Variable                 | Configures                                          | Default                   |
| ------------------------ | --------------------------------------------------- | ------------------------- |
| `TYPESAFE_API_KEY`       | API key (required)                                  | —                         |
| `TYPESAFE_BASE_URL`      | API root URL                                        | `https://api.typesafe.ai` |
| `TYPESAFE_DEFAULT_MODEL` | Default model                                       | `jev-latest`              |
| `TYPESAFE_LOG_LEVEL`     | `typesafe_sdk` logger level, applied once at import | unset                     |

See the [constants reference](/sdk/python/api/constants) for SDK defaults.

API keys supplied through `api_key` or `TYPESAFE_API_KEY` have leading and trailing whitespace stripped, including newlines from key files. Empty keys, internal whitespace, control characters, and non-ASCII characters are rejected before sending a request. An explicitly empty key does not fall back to the environment.

<h2 id="forward-compatibility">
  Forward compatibility
</h2>

The SDK keeps working as the TypeSafe API evolves, so you can adopt new API features before an SDK release adds first-class support for them.

<h3 id="extra-request-fields">
  Extra request fields
</h3>

Send additional API request fields with [`extra_body`](/sdk/python/api/clients/sync). The `beam_width` field below is illustrative; only send fields supported by the API.

skip: next

```python theme={null}
from typesafe_sdk import Noul, TypeSafeClient

with TypeSafeClient() as client:
    client.system_one(
        "I was charged twice.",
        {"billing": Noul(instructions="About billing?")},
        extra_body={"beam_width": 4},
    )
```

<h3 id="raw-question-dictionaries">
  Raw question dictionaries
</h3>

```python theme={null}
from typesafe_sdk import TypeSafeClient

with TypeSafeClient() as client:
    client.system_one(
        "I was charged twice.",
        {"billing": {"type": "noul", "instructions": "About billing?", "weight": 2}},
    )
```

<Tip>
  **Tip**

  Unknown fields are a forward-compatibility escape hatch. Ignore their type-checking errors and prefer upgrading the SDK instead.
</Tip>

<h3 id="unknown-answer-kinds">
  Unknown answer kinds
</h3>

The SDK logs a warning and skips unrecognized answer kinds. Use `raw_http_response` to inspect the complete API response, including those answers:

```python theme={null}
from typesafe_sdk import Noul, TypeSafeClient

result = TypeSafeClient().system_one(
    "I was charged twice.",
    {"billing": Noul(instructions="Is this about billing?")},
)
raw_answers = result.raw_http_response.json()["answers"]
```

<h3 id="unknown-response-fields">
  Unknown response fields
</h3>

Unknown extra fields on recognized responses are ignored.
