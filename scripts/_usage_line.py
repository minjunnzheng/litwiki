#!/usr/bin/env python3
"""Print a one-line token/cost summary from a grok --output-format json log."""
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    u = d.get("usage") or {}
    print("${:.4f}  tot={:,}  out={:,}  calls={}".format(
        d.get("total_cost_usd", 0) or 0,
        u.get("total_tokens", 0), u.get("output_tokens", 0),
        (d.get("modelUsage") or {}).get(next(iter(d.get("modelUsage") or {"x": {}})), {}).get("modelCalls", "?")))
except Exception as e:
    print("usage n/a ({})".format(type(e).__name__))
