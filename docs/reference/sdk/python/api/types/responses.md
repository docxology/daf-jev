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

Bases: `Response`

Answers grouped by question type with model and usage metadata.

See [System One](https://docs.typesafe.ai/concepts/system-one) for details.

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

<h3 id="typesafe_sdk.SystemOneResponse.model">
  model
</h3>

`instance-attribute`

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

`instance-attribute`

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

`class-attribute` `instance-attribute`

<SdkSignature>
  <span className="n">{"answers"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.Answer">{"Answer"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"="}</span>{" "}<span className="n"><a href="https://msgspec.dev/api.html#msgspec.field">{"field"}</a></span><span className="p">{"("}</span>{"\n"}{"    "}<span className="n">{"default_factory"}</span><span className="o">{"="}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span>{"\n"}<span className="p">{")"}</span>{"\n"}
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

Bases: <code>msgspec.<a href="https://msgspec.dev/api.html#msgspec.Struct">Struct</a></code>

Token counts for a request, when reported by the API.

<h3 id="typesafe_sdk.Usage.input_tokens">
  input\_tokens
</h3>

`class-attribute` `instance-attribute`

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

`class-attribute` `instance-attribute`

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

Bases: `wire.NoulAnswer`

A yes/no answer.

See the [noul primitive](https://docs.typesafe.ai/primitives/noul) for details.

<h3 id="typesafe_sdk.NoulAnswer.noul">
  noul
</h3>

`instance-attribute`

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

Probability of a yes answer, from zero to one.

<h2 id="typesafe_sdk.ChoiceAnswer">
  typesafe\_sdk.ChoiceAnswer
</h2>

Bases: `wire.ChoiceAnswer`

A selected label and its probabilities.

See the [choice primitive](https://docs.typesafe.ai/primitives/choice) for details.

<h3 id="typesafe_sdk.ChoiceAnswer.choice">
  choice
</h3>

`instance-attribute`

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

The selected label.

<h3 id="typesafe_sdk.ChoiceAnswer.confidence">
  confidence
</h3>

`instance-attribute`

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

Reported confidence in the selected label.

<h3 id="typesafe_sdk.ChoiceAnswer.probabilities">
  probabilities
</h3>

`instance-attribute`

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

Probabilities keyed by label.

<h2 id="typesafe_sdk.ScoreAnswer">
  typesafe\_sdk.ScoreAnswer
</h2>

Bases: `wire.ScoreAnswer`

An expected score with its rubric and probabilities.

See the [score primitive](https://docs.typesafe.ai/primitives/score) for details.

<h3 id="typesafe_sdk.ScoreAnswer.score">
  score
</h3>

`instance-attribute`

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

Expected score, which may fall between the integer rubric levels.

<h3 id="typesafe_sdk.ScoreAnswer.confidence">
  confidence
</h3>

`instance-attribute`

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

Reported confidence in the score.

<h3 id="typesafe_sdk.ScoreAnswer.legend">
  legend
</h3>

`instance-attribute`

<SdkSignature>
  <span className="n">{"legend"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span><span className="p">{"["}</span>{"\n"}{"    "}<span className="n"><a href="https://docs.python.org/3/builtins/functions.html#int">{"int"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#dict">{"dict"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#str">{"str"}</a></span><span className="p">{","}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.Any">{"Any"}</a></span><span className="p">{"]"}</span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/builtins/stdtypes.html#list">{"list"}</a></span><span className="p">{"["}</span><span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.Any">{"Any"}</a></span><span className="p">{"]"}</span>{"\n"}<span className="p">{"]"}</span>{"\n"}
</SdkSignature>

Rubric descriptions keyed by integer score.

<h3 id="typesafe_sdk.ScoreAnswer.probabilities">
  probabilities
</h3>

`instance-attribute`

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
  <span className="n">{"Answer"}</span><span className="p">{":"}</span>{" "}<span className="n"><a href="https://docs.python.org/3/library/typing.html#typing.TypeAlias">{"TypeAlias"}</a></span>{" "}<span className="o">{"="}</span>{" "}<span className="p">{"("}</span>{"\n"}{"    "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.NoulAnswer">{"NoulAnswer"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.ChoiceAnswer">{"ChoiceAnswer"}</a></span>{" "}<span className="o">{"|"}</span>{" "}<span className="n"><a href="/sdk/python/api/types/responses#typesafe_sdk.ScoreAnswer">{"ScoreAnswer"}</a></span>{"\n"}<span className="p">{")"}</span>{"\n"}
</SdkSignature>

An answer to a single question, identified by its `type`.

<h2 id="available-models">
  Available models
</h2>

<h2 id="typesafe_sdk.ListModelsResponse">
  typesafe\_sdk.ListModelsResponse
</h2>

Bases: `Response`

The models available to the account.

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

<h3 id="typesafe_sdk.ListModelsResponse.models">
  models
</h3>

`instance-attribute`

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

Bases: <code><a href="https://msgspec.dev/api.html#msgspec.Struct">Struct</a></code>

<h3 id="typesafe_sdk.ModelMetadata.name">
  name
</h3>

`instance-attribute`

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

<h3 id="typesafe_sdk.ModelMetadata.description">
  description
</h3>

`instance-attribute`

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

<h3 id="typesafe_sdk.ModelMetadata.release_date">
  release\_date
</h3>

`instance-attribute`

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
