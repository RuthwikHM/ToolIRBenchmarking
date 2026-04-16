import os, sys, uuid, requests, base64

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from profiler_utils import now_ms

def main():
    base_url = "http://127.0.0.1:8765"
    trace_id = f"tr_{uuid.uuid4().hex[:12]}"

    print(f"Starting BASIC workflow. Trace ID: {trace_id}")

    audio_b64 = base64.b64encode(b"fake_audio_bytes_representing_a_large_file").decode("utf-8")

    t_wall_start = now_ms()

    # 1. Transcribe
    print("1. Transcribing audio...")
    res1 = requests.post(f"{base_url}/audio/transcribe", json={"audio": audio_b64, "trace_id": trace_id, "node_id": "transcribe_1"}).json()
    transcript = res1["transcript"]

    # 2. Redundant Transcribe (Inefficiency 1)
    print("2. Transcribing again (wasting time/bandwidth)...")
    requests.post(f"{base_url}/audio/transcribe", json={"audio": audio_b64, "trace_id": trace_id, "node_id": "transcribe_2"}).json()

    # 3. Summarize
    print("3. Summarizing transcript...")
    res3 = requests.post(f"{base_url}/text/summarize", json={"text": transcript, "trace_id": trace_id, "node_id": "summarize_1"}).json()
    summary = res3["summary"]

    # 4. Translate (Inefficiency 2: Unnecessary round trip)
    print("4. Translating transcript...")
    res4 = requests.post(f"{base_url}/text/translate", json={"text": transcript, "trace_id": trace_id, "node_id": "translate_1"}).json()

    t_wall_end = now_ms()
    print(f"\n=== Summary ===\nTotal latency: {t_wall_end - t_wall_start}ms\nRPC calls: 4")

if __name__ == "__main__":
    main()
