> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Answers and responses

> Read answers, confidence scores, token usage, and available models returned by the TypeSafe API.

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

<a id="answers-and-responses" />

<h2 id="response">
  Response
</h2>

<h2 id="typesafe_sdk.SystemOneResponse">
  typesafe\_sdk.SystemOneResponse
</h2>

`pydantic-model`

Bases: `Response`

Answers grouped by question type with model and usage metadata.

See [System One](https://docs.typesafe.ai/concepts/system-one) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-1">
    ```json theme={null}
    {
      "$defs": {
        "ChoiceAnswer": {
          "description": "A selected label and its probabilities.\n\nSee the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.",
          "properties": {
            "type": {
              "const": "choice",
              "default": "choice",
              "title": "Type",
              "type": "string"
            },
            "choice": {
              "description": "The name of the choice with the highest probability among the question's criteria.",
              "examples": [
                "angry"
              ],
              "title": "Choice",
              "type": "string"
            },
            "confidence": {
              "description": "Confidence in the selected choice, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain selections for review.",
              "examples": [
                0.9
              ],
              "title": "Confidence",
              "type": "number"
            },
            "probabilities": {
              "additionalProperties": {
                "type": "number"
              },
              "description": "Probability of each choice in criteria, keyed by choice name, from 0 to 1. Shows how likely the alternatives are; values sum to approximately 1.",
              "examples": [
                {
                  "angry": 0.8,
                  "calm": 0.1,
                  "excited": 0.1
                }
              ],
              "title": "Probabilities",
              "type": "object"
            }
          },
          "required": [
            "choice",
            "confidence",
            "probabilities"
          ],
          "title": "ChoiceAnswer",
          "type": "object"
        },
        "NoulAnswer": {
          "description": "A yes/no answer.\n\nSee the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.",
          "properties": {
            "type": {
              "const": "noul",
              "default": "noul",
              "title": "Type",
              "type": "string"
            },
            "noul": {
              "description": "Probability of a yes answer or a true statement, from 0 to 1. Values near 1 favor yes or true, values near 0 favor no or false, and values near 0.5 indicate uncertainty.",
              "examples": [
                0.98
              ],
              "title": "Noul",
              "type": "number"
            }
          },
          "required": [
            "noul"
          ],
          "title": "NoulAnswer",
          "type": "object"
        },
        "ScoreAnswer": {
          "description": "An expected score with its rubric and probabilities.\n\nSee the [score primitive](https://docs.typesafe.ai/primitives/score) for details.",
          "properties": {
            "type": {
              "const": "score",
              "default": "score",
              "title": "Type",
              "type": "string"
            },
            "score": {
              "description": "Expected score: the probability-weighted average of the rubric levels. May fall between integer levels.",
              "examples": [
                1.7
              ],
              "title": "Score",
              "type": "number"
            },
            "confidence": {
              "description": "Confidence in the score, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain ratings for review.",
              "examples": [
                0.9
              ],
              "title": "Confidence",
              "type": "number"
            },
            "legend": {
              "additionalProperties": {
                "anyOf": [
                  {
                    "type": "string"
                  },
                  {
                    "additionalProperties": true,
                    "type": "object"
                  },
                  {
                    "items": {},
                    "type": "array"
                  }
                ]
              },
              "title": "Legend",
              "type": "object"
            },
            "probabilities": {
              "additionalProperties": {
                "type": "number"
              },
              "title": "Probabilities",
              "type": "object"
            }
          },
          "required": [
            "score",
            "confidence",
            "legend",
            "probabilities"
          ],
          "title": "ScoreAnswer",
          "type": "object"
        },
        "Usage": {
          "description": "Token counts for a request, when reported by the API.",
          "properties": {
            "input_tokens": {
              "anyOf": [
                {
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Input Tokens"
            },
            "output_tokens": {
              "anyOf": [
                {
                  "type": "integer"
                },
                {
                  "type": "null"
                }
              ],
              "default": null,
              "title": "Output Tokens"
            }
          },
          "title": "Usage",
          "type": "object"
        }
      },
      "description": "Answers grouped by question type with model and usage metadata.\n\nSee [System One](https://docs.typesafe.ai/concepts/system-one) for details.",
      "properties": {
        "model": {
          "title": "Model",
          "type": "string"
        },
        "usage": {
          "$ref": "#/$defs/Usage"
        },
        "answers": {
          "additionalProperties": {
            "discriminator": {
              "mapping": {
                "choice": "#/$defs/ChoiceAnswer",
                "noul": "#/$defs/NoulAnswer",
                "score": "#/$defs/ScoreAnswer"
              },
              "propertyName": "type"
            },
            "oneOf": [
              {
                "$ref": "#/$defs/NoulAnswer"
              },
              {
                "$ref": "#/$defs/ChoiceAnswer"
              },
              {
                "$ref": "#/$defs/ScoreAnswer"
              }
            ]
          },
          "title": "Answers",
          "type": "object"
        }
      },
      "required": [
        "model",
        "usage"
      ],
      "title": "SystemOneResponse",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Config:

* `extra`: `ignore`
* `frozen`: `True`
* `strict`: `True`

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.SystemOneResponse.model">model</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.SystemOneResponse.usage">usage</a></code> (<code><a href="/sdk/python/api/types/responses#typesafe_sdk.Usage">Usage</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.SystemOneResponse.answers">answers</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">dict</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="/sdk/python/api/types/responses#typesafe_sdk.Answer">Answer</a>]</code>)

<h3 id="typesafe_sdk.SystemOneResponse.request_id">
  request\_id
</h3>

`cached` `property`

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

  {"\n"}
</SdkSignature>

The `x-typesafe-request-id` response header.

<h3 id="typesafe_sdk.SystemOneResponse.raw_http_response">
  raw\_http\_response
</h3>

`property`

```python theme={null}
raw_http_response: httpx2.Response
```

The underlying `httpx2.Response`, exposing status, headers, and body.

<h3 id="typesafe_sdk.SystemOneResponse.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h3 id="typesafe_sdk.SystemOneResponse.model">
  model
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"model"}
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

  {"\n"}
</SdkSignature>

The model used to answer the request.

<h3 id="typesafe_sdk.SystemOneResponse.usage">
  usage
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"usage"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.Usage">
      {"Usage"}
    </a>
  </span>

  {"\n"}
</SdkSignature>

Token usage for the request.

<h3 id="typesafe_sdk.SystemOneResponse.answers">
  answers
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"answers"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.Answer">
      {"Answer"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

All answer objects keyed by question name.

<h3 id="typesafe_sdk.SystemOneResponse.nouls">
  nouls
</h3>

`cached` `property`

<SdkSignature>
  <span className="n">
    {"nouls"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.NoulAnswer">
      {"NoulAnswer"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Yes/no answers keyed by question name.

<h3 id="typesafe_sdk.SystemOneResponse.choices">
  choices
</h3>

`cached` `property`

<SdkSignature>
  <span className="n">
    {"choices"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer">
      {"ChoiceAnswer"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Choice answers keyed by question name.

<h3 id="typesafe_sdk.SystemOneResponse.scores">
  scores
</h3>

`cached` `property`

<SdkSignature>
  <span className="n">
    {"scores"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer">
      {"ScoreAnswer"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Score answers keyed by question name.

<h2 id="typesafe_sdk.Usage">
  typesafe\_sdk.Usage
</h2>

`pydantic-model`

Bases: `wire.Usage`

Token counts for a request, when reported by the API.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-2">
    ```json theme={null}
    {
      "description": "Token counts for a request, when reported by the API.",
      "properties": {
        "input_tokens": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Input Tokens"
        },
        "output_tokens": {
          "anyOf": [
            {
              "type": "integer"
            },
            {
              "type": "null"
            }
          ],
          "default": null,
          "title": "Output Tokens"
        }
      },
      "title": "Usage",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Config:

* `extra`: `ignore`
* `frozen`: `True`
* `strict`: `True`

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.Usage.input_tokens">input\_tokens</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#int">int</a> | None</code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.Usage.output_tokens">output\_tokens</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#int">int</a> | None</code>)

