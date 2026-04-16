# -*- coding: utf-8 -*-
"""parse_and_compare.py — ToolIR Trace Analysis (Podcast Processor)

Reads ../profiler_logs/podcast_exec_ops.jsonl and performs a simple
ToolIR pre-pass analysis over the recorded traces.
"""

import argparse
import collections
import json
import os
import sys
from typing import Any, Dict, List

EXEC_OPS_LOG = os.path.join(
    os.path.dirname(__file__), "..", "profiler_logs", "podcast_exec_ops.jsonl"
)
EXEC_OPS_LOG = os.path.normpath(EXEC_OPS_LOG)

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def load_records(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        print(f"ERROR: log file not found: {path}")
        print("Run the basic and optimized clients first.")
        sys.exit(1)
    records = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"WARNING: skipping malformed line {lineno}: {exc}")
    return records

def group_by_trace(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for r in records:
        if r.get("kind") == "EXEC_OP":
            tid = r.get("trace_id", "tr_unknown")
            groups[tid].append(r)
    return dict(groups)

def analyze_trace(trace_id: str, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_latency_ms = sum(n.get("latency_ms", 0) for n in nodes)
    total_payload_in = sum(n.get("payload_in_bytes", 0) or 0 for n in nodes)
    total_payload_out = sum(n.get("payload_out_bytes", 0) or 0 for n in nodes)
    total_bytes = total_payload_in + total_payload_out

    # Detect repeated invocations (Memoization candidate)
    op_arg_counts: Dict[str, int] = collections.Counter(
        f"{n.get('op')}:{n.get('args_hash', 'none')}"
        for n in nodes
    )
    repeated_invocations = {k: v for k, v in op_arg_counts.items() if v > 1}

    # Count cache hits
    cache_hits = sum(
        1 for n in nodes
        if n.get("extra", {}) and n["extra"].get("cache_hit", False)
    )
    rpc_calls = len(nodes) - cache_hits

    opportunities = []

    # 1. Report Memoization Opportunities
    if repeated_invocations:
        for key, count in repeated_invocations.items():
            op_name = key.split(":")[0]
            # Ignore cache hits from the count when suggesting opportunities
            if cache_hits == 0:
                opportunities.append(
                    f"Repeated invocations: {count} calls with same input "
                    f"for '{op_name}'\n"
                    f"          → Memoization candidate"
                )

    # If multiple DIFFERENT tools are called on the exact same input
    hash_to_ops = collections.defaultdict(set)
    for n in nodes:
        h = n.get("args_hash")
        op = n.get("op")
        if h and op:
            hash_to_ops[h].add(op)

    for h, ops in hash_to_ops.items():
        if len(ops) > 1 and cache_hits == 0: # Only warn in basic trace
            opportunities.append(
                f"Shared input detected: Tools ({', '.join(ops)}) share the exact same input.\n"
                f"          → Operator Fusion candidate"
            )

    return {
        "trace_id": trace_id,
        "node_count": len(nodes),
        "rpc_calls": rpc_calls,
        "cache_hits": cache_hits,
        "total_latency_ms": total_latency_ms,
        "total_bytes": total_bytes,
        "total_payload_in": total_payload_in,
        "total_payload_out": total_payload_out,
        "opportunities": opportunities,
    }

def fmt_bytes(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    if b < 1024 ** 2:
        return f"{b/1024:.1f}KB"
    return f"{b/1024**2:.2f}MB"

# ---------------------------------------------------------------------------
# Heuristic: classify basic vs optimized
# ---------------------------------------------------------------------------

def classify_traces(trace_analyses: List[Dict[str, Any]]) -> tuple:
    if len(trace_analyses) == 0:
        return None, None
    if len(trace_analyses) == 1:
        return trace_analyses[0], None

    # Determine which is optimized based on cache hits or fewer RPCs
    optimized_candidates = [t for t in trace_analyses if t["cache_hits"] > 0 or t["node_count"] < max(a["node_count"] for a in trace_analyses)]
    basic_candidates = [t for t in trace_analyses if t not in optimized_candidates]

    if optimized_candidates and basic_candidates:
        return basic_candidates[0], optimized_candidates[0]

    sorted_traces = sorted(trace_analyses, key=lambda t: -t["node_count"])
    return sorted_traces[0], sorted_traces[-1]

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ToolIR trace analyzer")
    parser.add_argument("--log", default=EXEC_OPS_LOG)
    args = parser.parse_args()

    records = load_records(args.log)
    by_trace = group_by_trace(records)

    if not by_trace:
        print("No EXEC_OP records found in log.")
        sys.exit(1)

    analyses = [analyze_trace(tid, nodes) for tid, nodes in by_trace.items()]

    print("=" * 60)
    print("=== ToolIR Analysis ===")
    print("=" * 60)
    print(f"Log file: {args.log}")
    print(f"Traces found: {len(analyses)}\n")

    basic, optimized = classify_traces(analyses)

    def print_trace(label: str, a: Dict[str, Any]) -> None:
        print(f"{label} trace ({a['trace_id']}):")
        print(f"  Nodes (total):          {a['node_count']}  (RPC={a['rpc_calls']}, cache_hit={a['cache_hits']})")
        print(f"  Total latency:          {a['total_latency_ms']}ms")
        print(f"  Total data transferred: {fmt_bytes(a['total_bytes'])}")

        if a["opportunities"]:
            print("  Optimization opportunities detected:")
            for opp in a["opportunities"]:
                for line in opp.split("\n"):
                    print(f"    - {line}")
        else:
            print("  No optimization opportunities detected (Fully Optimized!).")
        print()

    if basic:
        print_trace("Basic", basic)
    if optimized and optimized is not basic:
        print_trace("Optimized", optimized)

    if basic and optimized and optimized is not basic:
        lat_basic = max(basic["total_latency_ms"], 1)
        lat_opt = max(optimized["total_latency_ms"], 1)
        bytes_basic = max(basic["total_bytes"], 1)
        bytes_opt = max(optimized["total_bytes"], 1)

        lat_reduction = (1 - lat_opt / lat_basic) * 100
        bytes_reduction = (1 - bytes_opt / bytes_basic) * 100
        rpc_reduction = (1 - optimized["rpc_calls"] / max(basic["rpc_calls"], 1)) * 100

        print("Improvement:")
        print(f"  Latency reduction:  {lat_reduction:.1f}% ({basic['total_latency_ms']}ms → {optimized['total_latency_ms']}ms)")
        print(f"  RPC reduction:      {rpc_reduction:.1f}% ({basic['rpc_calls']} RPC calls → {optimized['rpc_calls']} RPC calls)")
        print(f"  Data reduction:     {bytes_reduction:.1f}% ({fmt_bytes(bytes_basic)} → {fmt_bytes(bytes_opt)})\n")

if __name__ == "__main__":
    main()
