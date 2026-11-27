"""Exit 0 while the ledger has money left: `budget_left.py LEDGER CAP`."""

import json
import sys

try:
    spent = json.load(open(sys.argv[1])).get("spent", 0)
except (OSError, ValueError):
    spent = 0
print(f"budget: ${spent:.2f} of ${float(sys.argv[2]):.2f} spent")
sys.exit(0 if spent < float(sys.argv[2]) else 1)
