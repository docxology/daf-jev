# Modular decision-model study: hosted probe result

Manifest: `df1ea22ca5f0691dbd0148e0908c7df3475e5cf16fa04a1ef709cb5d6d999954`. Journal: `b6de3222b071e0623174b3f49e40b7a95403a89ef68c6e56e8bfc3ce56e2abc9`.

Software verification: 1,519 passing unit tests; 93.15% combined line and branch coverage. 2 live tests were collected and none executed.

The frozen 5-arm pilot contains 18,065 cells. Its validation-probe stage made 1 actual HTTP attempt. The result is partial: 0 completed, 1 failed, 19 unsupported and 18,045 unattempted.

Requested model: `inception/mercury-decide:free`. Endpoint: `https://openrouter.ai/api/alpha/decisions`. HTTP status: 404. Resolved model, provider, response ID, tokens and charge are unavailable.

The probe used one independently defined synthetic validation example with three complete Choice options. It did not establish successful inference or a maximum option/context boundary. No quality, warm-repeat or graphical inference ran. No hosted accuracy, calibration, latency comparison or cost-per-correct-decision claim follows from this failure.

The shared allocation remains USD 25. The ledger's reported and reserved totals are USD 0 and USD 0, but it retains 1 unknown-billing attempt and stops admission. These numeric zeros do not prove zero actual billing. Probes, failed attempts and retries share this allocation.

The operational process guard closed and reaped its child, with 0 SIGINT deliveries and no observed unresolved descendants. Its measured outer interval was 3.176273 seconds. Process closure does not reconcile billing or establish model quality.

Public metadata investigation separately returned HTTP 200 for the Mercury endpoint listing and for the Decisions reference, while an unauthenticated GET to the Decisions route returned HTTP 404. GET and POST are different operations. These later observations do not reproduce the original response body or identify the original POST failure cause. The [official Decisions reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request) continues to document the POST endpoint.

This first pilot is frozen at hosted concurrency 1; the general default of four is a different throughput treatment. All subsequent hosted phases remain held pending actual billing reconciliation. No endpoint substitution or new ledger was used.

Retained CPU comparator studies remain separate: 9 jobs with 93,046 planned cells, 68,894 completed and 24,152 unsupported. Their [comparison](../full-offline-20261008/full-offline-comparison.md) and source identities remain unchanged. Historical local-model receipts are a partial study, not current-source acceptance.

The 15-arm full-study projection remains proposed, with 376,155 cells. The all-arm pilot obligation contains 54,195 cells; only the eligible five-arm subset was materialized. These projections create no additional budget and are not completed comparative studies. Local model startup continues to require accepted cumulative clocks, independently checked runtime/input custody and available RAM above each unchanged profile floor.

The [JSON aggregate](summary.json) binds the selected manifest, journal, report, source, metadata and independent reviews. Complete raw observations and review receipts remain in the local retained archive. This report does not publish that archive. The [source paper](../../pdf/modular-methods-reproduction-20261008-staged-source.pdf) documents the framework and its selected historical evidence; it does not add a hosted quality result.
