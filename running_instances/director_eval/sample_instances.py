"""Draw a fixed random sample of instances, the same for a given seed.

    python sample_instances.py --seed 20261127 --num 30 --out sample.txt

Writes one `<family> <instance id>` line per instance, the format `run.py
--instances-file` and `eval.grade` read. The instances are drawn from every
corpus folder together, so a sample can span v1 and v2.
"""

from __future__ import annotations

import argparse
import pathlib
import random

REPO = pathlib.Path(__file__).resolve().parents[2]
FOLDERS = {
    "v1": [REPO / "dataset" / "v1" / "generated", REPO / "dataset" / "v1" / "seeds"],
    "v2": [REPO / "dataset" / "v2" / "generated"],
}


def instances(corpora: list[str], families: list[str]) -> list[tuple[str, str]]:
    found = set()
    for corpus in corpora:
        for folder in FOLDERS[corpus]:
            for family in families:
                for file in (folder / family).glob("*.json"):
                    if not file.name.endswith(".verification.json"):
                        found.add((family, file.stem))
    # Sorted, so that the draw does not depend on the order of the file system.
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--num", type=int, required=True, help="how many to draw at most")
    parser.add_argument("--corpus", default="v1,v2", help="v1, v2 or both, comma separated")
    parser.add_argument("--family", default="contradictory,complementary")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    pool = instances(args.corpus.split(","), args.family.split(","))
    drawn = random.Random(args.seed).sample(pool, min(args.num, len(pool)))
    lines = [f"# seed={args.seed} num={args.num} of {len(pool)} ({args.corpus}; {args.family})"]
    lines += [f"{family} {name}" for family, name in sorted(drawn)]
    pathlib.Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"{len(drawn)} of {len(pool)} instances -> {args.out}")


if __name__ == "__main__":
    main()
