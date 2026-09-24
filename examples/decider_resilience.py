"""Decider resilience: ledger, breaker, budget and cache in one loop.

Demonstrates:
- ``UsageLedger`` wiring and ``usage_snapshot().to_dict()`` totals
- a ``CircuitBreaker`` around the ask, driven by an injectable fake
  clock (cooldown skipped without sleeping)
- the ``CircuitOpenError`` -> fallback reason ``"breaker"`` path
- ``Budget`` bounding ask attempts (reason ``"budget"``); the
  open-circuit attempt is charged too -- ``charge()`` precedes the ask
- a per-decision ``cache``/``cache_key`` pair (source ``cache``)
- a ``should_ask`` veto (reason ``"not_asked"``)
- the injected-transport seam: scripted canned transport serving 500s
  during a simulated outage, then recovering (zero network)

Run: python examples/decider_resilience.py [--model NAME]
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import httpx

from daf_jev import (
    Budget,
    CircuitBreaker,
    Decider,
    JevClient,
    RetryPolicy,
    UsageLedger,
    choice,
    load_settings,
)

Ticket = dict[str, str]

# V is informational (vetoed); B and C hit the canned outage (500s).
STATES: list[Ticket] = [
    {"ticket": "V", "summary": "informational: weekly metrics digest"},
    {"ticket": "A", "summary": "checkout button returns HTTP 500"},
    {"ticket": "B", "summary": "login loop on mobile web"},
    {"ticket": "C", "summary": "duplicate invoice charge"},
    {"ticket": "D", "summary": "stale search results"},
    {"ticket": "E", "summary": "export job hangs at 90 percent"},
    {"ticket": "F", "summary": "newsletter unsubscribe broken"},
]

ROUTE = choice(
    "Route this ticket now or defer it to the next triage batch?",
    {"now": "page the on-call owner", "later": "batch for next triage"},
)

OUTAGE_MARKERS = ("ticket=B", "ticket=C")


class FakeClock:
    """Advancing ``time.monotonic`` stand-in (no sleeping in the demo)."""

    def __init__(self) -> None:
        self.now: float = 0.0

    def __call__(self) -> float:
        return self.now


class ScriptedTransport:
    """Canned Transport: 500 during the outage, success payload after.

    The injected transport is the sanctioned offline seam; flipping
    ``recovered`` mid-demo ends the outage for OUTAGE_MARKERS tickets.
    """

    def __init__(self) -> None:
        self.recovered: bool = False

    def post_json(
        self,
        path: str,
        json_body: dict,
        headers: dict[str, str],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        state_text = str(json_body.get("state", ""))
        if not self.recovered and any(m in state_text for m in OUTAGE_MARKERS):
            return httpx.Response(500, json={"error": "simulated outage"})
        payload = {
            "model": "kev-latest",
            "answers": {
                "route": {
                    "type": "choice",
                    "choice": "now",
                    "probabilities": {"now": 0.9, "later": 0.1},
                    "confidence": 0.9,
                },
            },
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }
        return httpx.Response(
            200,
            json=payload,
            headers={"x-typesafe-request-id": "canned-0000"},
        )

    def close(self) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resilient decision loop: ledger + breaker + budget + cache."
    )
    parser.add_argument("--model", default=None, help="model name override")
    args = parser.parse_args()

    settings = load_settings()
    if settings.api_key is None:
        print("SKIP: JEV_API_KEY not set")
        return

    clock = FakeClock()
    transport = ScriptedTransport()
    cache: dict[str, str] = {}
    events: list[dict[str, Any]] = []

    with JevClient(
        api_key=settings.api_key,
        model=args.model or settings.model,
        transport=transport,
        retry=RetryPolicy(max_attempts=1),
    ) as client:
        breaker = CircuitBreaker(failure_threshold=2, clock=clock)
        decider = Decider(
            client,
            render_state=lambda state: f"ticket={state['ticket']} {state['summary']}",
            questions=lambda state: {"route": ROUTE},
            map_answers=lambda state, resp: resp.choices["route"].choice,
            fallback=lambda state: f"manual-review:{state['ticket']}",
            should_ask=lambda state: "informational" not in state["summary"],
            budget=Budget(max_calls=5),  # open-circuit attempt charged too
            # 2 outage errors < 3: the breaker-open decide (D) is not
            # counted, so the Decider never latches in this arc.
            max_consecutive_failures=3,
            cache=cache,
            cache_key=lambda state: state["ticket"],
            ledger=UsageLedger(),
            breaker=breaker,
            clock=clock,
            on_event=lambda event: events.append(event.to_dict()),
        )

        def decide_and_report(state: Ticket) -> None:
            action = decider.decide(state)
            event = decider.last_event
            assert event is not None  # decide() emits exactly one event
            print(f"decide({state['ticket']}) -> {action!r}")
            print(json.dumps(event.to_dict(), sort_keys=True))

        tickets = {state["ticket"]: state for state in STATES}

        # 1. should_ask veto: no ask, no charge.
        decide_and_report(tickets["V"])
        # 2. First ask succeeds; the repeat is served from cache.
        decide_and_report(tickets["A"])
        decide_and_report(tickets["A"])
        # 3. Outage: B, C get 500s; second consecutive failure trips breaker.
        decide_and_report(tickets["B"])
        decide_and_report(tickets["C"])
        print("breaker open:", json.dumps(breaker.to_dict(), sort_keys=True))
        # 4. Circuit open: CircuitOpenError -> fallback reason "breaker".
        decide_and_report(tickets["D"])
        # 5. Recovery: outage over, cooldown elapsed; the probe succeeds.
        transport.recovered = True
        clock.now += 31.0
        print(
            "breaker pre-probe:", json.dumps(breaker.to_dict(), sort_keys=True)
        )
        decide_and_report(tickets["E"])
        print("breaker closed:", json.dumps(breaker.to_dict(), sort_keys=True))
        # 6. Budget spent (A-E charged, open attempt too): reason "budget".
        decide_and_report(tickets["F"])

    tokens = [event["reason"] or event["source"] for event in events]
    print("decision sequence:", " -> ".join(tokens))
    usage = decider.usage_snapshot().to_dict()
    print(f"usage: {json.dumps(usage, sort_keys=True)}")


if __name__ == "__main__":
    main()
