"""One table for a director run: what passed, what it cost, whether teams were used.

    python summarize.py --runs RUN_ROOT --eval EVAL_ROOT --harness-model director__X [--ledger F]
"""

from __future__ import annotations

import argparse
import json
import pathlib


def load(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--eval", required=True)
    parser.add_argument("--harness-model", required=True)
    parser.add_argument("--ledger")
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = []
    for manifest in sorted(pathlib.Path(args.runs).glob(f"*/{args.harness_model}/*/*/*/*/manifest.json")):
        bundle = manifest.parent
        corpus, _, label, family, instance, scenario = bundle.parts[-6:]
        graded = load(pathlib.Path(args.eval) / corpus / args.harness_model / label / family / instance / f"{scenario}.json")
        turns = [load(turn / "team_usage.json") for turn in sorted((bundle / "turns").glob("*"))]
        results = [load(turn / "result.json") for turn in sorted((bundle / "turns").glob("*"))]
        summaries = [turn.get("summary") or {} for turn in turns]
        rows.append(
            {
                "instance": instance,
                "family": family,
                "scenario": scenario,
                "landed": all(r.get("landed") for r in results) if results else None,
                "scored_pass": graded.get("scored_pass"),
                "used_teams": any(turn.get("used_teams") for turn in turns),
                "sub_teams": sum(s.get("sub_teams_started", 0) for s in summaries),
                "proposals": sum(s.get("proposals", 0) for s in summaries),
                "team_tool_calls": sum(s.get("team_tool_calls", 0) for s in summaries),
                "agents": sum(s.get("agents", 0) for s in summaries),
                "web_lookups": [look for turn in turns for look in turn.get("web_lookups") or []],
                "web_tools_refused": sum(len(r.get("web_tools_refused") or []) for r in results),
                "hosts_refused": sorted({h for r in results for h in (r.get("network") or {}).get("refused") or []}),
                "cost": round(sum(r.get("cost") or 0 for r in results), 2),
                "cost_estimated": any((turn.get("usage") or {}).get("estimated") for turn in turns),
                "minutes": round(sum(r.get("wall_seconds") or 0 for r in results) / 60, 1),
            }
        )
    done = [row for row in rows if row["scored_pass"] is not None]
    total = {
        "harness_model": args.harness_model,
        "bundles": len(rows),
        "graded": len(done),
        "scored_pass": sum(bool(row["scored_pass"]) for row in done),
        "landed": sum(bool(row["landed"]) for row in rows),
        "used_teams": sum(row["used_teams"] for row in rows),
        "with_web_lookups": sum(bool(row["web_lookups"]) for row in rows),
        "scored_pass_without_web_lookups": sum(bool(row["scored_pass"]) and not row["web_lookups"] for row in done),
        "cost": round(sum(row["cost"] for row in rows), 2),
        "ledger": load(pathlib.Path(args.ledger)) if args.ledger else None,
    }
    print(f"{'instance':<58} {'scen':<16} land pass teams sub web  cost   min")
    for row in rows:
        print(
            f"{row['instance'][:57]:<58} {row['scenario'][:15]:<16} "
            f"{str(row['landed'])[0]:<4} {str(row['scored_pass'])[0]:<4} {str(row['used_teams'])[0]:<5} "
            f"{row['sub_teams']:<3} {len(row['web_lookups']):<3} {row['cost']:>6.2f} {row['minutes']:>5.1f}"
        )
    print(json.dumps({k: v for k, v in total.items() if k != "ledger"}))
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps({"total": total, "rows": rows}, indent=2) + "\n")


if __name__ == "__main__":
    main()
