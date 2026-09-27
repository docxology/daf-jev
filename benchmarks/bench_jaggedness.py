#!/usr/bin/env python3
"""Model jaggedness: statistical uniformity of stochastic answers across providers.

For each requested provider (jeff, kev, jev, ...) that has a usable API key,
three stochastic fixtures are each asked N times — one call per repeat: a
fair-coin choice question, a six-sided die choice question, and the same coin
as a yes/no noul question. Per fixture, daf_jev.jaggedness.run_battery
measures how far the stated/observed behavior deviates from the uniform
distribution: a chi-square uniformity test on the chosen labels, per-outcome
deviation from 1/k (max |Δp| and total variation across repeated asks),
degeneracy of the chosen label (one label wins every time), serial structure
(runs test z, longest streak), order sensitivity (sequential vs concurrent
asks: position-bias slope, argmax flips, concurrent wobble), and for noul the
spread of the scalar belief. The coin-noul and coin-choice fixtures are
compared through the noul_choice_delta cross-instrument gap — the same fair
coin, measured two ways, should agree.

Writes output/benchmarks/jaggedness_<YYYYMMDD>.json and prints a compact
per-provider/per-fixture table (verdict left to the reader). A provider whose
key variable is unset is skipped with a SKIP line; when no requested provider
has a key the run prints a global skip line and exits 0. Provider and ask
failures never raise: construction errors, battery errors, and failed asks
are isolated to their own row/counters (``n_errors``).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _util import ROOT, write_result  # noqa: E402

GLOBAL_SKIP_MESSAGE = (
    "SKIP: no provider keys set (JEV_API_KEY / JEFF_API_KEY / KEV_API_KEY)"
)

# CLI fixture name -> canonical battery key (the keys used in the JSON
# payload); the canonical key maps onto the JaggednessFixture constants
# lazily inside main().
FIXTURE_ALIASES: dict[str, str] = {
    "coin": "coin",
    "d6": "d6",
    "coin-noul": "coin_noul",
    "coin_noul": "coin_noul",
}


def fixture_names_arg(value: str) -> list[str]:
    """Parse the --fixtures comma list into canonical keys, deduplicated.

    Raises argparse-style ValueError on an unknown name so main can call
    parser.error with the exact argument name.
    """
    names: list[str] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        canonical = FIXTURE_ALIASES.get(token)
        if canonical is None:
            raise ValueError(token)
        if canonical not in names:
            names.append(canonical)
    if not names:
        raise ValueError(value)
    return names


def _fmt(value: float | int | bool | None, spec: str = ".3f") -> str:
    """Format a table cell; missing/None renders as a dash."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return format(value, spec)


def _chi2_p(battery: dict) -> float | None:
    """Chi-square p-value of a choice battery, or None when not computable."""
    chi2 = battery.get("uniform_chi2")
    if chi2 is None:
        return None
    return chi2.get("p")


def _choice_row(
    provider: str, fixture: str, battery: dict
) -> list[str]:
    """One table row for a choice battery: uniformity and order columns."""
    deviation = battery.get("uniform_deviation") or {}
    orders = battery.get("orders") or {}
    return [
        provider,
        fixture,
        _fmt(_chi2_p(battery), ".4g"),
        _fmt(deviation.get("max_abs")),
        _fmt(deviation.get("total_variation")),
        _fmt(battery.get("degenerate")),
        _fmt(orders.get("argmax_flips"), "d"),
        "-",
        "-",
    ]


def _noul_row(
    provider: str, battery: dict, delta: float | None
) -> list[str]:
    """One table row for the noul battery: belief spread and the cross gap."""
    return [
        provider,
        "coin_noul",
        "-",
        "-",
        "-",
        "-",
        "-",
        _fmt(battery.get("noul_mean")),
        _fmt(delta),
    ]


