# Test maintenance

Start with the [test guide](README.md) and the repository’s
[verification commands](../AGENTS.md#verification-commands).

- Put offline package and local integration checks in `unit/`. Use real
  files, numerical inputs and the existing local HTTP fixture as applicable.
- Keep tests that call a provider in `live/` with the `live` marker. The
  offline gate excludes them. CI checks collection separately.
- For generated manuscript counts and coverage, keep the native result and
  its exact input binding with the corresponding
  [verification selection](../docs/reproducibility.md#retained-verification-for-exact-offline-regeneration).
