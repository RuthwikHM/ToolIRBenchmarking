# -*- coding: utf-8 -*-
"""podcast_server.py

ToolIR Benchmark: Podcast Processor (Audio -> Text -> Summary/Translation)
"""
import os
import sys
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from profiler_utils import (
    append_jsonl, build_exec_op_record, guess_bytes, now_ms, obj_id_from_str,
)

EXEC_OPS_LOG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "profiler_logs", "podcast_exec_ops.jsonl"))
app = FastAPI(title="ToolIR Podcast Server")

# --- Request/Response Models ---
class AudioRequest(BaseModel):
    audio: str
    trace_id: Optional[str] = None
    node_id: Optional[str] = None

class TextRequest(BaseModel):
    text: str
    trace_id: Optional[str] = None
    node_id: Optional[str] = None

# --- Helper to log EXEC_OP ---
def log_exec_op(trace_id, op_name, node_id, input_val, output_val, input_name, output_name, input_type, output_type, t_start, t_end, stage):
    in_id = obj_id_from_str(input_val, kind=input_type)
    out_id = obj_id_from_str(output_val, kind=output_type)
    p_in = guess_bytes(input_val)
    p_out = guess_bytes(output_val)

    record = build_exec_op_record(
        trace_id=trace_id, op=op_name, node_id=node_id, args_hash=in_id,
        inputs_meta={input_name: {"id": in_id, "bytes": p_in, "type": input_type}},
        outputs_meta={output_name: {"id": out_id, "bytes": p_out, "type": output_type}},
        t_start_ms=t_start, t_end_ms=t_end, payload_in_bytes=p_in, payload_out_bytes=p_out,
        stage_ms=stage, status_code=200,
    )
    append_jsonl(EXEC_OPS_LOG, record)

@app.post("/audio/transcribe")
def transcribe(req: AudioRequest):
    t_start = now_ms()
    time.sleep(0.3) # Fake AI compute
    transcript = "Fake transcript: Welcome to the podcast about AI..."
    t_end = now_ms()

    log_exec_op(req.trace_id or "tr_unk", "tool.transcribe", req.node_id or "node_unk",
                req.audio, transcript, "audio", "transcript", "b64audio", "str", t_start, t_end, {"compute": 300})
    return {"transcript": transcript}

@app.post("/text/summarize")
def summarize(req: TextRequest):
    t_start = now_ms()
    time.sleep(0.2)
    summary = "Fake Summary: A podcast about AI."
    t_end = now_ms()

    log_exec_op(req.trace_id or "tr_unk", "tool.summarize", req.node_id or "node_unk",
                req.text, summary, "text", "summary", "str", "str", t_start, t_end, {"compute": 200})
    return {"summary": summary}

@app.post("/text/translate")
def translate(req: TextRequest):
    t_start = now_ms()
    time.sleep(0.2)
    translation = "Fake Translation: Un podcast sobre IA."
    t_end = now_ms()

    log_exec_op(req.trace_id or "tr_unk", "tool.translate", req.node_id or "node_unk",
                req.text, translation, "text", "translation", "str", "str", t_start, t_end, {"compute": 200})
    return {"translation": translation}

@app.post("/text/summarize_and_translate")
def summarize_and_translate(req: TextRequest):
    t_start = now_ms()
    time.sleep(0.35)
    result = '{"summary": "Fake Summary", "translation": "Fake Translation"}'
    t_end = now_ms()

    log_exec_op(req.trace_id or "tr_unk", "tool.summarize_and_translate", req.node_id or "node_unk",
                req.text, result, "text", "fused_output", "str", "json", t_start, t_end, {"compute": 350})
    return {"summary": "Fake Summary", "translation": "Fake Translation"}

if __name__ == "__main__":
    os.makedirs(os.path.dirname(EXEC_OPS_LOG), exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