<h3 id="typesafe_sdk.Usage.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h3 id="typesafe_sdk.Usage.input_tokens">
  input\_tokens
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"input_tokens"}
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

  <span className="kc">
    {"None"}
  </span>

  {"\n"}
</SdkSignature>

Number of input tokens used, or `None` when the API did not report it.

<h3 id="typesafe_sdk.Usage.output_tokens">
  output\_tokens
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"output_tokens"}
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

  <span className="kc">
    {"None"}
  </span>

  {"\n"}
</SdkSignature>

Number of output tokens used, or `None` when the API did not report it.

<h2 id="answers">
  Answers
</h2>

<h2 id="typesafe_sdk.NoulAnswer">
  typesafe\_sdk.NoulAnswer
</h2>

`pydantic-model`

Bases: `wire.NoulAnswer`

A yes/no answer.

See the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-3">
    ```json theme={null}
    {
      "description": "A yes/no answer.\n\nSee the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.",
      "properties": {
        "type": {
          "const": "noul",
          "default": "noul",
          "title": "Type",
          "type": "string"
        },
        "noul": {
          "description": "Probability of a yes answer or a true statement, from 0 to 1. Values near 1 favor yes or true, values near 0 favor no or false, and values near 0.5 indicate uncertainty.",
          "examples": [
            0.98
          ],
          "title": "Noul",
          "type": "number"
        }
      },
      "required": [
        "noul"
      ],
      "title": "NoulAnswer",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Config:

* `extra`: `ignore`
* `frozen`: `True`
* `strict`: `True`

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.NoulAnswer.noul">noul</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a></code>)
* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['noul']</code>)

<h3 id="typesafe_sdk.NoulAnswer.noul">
  noul
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"noul"}
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

  {"\n"}
</SdkSignature>

Probability of a yes answer or a true statement, from 0 to 1. Values near 1 favor yes or true, values near 0 favor no or false, and values near 0.5 indicate uncertainty.

<h3 id="typesafe_sdk.NoulAnswer.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h2 id="typesafe_sdk.ChoiceAnswer">
  typesafe\_sdk.ChoiceAnswer
</h2>

`pydantic-model`

Bases: `wire.ChoiceAnswer`

A selected label and its probabilities.

See the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-4">
    ```json theme={null}
    {
      "description": "A selected label and its probabilities.\n\nSee the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.",
      "properties": {
        "type": {
          "const": "choice",
          "default": "choice",
          "title": "Type",
          "type": "string"
        },
        "choice": {
          "description": "The name of the choice with the highest probability among the question's criteria.",
          "examples": [
            "angry"
          ],
          "title": "Choice",
          "type": "string"
        },
        "confidence": {
          "description": "Confidence in the selected choice, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain selections for review.",
          "examples": [
            0.9
          ],
          "title": "Confidence",
          "type": "number"
        },
        "probabilities": {
          "additionalProperties": {
            "type": "number"
          },
          "description": "Probability of each choice in criteria, keyed by choice name, from 0 to 1. Shows how likely the alternatives are; values sum to approximately 1.",
          "examples": [
            {
              "angry": 0.8,
              "calm": 0.1,
              "excited": 0.1
            }
          ],
          "title": "Probabilities",
          "type": "object"
        }
      },
      "required": [
        "choice",
        "confidence",
        "probabilities"
      ],
      "title": "ChoiceAnswer",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Config:

* `extra`: `ignore`
* `frozen`: `True`
* `strict`: `True`

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer.choice">choice</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer.confidence">confidence</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer.probabilities">probabilities</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">dict</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="https://docs.python.org/3/builtins/functions.html#float">float</a>]</code>)
* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['choice']</code>)

