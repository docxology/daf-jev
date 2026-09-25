> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Questions

> Provide state and ask yes/no, choice, and score questions using objects or dictionaries.

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

<a id="questions" />

<h2 id="state">
  State
</h2>

`state` is the text or JSON object you want to ask questions about. It cannot be `None`, but values inside an object may be `None`.

<h2 id="question-objects">
  Question objects
</h2>

Use `Noul`, `Choice`, and `Score` to define questions with named arguments.

<h2 id="typesafe_sdk.NoulCriteria">
  typesafe\_sdk.NoulCriteria
</h2>

Bases: <code><a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.TypedDict">TypedDict</a></code>

Optional descriptions of the yes and no outcomes.

See the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.

<h3 id="typesafe_sdk.NoulCriteria.true">
  true
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"true"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

Description of the yes outcome as text, a JSON object, or an array; `None` leaves it undescribed.

<h3 id="typesafe_sdk.NoulCriteria.false">
  false
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"false"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

Description of the no outcome as text, a JSON object, or an array; `None` leaves it undescribed.

<h2 id="typesafe_sdk.Noul">
  typesafe\_sdk.Noul
</h2>

`pydantic-model`

Bases: `_Question`, `wire.NoulQuestion`

A yes/no question with optional descriptions for either outcome.

