# Stack integration and evidence

daf-jev supplies typed decision interfaces, provider-neutral execution receipts,
Bayes-net/posterior interchange, and reproducible evaluation. DAF Dot carries the
real-time voice protocol; DAF Operator spatializes information. This component
does not start either service or dispatch workers.

## Read selected verification

From a prepared environment:

```sh
daf-jev verification-status --root /absolute/path/to/daf-jev --pretty
```

The existing CLI emits `dafjev.verification-status/1` on stdout. `current` exits
0 and supplies the existing `VerificationStatistics` fields: unit_count,
live_count, coverage_percent, python_version, platform. `unavailable` (no selected
verification) and `invalid` (malformed, missing, changed or stale selected inputs)
exit 1 with null statistics. Invalid evidence includes a typed error. Missing
`--root` exits 2. The explicit root prevents an installed wheel or arbitrary CWD
from being mistaken for a source checkout.

This reads `manuscript/evidence.json` through `evidence.selected_verification`,
including exact bound capture/native-export bytes and before/after/current source
inventories. It never falls back to raw coverage, a newer result, prose counts,
pytest collection or execution. The inventory includes shell gates and tasks.yaml;
captures predating these inputs are stale. The status is a point-in-time source
observation; re-read before reuse. It is not an atomic filesystem attestation.
`current` describes retained unit execution plus live collection, not execution
of live tests or success of every tool in the fixed Stack gate.

The native Stack gate remains `bash scripts/gate.sh`: fixed offline tests with
branch coverage >=90%, live explicitly excluded, no test-selection arguments.
Use the project's existing uv lock and an already qualified SSD runtime. A
missing offline wheel is unavailable preparation, not passing verification.
`scripts/capture_verification.py --out-dir FRESH_INSIDE_ROOT` retains genuine
unit/JUnit/coverage/live-collection output. Select its path/hash deliberately;
this status command never changes historical publication selection.

## Sidecar foothold

`.docxology/` was created by the existing native `docxology-sidecar init`, using
its version-one manifest and empty native lock. Scaffold owner/ORCID values are
inherited tool defaults, not independent identity verification. No key, recipient,
sealed payload, encryption setup or hosted inference is required here.

Run the Sidecar owner's existing read-only command against this checkout:

```sh
bun run /absolute/path/to/daf-sidecar/src/cli.ts doctor /absolute/path/to/daf-jev --json
```

Its `{status,data,error,meta}` transport envelope and `data.verdict`
pass/concerns/fail are separate from daf-jev's native verification status. Dirty
source is a concern. Sidecar directory presence, typed configuration, bounded
observation, fresh validation and stale evidence remain distinct; native Sidecar
coverage is not a source gate, identity authority, adoption or publication proof.
Preserve its manifest/lock formats; use the owner's roster-based fleet audit for
coverage rather than inventing a second schema or freshness rule here.

## Roster membership

Stack owns the repository registry and publishes it read-only as
`daf-stack-doctor roster` → `{daf_root, repos: [{name, path, branch,
require_board, require_sidecar, gate_cmd, required_files, board_path}]}`.
daf-jev consumes that document as an external dual-use member:

```sh
daf-stack-doctor roster > /tmp/roster.json        # in the daf-stack checkout
daf-jev stack-member /tmp/roster.json --pretty
```

`daf-jev stack-member` parses the roster strictly (duplicate JSON keys,
missing/typed fields, relative or escaping `required_files` entries and
duplicate member names fail closed; unknown extra fields are ignored) and
audits the `daf-jev` entry, or another `--repo NAME`. It checks only that the
declared `required_files` exist under the declared path, which `--root PATH`
may override for a moved checkout or install. It prints
`dafjev.stack-member/1` and exits 0 when the member conforms, 1 for missing
files or a malformed/unreadable roster, 2 for an unknown `--repo`.

The declared `branch`, `gate_cmd`, `board_path`, `require_board` and
`require_sidecar` values are echoed, never executed or verified: no git,
gate, Sidecar CLI or subprocess runs, and a green audit is not daf-stack's
doctor verdict, the native offline gate, Sidecar coverage or publication
acceptance. `tests/unit/test_stack_roster.py` also binds this checkout to the
declared required files, so losing one fails locally rather than silently
dropping Stack membership.

## Next integration

Stack owns its manifest and fixed entrypoint admission. Operator can consume
this explicit-root CLI result as a scoped evidence card, keeping unavailable and
invalid states visible and re-reading before reuse. The roster consumer above
reads Stack's registry; it does not register components, wire dashboards or
admit cross-repo gates. Native source-gate evidence, Sidecar coverage, model
execution/billing, scientific acceptance and publication remain separate
evidence lanes.
