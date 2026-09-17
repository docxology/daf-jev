> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Changelog

> Python clients for the TypeSafe AI API

<a id="changelog" />

<h2 id="v060-2026-09-15">
  v0.6.0 (2026-09-15)
</h2>

<h3 id="breaking-changes">
  Breaking Changes
</h3>

* accept `Score.criteria` as an ordered sequence instead of a dictionary keyed by integers

<h3 id="features">
  Features
</h3>

* improve type annotations on SDK inputs to accept abstract types like `Mapping` and `Sequence`
* improve error messages to include http details and metadata

<h3 id="bug-fixes">
  Bug fixes
</h3>

* handle invalid values in `RetryPolicy`
* make exceptions and responses picklable

<h3 id="documentation">
  Documentation
</h3>

* link more concepts from main [docs](https://docs.typesafe.ai/)

<h2 id="v057-2026-09-14">
  v0.5.7 (2026-09-14)
</h2>

This is the initial public release of TypeSafe Python SDK. Learn more in the [documentation](https://docs.typesafe.ai/sdk/python).