See the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-1">
    ```json theme={null}
    {
      "$defs": {
        "JSONContent": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            }
          ]
        },
        "JSONValue": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "integer"
            },
            {
              "type": "number"
            },
            {
              "type": "boolean"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            }
          ]
        },
        "NoulCriteria": {
          "additionalProperties": false,
          "description": "Optional descriptions of the yes and no outcomes.\n\nSee the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.",
          "properties": {
            "true": {
              "anyOf": [
                {
                  "$ref": "#/$defs/JSONContent"
                },
                {
                  "type": "null"
                }
              ]
            },
            "false": {
              "anyOf": [
                {
                  "$ref": "#/$defs/JSONContent"
                },
                {
                  "type": "null"
                }
              ]
            }
          },
          "title": "NoulCriteria",
          "type": "object"
        }
      },
      "additionalProperties": false,
      "description": "A yes/no question with optional descriptions for either outcome.\n\nSee the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.",
      "properties": {
        "type": {
          "const": "noul",
          "default": "noul",
          "title": "Type",
          "type": "string"
        },
        "instructions": {
          "anyOf": [
            {
              "$ref": "#/$defs/JSONContent"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "criteria": {
          "anyOf": [
            {
              "$ref": "#/$defs/NoulCriteria"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        }
      },
      "title": "Noul",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Fields:

* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['noul']</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Noul.instructions">instructions</a></code> (<code><a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a> | None</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Noul.criteria">criteria</a></code> (<code><a href="/sdk/python/api/types/questions#typesafe_sdk.NoulCriteria">NoulCriteria</a> | None</code>)

<h3 id="typesafe_sdk.Noul.instructions">
  instructions
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

The question to ask, expressed as text, a JSON object, or an array; optional.

<h3 id="typesafe_sdk.Noul.criteria">
  criteria
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/questions#typesafe_sdk.NoulCriteria">
      {"NoulCriteria"}
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

Optional descriptions of the yes and no outcomes.

<h2 id="typesafe_sdk.Choice">
  typesafe\_sdk.Choice
</h2>

`pydantic-model`

Bases: `_Question`, `wire.ChoiceQuestion`

A question that selects between named alternatives.

See the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-2">
    ```json theme={null}
    {
      "$defs": {
        "JSONContent": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            }
          ]
        },
        "JSONValue": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "integer"
            },
            {
              "type": "number"
            },
            {
              "type": "boolean"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            }
          ]
        }
      },
      "additionalProperties": false,
      "description": "A question that selects between named alternatives.\n\nSee the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.",
      "properties": {
        "type": {
          "const": "choice",
          "default": "choice",
          "title": "Type",
          "type": "string"
        },
        "instructions": {
          "anyOf": [
            {
              "$ref": "#/$defs/JSONContent"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "criteria": {
          "additionalProperties": {
            "anyOf": [
              {
                "$ref": "#/$defs/JSONContent"
              },
              {
                "type": "null"
              }
            ]
          },
          "title": "Criteria",
          "type": "object"
        }
      },
      "required": [
        "criteria"
      ],
      "title": "Choice",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Fields:

* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['choice']</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Choice.criteria">criteria</a></code> (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">Mapping</a>\[<a href="https://docs.python.org/3/builtins/stdtypes.html#str">str</a>, <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a> | None]</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Choice.instructions">instructions</a></code> (<code><a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a> | None</code>)

<h3 id="typesafe_sdk.Choice.criteria">
  criteria
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">
      {"Mapping"}
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
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Labels mapped to text, object, or array descriptions, or `None` for undescribed labels.

<h3 id="typesafe_sdk.Choice.instructions">
  instructions
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

The question to ask, expressed as text, a JSON object, or an array; optional.

<h2 id="typesafe_sdk.Score">
  typesafe\_sdk.Score
</h2>

`pydantic-model`

Bases: `_Question`, `wire.ScoreQuestion`

A question that assigns a score using an ordered rubric.

See the [score primitive](https://docs.typesafe.ai/primitives/score) for details.

<Note>
  **Show JSON schema:**

  <Accordion title="Details" id="sdk-disclosure-3">
    ```json theme={null}
    {
      "$defs": {
        "JSONContent": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            }
          ]
        },
        "JSONValue": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "integer"
            },
            {
              "type": "number"
            },
            {
              "type": "boolean"
            },
            {
              "items": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "array"
            },
            {
              "additionalProperties": {
                "anyOf": [
                  {
                    "$ref": "#/$defs/JSONValue"
                  },
                  {
                    "type": "null"
                  }
                ]
              },
              "type": "object"
            }
          ]
        }
      },
      "additionalProperties": false,
      "description": "A question that assigns a score using an ordered rubric.\n\nSee the [score primitive](https://docs.typesafe.ai/primitives/score) for details.",
      "properties": {
        "type": {
          "const": "score",
          "default": "score",
          "title": "Type",
          "type": "string"
        },
        "instructions": {
          "anyOf": [
            {
              "$ref": "#/$defs/JSONContent"
            },
            {
              "type": "null"
            }
          ],
          "default": null
        },
        "criteria": {
          "items": {
            "$ref": "#/$defs/JSONContent"
          },
          "title": "Criteria",
          "type": "array"
        }
      },
      "required": [
        "criteria"
      ],
      "title": "Score",
      "type": "object"
    }
    ```
  </Accordion>
</Note>

Fields:

* `type` (<code><a href="https://docs.python.org/3/library/typing.html#typing.Literal">Literal</a>\['score']</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Score.criteria">criteria</a></code> (<code><a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence">Sequence</a>\[<a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a>]</code>)
* <code><a href="/sdk/python/api/types/questions#typesafe_sdk.Score.instructions">instructions</a></code> (<code><a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">JSONContent</a> | None</code>)

<h3 id="typesafe_sdk.Score.criteria">
  criteria
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence">
      {"Sequence"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

A nonempty, ordered list of text, object, or array descriptions, one per score from zero.

<h3 id="typesafe_sdk.Score.instructions">
  instructions
</h3>

`pydantic-field`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

The question to ask, expressed as text, a JSON object, or an array; optional.

<h2 id="typesafe_sdk.Question">
  typesafe\_sdk.Question
</h2>

`module-attribute`

<SdkSignature>
  <span className="n">{"Question"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.TypeAlias">{"TypeAlias"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="p">{"("}</span>{"\n"}{"    "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.Noul">{"Noul"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.Choice">{"Choice"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.Score">{"Score"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.QuestionModel">{"QuestionModel"}</a></span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

A question object or question dictionary.

<h2 id="typesafe_sdk.Questions">
  typesafe\_sdk.Questions
</h2>

`module-attribute`

<SdkSignature>
  <span className="n">
    {"Questions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/typing.html#typing.TypeAlias">
      {"TypeAlias"}
    </a>
  </span>

  {" "}

  <span className="o">
    {"="}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">
      {"Mapping"}
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
    <a href="/sdk/python/api/types/questions#typesafe_sdk.Question">
      {"Question"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Question inputs keyed by the names used to identify their answers.

<h2 id="question-dictionaries">
  Question dictionaries
</h2>

Question dictionaries include a `type` key: `"noul"`, `"choice"`, or `"score"`. You can mix dictionaries and question objects in the same request.

<h2 id="typesafe_sdk.NoulModel">
  typesafe\_sdk.NoulModel
</h2>

Bases: <code><a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.TypedDict">TypedDict</a></code>

A yes/no question dictionary with `type="noul"`.

See the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.

<h3 id="typesafe_sdk.NoulModel.type">
  type
</h3>

`instance-attribute`

<SdkSignature>
  <span className="nb">
    {"type"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/typing.html#typing.Literal">
      {"Literal"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="s1">
    {"'noul'"}
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

<h3 id="typesafe_sdk.NoulModel.instructions">
  instructions
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.NotRequired">
      {"NotRequired"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

The question to ask, expressed as text, a JSON object, or an array; optional.

<h3 id="typesafe_sdk.NoulModel.criteria">
  criteria
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.NotRequired">
      {"NotRequired"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/questions#typesafe_sdk.NoulCriteria">
      {"NoulCriteria"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Optional descriptions of the yes and no outcomes.

<h2 id="typesafe_sdk.ChoiceModel">
  typesafe\_sdk.ChoiceModel
</h2>

Bases: <code><a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.TypedDict">TypedDict</a></code>

A choice question dictionary with `type="choice"`.

See the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.

<h3 id="typesafe_sdk.ChoiceModel.type">
  type
</h3>

`instance-attribute`

<SdkSignature>
  <span className="nb">
    {"type"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/typing.html#typing.Literal">
      {"Literal"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="s1">
    {"'choice'"}
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

<h3 id="typesafe_sdk.ChoiceModel.instructions">
  instructions
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.NotRequired">
      {"NotRequired"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

The question to ask, expressed as text, a JSON object, or an array; optional.

<h3 id="typesafe_sdk.ChoiceModel.criteria">
  criteria
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Mapping">
      {"Mapping"}
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
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

Labels mapped to text, object, or array descriptions, or `None` for undescribed labels.

<h2 id="typesafe_sdk.ScoreModel">
  typesafe\_sdk.ScoreModel
</h2>

Bases: <code><a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.TypedDict">TypedDict</a></code>

A score question dictionary with `type="score"`.

See the [score primitive](https://docs.typesafe.ai/primitives/score) for details.

<h3 id="typesafe_sdk.ScoreModel.type">
  type
</h3>

`instance-attribute`

<SdkSignature>
  <span className="nb">
    {"type"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/typing.html#typing.Literal">
      {"Literal"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="s1">
    {"'score'"}
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

<h3 id="typesafe_sdk.ScoreModel.instructions">
  instructions
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"instructions"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://typing-extensions.readthedocs.io/en/latest/index.html#typing_extensions.NotRequired">
      {"NotRequired"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
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

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

The question to ask, expressed as text, a JSON object, or an array; optional.

<h3 id="typesafe_sdk.ScoreModel.criteria">
  criteria
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">
    {"criteria"}
  </span>

  <span className="p">
    {":"}
  </span>

  {" "}

  <span className="n">
    <a href="https://docs.python.org/3/library/collections.abc.html#collections.abc.Sequence">
      {"Sequence"}
    </a>
  </span>

  <span className="p">
    {"["}
  </span>

  <span className="n">
    <a href="/sdk/python/api/types/common#typesafe_sdk.JSONContent">
      {"JSONContent"}
    </a>
  </span>

  <span className="p">
    {"]"}
  </span>

  {"\n"}
</SdkSignature>

A nonempty, ordered list of text, object, or array descriptions, one per score from zero.

<h2 id="typesafe_sdk.QuestionModel">
  typesafe\_sdk.QuestionModel
</h2>

`module-attribute`

<SdkSignature>
  <span className="n">{"QuestionModel"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.TypeAlias">{"TypeAlias"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="p">{"("}</span>{"\n"}{"    "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.NoulModel">{"NoulModel"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.ChoiceModel">{"ChoiceModel"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/questions#typesafe_sdk.ScoreModel">{"ScoreModel"}</a></span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

A question dictionary identified by its `type` key.