def print_table(rows: list[list[str]], width: int) -> None:
    """Compact per-provider/per-fixture summary; verdict left to the reader."""
    header = [
        "provider", "fixture", "chi2 p", "max|dp|", "TV", "degen", "flips",
        "noul p", "noul-ch",
    ]
    print(f"{'provider':<{width}}  " + "  ".join(f"{col:>8}" for col in header[1:]))
    for row in rows:
        print(f"{row[0]:<{width}}  " + "  ".join(f"{cell:>8}" for cell in row[1:]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--providers", default="jeff,kev,jev",
        help="comma-separated provider registry keys (default jeff,kev,jev)")
    parser.add_argument(
        "--fixtures", default="coin,d6,coin-noul",
        help="comma-separated subset of coin,d6,coin-noul (default all; "
             "coin_noul is accepted as an alias of coin-noul)")
    parser.add_argument(
        "--repeats", type=int, default=50,
        help="independent asks per fixture (default 50)")
    parser.add_argument(
        "--concurrent", type=int, default=32,
        help="concurrent asks in the wobble arm (default 32)")
    parser.add_argument(
        "--timeout", type=float, default=None,
        help="per-call timeout in seconds (default: client/env default)")
    parser.add_argument(
        "--model", default=None,
        help="model id (default: provider-resolved model)")
    args = parser.parse_args(argv)

    try:
        fixture_names = fixture_names_arg(args.fixtures)
    except ValueError as unknown:
        parser.error(f"--fixtures: unknown fixture {unknown.args[0]!r} "
                     f"(choose from {', '.join(sorted(FIXTURE_ALIASES))})")
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.concurrent < 1:
        parser.error("--concurrent must be >= 1")

    # Lazy imports: the instrument modules are landing concurrently and the
    # registry/key resolution needs the .env merge below.
    from daf_jev import JevClient
    from daf_jev.config import load_dotenv
    from daf_jev.jaggedness import COIN, COIN_NOUL, D6, noul_choice_delta, run_battery
    from daf_jev.providers import (
        get_provider,
        resolve_provider_api_key,
        resolve_provider_model,
    )

    file_env = load_dotenv(ROOT / ".env")
    merged = {k: v for k, v in file_env.items() if k not in os.environ}

    fixture_by_name = {"coin": COIN, "d6": D6, "coin_noul": COIN_NOUL}

    requested = [p.strip() for p in args.providers.split(",") if p.strip()]
    rows: list[list[str]] = []
    providers_payload: dict[str, dict] = {}
    n_with_key = 0
    for key in requested:
        try:
            spec = get_provider(key)
        except ValueError as exc:
            print(f"ERROR[{key}]: {exc}")
            continue
        api_key = resolve_provider_api_key(spec, env=merged)
        if not api_key:
            print(f"SKIP[{spec.key}]: {spec.api_key_vars[0]} not set")
            continue
        n_with_key += 1
        try:
            client = JevClient.for_provider(
                provider=spec.key, env=merged, timeout=args.timeout,
                model=args.model,
            )
        except Exception as exc:  # never crash the run on one provider
            print(f"ERROR[{spec.key}]: client construction failed: {exc}")
            continue
        model_name = args.model or resolve_provider_model(spec, env=merged)
        print(f"jaggedness: provider={spec.key} model={model_name} "
              f"repeats={args.repeats} concurrent={args.concurrent}")

        fixtures_payload: dict[str, dict] = {}
        delta: float | None = None
        noul_row_index: int | None = None
        try:
            with client:
                for name in fixture_names:
                    try:
                        result = run_battery(
                            client, fixture_by_name[name],
                            repeats=args.repeats,
                            concurrent=args.concurrent,
                            timeout=args.timeout,
                        )
                    except Exception as exc:  # per-fixture isolation
                        print(f"ERROR[{spec.key}/{name}]: "
                              f"{type(exc).__name__}: {exc}")
                        continue
                    # run_battery returns {fixture.name: battery_dict} for
                    # a single fixture; a bare battery dict is tolerated.
                    battery = (
                        result[name] if name in result and "kind" not in result
                        else result
                    )
                    if battery.get("kind") == "choice":
                        rows.append(_choice_row(spec.key, name, battery))
                    else:
                        rows.append(_noul_row(spec.key, battery, None))
                        noul_row_index = len(rows) - 1
                    if battery.get("n_errors"):
                        print(f"errors[{spec.key}/{name}]: "
                              f"{battery['n_errors']} failed ask(s)")
                    fixtures_payload[name] = battery
                coin_b = fixtures_payload.get("coin")
                noul_b = fixtures_payload.get("coin_noul")
                if (
                    coin_b is not None
                    and noul_b is not None
                    and not coin_b.get("n_errors")
                    and not noul_b.get("n_errors")
                    and "prob_mean" in coin_b
                    and "heads" in coin_b.get("prob_mean", {})
                    and "noul_mean" in noul_b
                ):
                    delta = round(
                        noul_choice_delta(
                            noul_b["noul_mean"], coin_b["prob_mean"]["heads"]
                        ),
                        6,
                    )
                if delta is not None and noul_row_index is not None:
                    rows[noul_row_index][8] = _fmt(delta)
        except Exception as exc:  # client/session-level failure
            print(f"ERROR[{spec.key}]: {type(exc).__name__}: {exc}")
            continue

        providers_payload[spec.key] = {
            "model": model_name,
            "fixtures": fixtures_payload,
            "noul_choice_delta": delta,
        }

    if n_with_key == 0:
        print(GLOBAL_SKIP_MESSAGE)
        return 0

    if rows:
        width = max(len("provider"), *(len(r[0]) for r in rows))
        print_table(rows, width)
    else:
        print("all fixtures failed for every provider; no metrics computed")

    payload = {
        "generated": date.today().isoformat(),
        "config": vars(args),
        "providers": providers_payload,
    }
    path = write_result("jaggedness", payload)
    print(f"results: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
