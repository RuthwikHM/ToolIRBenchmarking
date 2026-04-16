# ToolIR Benchmark Example: Podcast Processor

## Overview

This benchmark demonstrates two common tool-based workflow inefficiencies: **redundant invocations** and **unnecessary network round-trips**. The workflow simulates an AI-driven podcast processing pipeline that transcribes audio, summarizes the text, and translates it.

The basic version wastes network bandwidth and server compute by transcribing the same audio twice, and by downloading intermediate results just to re-upload them. The optimized version applies **client-side result memoization** and **server-side operator fusion**, reducing network calls from 4 to 2 and delivering a ~35% speedup.

---

## Workflow Description

### Basic Version

```text
Client → POST /audio/transcribe → Server      (call 1: audio)
Client → POST /audio/transcribe → Server      (call 2: SAME audio!)
Client → POST /text/summarize   → Server      (call 3: upload transcript)
Client → POST /text/translate   → Server      (call 4: upload transcript again!)

Inefficiencies:
1. Identical transcription computation repeated 2 times.
2. The transcript is downloaded to the client only to be immediately uploaded again for translation, failing to use shared server state.
```

### Optimized Version

```text
Client → POST /audio/transcribe              → Server   (call 1: compute + cache)
Client → [CACHE HIT, no RPC]                            (call 2: served locally)
Client → POST /text/summarize_and_translate  → Server   (call 3: fused operation)

Optimizations:
1. Result memoization keyed by audio hash (Call 2 served from in-process cache).
2. Operator fusion (Call 3 computes both summary and translation in a single RPC).
```

## Optimizations Applied

- **Result memoization / deduplication**: Caches the server response keyed by the audio data hash. On a cache hit, it returns the stored transcript without making an RPC call.
- **Operator Fusion**: Instead of calling summarize and translate sequentially and moving data back and forth, the client calls a fused /text/summarize_and_translate endpoint. The server handles both operations internally, saving a complete network round-trip.

## Installation

```bash
pip install -r requirements.txt
```

---

## How to Run

### Step 1: Start the server

```bash
python server/podcast_server.py
```

The server listens on `http://127.0.0.1:8765` by default.
EXEC_OP records are written to `profiler_logs/podcast_exec_ops.jsonl`.

### Step 2: Run the basic (unoptimized) version

```bash
python client/basic_client.py
```

Makes 4 full RPC calls, including a redundant transcription and unfused text processing.

### Step 3: Run the optimized version

```bash
python client/optimized_client.py
```

Makes only 2 RPC calls. Uses client-side caching and a fused server endpoint.

### Step 4: Analyze the traces

```bash
python analysis/parse_and_compare.py
```

Reads profiler_logs/podcast_exec_ops.jsonl and prints a structured comparison of the two traces, including detected optimization opportunities.

---

## Performance Results (Reference Machine)

Run on a standard development machine. The server uses time.sleep() to simulate realistic compute times for audio/text models.

| Version   | Latency  | RPC Calls | Data Transferred |
|-----------|----------|-----------|------------------|
| Basic     | ~1016ms  | 4         | ~387B            |
| Optimized | ~657ms   | 2         | ~271B            |
| Reduction | ~35.3%   | 50.0%     | 30.0%            |

Hardware: CPU only (simulated compute)
Input: Simulated audio byte payload

*Exact numbers depend on system load, but the RPC reduction is deterministic.*

---

## EXEC_OP Record Format

Each tool invocation emits one EXEC_OP record to the JSONL log:

```json
{
  "kind": "EXEC_OP",
  "op": "tool.caption_interrogate",
  "trace_id": "tr_abc123def456",
  "event_id": "ev_0011223344aa",
  "node_id": "interrogate_1",
  "args_hash": "obj:b64img:a3f9c12d45e6f789",
  "inputs_meta": {
    "image": {"id": "obj:b64img:a3f9c12d45e6f789", "bytes": 102400, "type": "base64_image"},
    "model": {"id": "const:clip", "bytes": 4, "type": "str"}
  },
  "outputs_meta": {
    "caption": {"id": "obj:txt:bc12de34f5678901", "bytes": 48, "type": "str"}
  },
  "t_start_ms": 1711900000000,
  "t_end_ms":   1711900000215,
  "latency_ms": 215,
  "payload_in_bytes": 102400,
  "payload_out_bytes": 48,
  "stage_ms": {"decode": 10, "compute": 200, "encode": 5},
  "error": null,
  "status_code": 200,
  "extra": {"cache_hit": false}
}
```

Key fields:
- `trace_id` — unique per client run; shared across all nodes in one workflow
- `args_hash` — content-addressed hash of inputs (never the raw payload)
- `inputs_meta` / `outputs_meta` — object IDs and sizes (no raw data)
- `stage_ms` — server-side breakdown: decode → compute → encode
- `extra.cache_hit` — `true` for client-side cache hits (latency_ms = 0)
