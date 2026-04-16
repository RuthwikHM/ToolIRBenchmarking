import os, sys, uuid, requests, base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from profiler_utils import build_exec_op_record, append_jsonl, now_ms, obj_id_from_str, guess_bytes

EXEC_OPS_LOG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "profiler_logs", "podcast_exec_ops.jsonl"))

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

    audio_b64 = base64.b64encode(b"fake_audio_bytes_representing_a_large_file").decode("utf-8")
    client_cache = {}

    t_wall_start = now_ms()

    # 1. Transcribe
    print("1. Transcribing audio (Cache Miss)...")
    res1 = requests.post(f"{base_url}/audio/transcribe", json={"audio": audio_b64, "trace_id": trace_id, "node_id": "transcribe_opt_1"}).json()
    transcript = res1["transcript"]
    client_cache[audio_b64] = transcript # Save to cache

    # 2. Redundant Transcribe (Optimized!)
    print("2. Transcribing again (Cache Hit! Skipping network)...")
    if audio_b64 in client_cache:
        emit_cache_hit(trace_id, "transcribe_opt_2", audio_b64, transcript)

    # 3. Fused Summarize & Translate
    print("3. Summarizing and Translating (Fused Operator!)...")
    requests.post(f"{base_url}/text/summarize_and_translate", json={"text": transcript, "trace_id": trace_id, "node_id": "fused_1"}).json()

    t_wall_end = now_ms()
    print(f"\n=== Summary ===\nTotal latency: {t_wall_end - t_wall_start}ms\nRPC calls: 2")

if __name__ == "__main__":
    main()
