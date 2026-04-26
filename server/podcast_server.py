# -*- coding: utf-8 -*-
"""podcast_server.py

ToolIR Benchmark: Podcast Processor (Audio -> Text -> Summary/Translation)
Updated for Phase II: Real models and dead-output ablation.
"""
import os
import sys
import time
import base64
import tempfile
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# --- Real Model Dependencies ---
import whisper
import nltk
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize, sent_tokenize
from transformers import pipeline

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from profiler_utils import (
    append_jsonl, build_exec_op_record, guess_bytes, now_ms, obj_id_from_str,
)

EXEC_OPS_LOG = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "profiler_logs", "podcast_exec_ops.jsonl"))
app = FastAPI(title="ToolIR Podcast Server")

# --- Initialize Models (Loads once on startup) ---
print("Loading Whisper model...")
whisper_model = whisper.load_model("tiny")

print("Downloading NLTK data...")
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk.download('stopwords', quiet=True)

print("Loading Translation model...")
translator = pipeline("translation", model="Helsinki-NLP/opus-mt-en-es")

# Stores intermediate outputs so we only need to pass IDs over HTTP
DATA_STORE = {}

# --- Request/Response Models ---
class AudioRequest(BaseModel):
    audio: str
    trace_id: Optional[str] = None
    node_id: Optional[str] = None

class TextRequest(BaseModel):
    text: Optional[str] = None
    text_id: Optional[str] = None
    trace_id: Optional[str] = None
    node_id: Optional[str] = None

def nltk_summarize(text: str) -> str:
    stop_words = set(stopwords.words("english"))
    words = word_tokenize(text)

    freq_table = dict()
    for word in words:
        word = word.lower()
        if word in stop_words: continue
        freq_table[word] = freq_table.get(word, 0) + 1

    sentences = sent_tokenize(text)
    sentence_value = dict()
    for sentence in sentences:
        for word, freq in freq_table.items():
            if word in sentence.lower():
                sentence_value[sentence] = sentence_value.get(sentence, 0) + freq

    if len(sentence_value) == 0: return text
    average = int(sum(sentence_value.values()) / len(sentence_value))

    summary = ' '.join([s for s in sentences if s in sentence_value and sentence_value[s] > (1.2 * average)])
    return summary if summary else text

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

    # 1. Decode base64 audio and save to a temporary file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
        tmp_audio.write(base64.b64decode(req.audio))
        tmp_audio_path = tmp_audio.name

    # 2. Run real whisper inference
    try:
        result = whisper_model.transcribe(tmp_audio_path)
        transcript = result["text"]
    finally:
        os.remove(tmp_audio_path)

    t_end = now_ms()

    transcript_id = str(uuid.uuid4())
    DATA_STORE[transcript_id] = transcript

    log_exec_op(req.trace_id or "tr_unk", "tool.transcribe", req.node_id or "node_unk",
                req.audio, transcript, "audio", "transcript", "b64audio", "str", t_start, t_end, {"compute": t_end - t_start})

    return {"transcript": transcript, "transcript_id": transcript_id}


def _get_text_from_req(req: TextRequest) -> str:
    if req.text_id and req.text_id in DATA_STORE:
        return DATA_STORE[req.text_id]
    elif req.text:
        return req.text
    raise HTTPException(status_code=400, detail="Must provide valid 'text' or 'text_id'")


@app.post("/text/summarize")
def summarize(req: TextRequest):
    text_to_process = _get_text_from_req(req)

    t_start = now_ms()
    summary = nltk_summarize(text_to_process)
    t_end = now_ms()

    summary_id = str(uuid.uuid4())
    DATA_STORE[summary_id] = summary

    log_exec_op(req.trace_id or "tr_unk", "tool.summarize", req.node_id or "node_unk",
                text_to_process, summary, "text", "summary", "str", "str", t_start, t_end, {"compute": t_end - t_start})

    return {"summary": summary, "summary_id": summary_id}


@app.post("/text/translate")
def translate(req: TextRequest):
    text_to_process = _get_text_from_req(req)

    t_start = now_ms()
    translation_result = translator(text_to_process, max_length=512)
    translation = translation_result[0]['translation_text']
    t_end = now_ms()

    translation_id = str(uuid.uuid4())
    DATA_STORE[translation_id] = translation

    log_exec_op(req.trace_id or "tr_unk", "tool.translate", req.node_id or "node_unk",
                text_to_process, translation, "text", "translation", "str", "str", t_start, t_end, {"compute": t_end - t_start})

    return {"translation": translation, "translation_id": translation_id}


@app.post("/text/summarize_and_translate")
def summarize_and_translate(req: TextRequest):
    text_to_process = _get_text_from_req(req)

    t_start = now_ms()
    summary = nltk_summarize(text_to_process)

    translation_result = translator(summary, max_length=512)
    translation = translation_result[0]['translation_text']
    t_end = now_ms()

    summary_id = str(uuid.uuid4())
    translation_id = str(uuid.uuid4())
    DATA_STORE[summary_id] = summary
    DATA_STORE[translation_id] = translation

    result_json = f'{{"summary": "{summary}", "translation": "{translation}"}}'

    log_exec_op(req.trace_id or "tr_unk", "tool.summarize_and_translate", req.node_id or "node_unk",
                text_to_process, result_json, "text", "fused_output", "str", "json", t_start, t_end, {"compute": t_end - t_start})

    return {
        "summary": summary,
        "summary_id": summary_id,
        "translation": translation,
        "translation_id": translation_id
    }

if __name__ == "__main__":
    os.makedirs(os.path.dirname(EXEC_OPS_LOG), exist_ok=True)
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
