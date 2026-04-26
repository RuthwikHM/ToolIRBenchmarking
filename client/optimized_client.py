import os
import sys
import uuid
import requests
import base64
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from profiler_utils import build_exec_op_record, append_jsonl, now_ms, obj_id_from_str, guess_bytes

EXEC_OPS_LOG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "profiler_logs", "podcast_exec_ops.jsonl"))
AUDIO_FILE = "sample.wav"

def emit_cache_hit(trace_id, node_id, audio_b64, transcript):
    t = now_ms()
    record = build_exec_op_record(
        trace_id=trace_id, op="tool.transcribe", node_id=node_id,
        args_hash=obj_id_from_str(audio_b64, kind="b64audio"),
        inputs_meta={"audio": {"id": obj_id_from_str(audio_b64, kind="b64audio"), "bytes": 0, "type": "b64audio"}},
        outputs_meta={"transcript": {"id": obj_id_from_str(transcript, kind="txt"), "bytes": guess_bytes(transcript), "type": "str"}},
        t_start_ms=t, t_end_ms=t, payload_in_bytes=0, payload_out_bytes=guess_bytes(transcript),
        status_code=200, extra={"cache_hit": True}
    )
    append_jsonl(EXEC_OPS_LOG, record)

def main():
    base_url = "http://127.0.0.1:8765"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"
    print(f"Starting OPTIMIZED workflow. Trace ID: {trace_id}")

    if not os.path.exists(AUDIO_FILE):
        print(f"ERROR: Please place a real audio file named '{AUDIO_FILE}' in this directory.")
        return

    with open(AUDIO_FILE, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")

    # Hash the heavy audio payload to use as a lightweight dictionary key
    audio_hash = hashlib.md5(audio_b64.encode("utf-8")).hexdigest()
    client_cache = {}

    t_wall_start = now_ms()

    # 1. Transcribe (Cache Miss)
    print("1. Transcribing audio (Cache Miss)...")
    res1 = requests.post(f"{base_url}/audio/transcribe", json={"audio": audio_b64, "trace_id": trace_id, "node_id": "transcribe_opt_1"}).json()

    transcript = res1["transcript"]
    transcript_id = res1["transcript_id"]

    # Store both text and ID in the cache
    client_cache[audio_hash] = {"transcript": transcript, "transcript_id": transcript_id}

    # 2. Redundant Transcribe
    print("2. Transcribing again (Cache Hit! Skipping network)...")
    if audio_hash in client_cache:
        cached_data = client_cache[audio_hash]
        emit_cache_hit(trace_id, "transcribe_opt_2", audio_b64, cached_data["transcript"])

    # 3. Fused Summarize & Translate
    print("3. Summarizing and Translating (Fused Operator + Dead-Output ID passing!)...")

    res3 = requests.post(
        f"{base_url}/text/summarize_and_translate",
        json={"text_id": transcript_id, "trace_id": trace_id, "node_id": "fused_1"}
    ).json()

    t_wall_end = now_ms()
    print(f"\n=== Summary ===")
    print(f"Total latency: {t_wall_end - t_wall_start}ms")
    print(f"RPC calls: 2")

if __name__ == "__main__":
    main()