<h3 id="typesafe_sdk.ChoiceAnswer.choice">
  choice
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"choice"}
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

  {"\n"}
</SdkSignature>

The name of the choice with the highest probability among the question's criteria.

<h3 id="typesafe_sdk.ChoiceAnswer.confidence">
  confidence
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"confidence"}
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

  {"\n"}
</SdkSignature>

Confidence in the selected choice, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain selections for review.

<h3 id="typesafe_sdk.ChoiceAnswer.probabilities">
  probabilities
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"probabilities"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#str">
      {"str"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Probability of each choice in criteria, keyed by choice name, from 0 to 1. Shows how likely the alternatives are; values sum to approximately 1.

<h3 id="typesafe_sdk.ChoiceAnswer.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h2 id="typesafe_sdk.ScoreAnswer">
  typesafe\_sdk.ScoreAnswer
</h2>

`pydantic-model`

Bases: `wire.ScoreAnswer`

An expected score with its rubric and probabilities.

See the [score primitive](https://docs.typesafe.ai/primitives/score) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-5">
    ```json theme={null}
    {
      "description": "An expected score with its rubric and probabilities.\n\nSee the [score primitive](https://docs.typesafe.ai/primitives/score) for details.",
      "properties": {
        "type": {
          "const": "score",
          "default": "score",
          "title": "Type",
          "type": "string"
        },
        "score": {
          "description": "Expected score: the probability-weighted average of the rubric levels. May fall between integer levels.",
          "examples": [
            1.7
          ],
          "title": "Score",
          "type": "number"
        },
        "confidence": {
          "description": "Confidence in the score, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain ratings for review.",
          "examples": [
            0.9
          ],
          "title": "Confidence",
          "type": "number"
        },
        "legend": {
          "additionalProperties": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "additionalProperties": true,
                "type": "object"
              },
              {
                "items": {},
                "type": "array"
              }
            ]
          },
          "title": "Legend",
          "type": "object"
        },
        "probabilities": {
          "additionalProperties": {
            "type": "number"
          },
          "title": "Probabilities",
          "type": "object"
        }
      },
      "required": [
        "score",
        "confidence",
        "legend",
        "probabilities"
      ],
      "title": "ScoreAnswer",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Config:

* `extra`: `ignore`
* `frozen`: `True`
* `strict`: `True`

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer.score">score</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer.confidence">confidence</a></code> (<code><a href="https://docs.python.org/3/builtins/functions.html#float">float</a></code>)
* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['score']</code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer.legend">legend</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">dict</a>\[<a href="https://docs.python.org/3/builtins/functions.html#int">int</a>, <a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a> | <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">dict</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="https://docs.python.org/3/library/typing.html#typing.Any">Any</a>] | <a href="https://docs.python.org/3/builtins/stdtypes.html#list">list</a>\[<a href="https://docs.python.org/3/library/typing.html#typing.Any">Any</a>]]</code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer.probabilities">probabilities</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">dict</a>\[<a href="https://docs.python.org/3/builtins/functions.html#int">int</a>, <a href="https://docs.python.org/3/builtins/functions.html#float">float</a>]</code>)

<h3 id="typesafe_sdk.ScoreAnswer.score">
  score
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"score"}
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

  {"\n"}
</SdkSignature>

Expected score: the probability-weighted average of the rubric levels. May fall between integer levels.

<h3 id="typesafe_sdk.ScoreAnswer.confidence">
  confidence
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"confidence"}
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

  {"\n"}
</SdkSignature>

Confidence in the score, from 0 to 1. Higher values indicate greater certainty; use lower values to flag uncertain ratings for review.

<h3 id="typesafe_sdk.ScoreAnswer.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h3 id="typesafe_sdk.ScoreAnswer.legend">
  legend
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">{"legend"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span><span className="p">{"["}</span>{"\n"}{"    "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#int">{"int"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.Any">{"Any"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#list">{"list"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.Any">{"Any"}</a></span><span className="p">{"]"}</span>{"\n"}<span className="p">{"]"}</span>{"\n"}
</SdkSignature>

Rubric descriptions keyed by integer score.

<h3 id="typesafe_sdk.ScoreAnswer.probabilities">
  probabilities
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"probabilities"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#dict">
      {"dict"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#int">
      {"int"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/functions.html#float">
      {"float"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Probabilities keyed by integer score.

<h2 id="typesafe_sdk.Answer">
  typesafe\_sdk.Answer
</h2>

`module-attribute`

<SdkSignature>
  <span className="n">{"Answer"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.TypeAlias">{"TypeAlias"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.Annotated">{"Annotated"}</a></span><span className="p">{"["}</span>{"\n"}{"    "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.NoulAnswer">{"NoulAnswer"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer">{"ChoiceAnswer"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer">{"ScoreAnswer"}</a></span><span className="p">{","}</span>{"\n"}{"    "}<span className="n">{"Field"}</span><span className="p">{"("}</span><span className="n">{"discriminator"}</span><span className="o">{"="}</span><span className="s2">{"\"type\""}</span><span className="p">{"),"}</span>{"\n"}<span className="p">{"]"}</span>{"\n"}
</SdkSignature>

An answer to a single question, identified by its `type`.

<h2 id="available-models">
  Available models
</h2>

<h2 id="typesafe_sdk.ListModelsResponse">
  typesafe\_sdk.ListModelsResponse
</h2>

`pydantic-model`

Bases: `Response`

The models available to the account.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-6">
    ```json theme={null}
    {
      "$defs": {
        "ModelMetadata": {
          "description": "Metadata describing a single available model.",
          "properties": {
            "name": {
              "title": "Name",
              "type": "string"
            },
            "description": {
              "title": "Description",
              "type": "string"
            },
            "release_date": {
              "title": "Release Date",
              "type": "string"
            }
          },
          "required": [
            "name",
            "description",
            "release_date"
          ],
          "title": "ModelMetadata",
          "type": "object"
        }
      },
      "description": "The models available to the account.",
      "properties": {
        "models": {
          "items": {
            "$ref": "#/$defs/ModelMetadata"
          },
          "title": "Models",
          "type": "array"
        }
      },
      "required": [
        "models"
      ],
      "title": "ListModelsResponse",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ListModelsResponse.models">models</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#tuple">tuple</a>\[<a href="/sdk/python/api/types/responses#typesafe_sdk.ModelMetadata">ModelMetadata</a>, ...]</code>)

<h3 id="typesafe_sdk.ListModelsResponse.request_id">
  request\_id
</h3>

`cached` `property`

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

  {"\n"}
</SdkSignature>

The `x-typesafe-request-id` response header.

<h3 id="typesafe_sdk.ListModelsResponse.raw_http_response">
  raw\_http\_response
</h3>

`property`

```python theme={null}
raw_http_response: httpx2.Response
```

The underlying `httpx2.Response`, exposing status, headers, and body.

<h3 id="typesafe_sdk.ListModelsResponse.model_config">
  model\_config
</h3>

`class-attribute` `instance-attribute`

```python theme={null}
model_config = ConfigDict(
    extra="ignore", frozen=True, strict=True
)
```

<h3 id="typesafe_sdk.ListModelsResponse.models">
  models
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"models"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/builtins/stdtypes.html#tuple">
      {"tuple"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/responses#typesafe_sdk.ModelMetadata">
      {"ModelMetadata"}
    </a>
  </span>

  <span className="p">
    {","}
  </span>

  {" "}

  <span className="o">
    {"..."}
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

The available models.

<h2 id="typesafe_sdk.ModelMetadata">
  typesafe\_sdk.ModelMetadata
</h2>

`pydantic-model`

Bases: `Schema`

Metadata describing a single available model.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-7">
    ```json theme={null}
    {
      "description": "Metadata describing a single available model.",
      "properties": {
        "name": {
          "title": "Name",
          "type": "string"
        },
        "description": {
          "title": "Description",
          "type": "string"
        },
        "release_date": {
          "title": "Release Date",
          "type": "string"
        }
      },
      "required": [
        "name",
        "description",
        "release_date"
      ],
      "title": "ModelMetadata",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Fields:

* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ModelMetadata.name">name</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ModelMetadata.description">description</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a></code>)
* <code><a href="/sdk/python/api/types/responses#typesafe_sdk.ModelMetadata.release_date">release\_date</a></code> (<code><a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a></code>)

<h3 id="typesafe_sdk.ModelMetadata.name">
  name
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"name"}
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

  {"\n"}
</SdkSignature>

Model name or alias accepted by a request's model field.

<h3 id="typesafe_sdk.ModelMetadata.description">
  description
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"description"}
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

  {"\n"}
</SdkSignature>

Human-readable description of the model and its capabilities.

<h3 id="typesafe_sdk.ModelMetadata.release_date">
  release\_date
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"release_date"}
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

  {"\n"}
</SdkSignature>

Model release date, formatted as YYYY-MM-DD.
