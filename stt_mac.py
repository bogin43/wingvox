"""mlx-whisper transcription backend — Apple Silicon only. Extracted
unchanged from what used to be inline in flow.py's transcribe(); byte-for-
byte identical behavior, just relocated so flow.py can dispatch between this
and stt_windows.py by platform."""

import threading

WHISPER_REPO = "mlx-community/whisper-large-v3-turbo"

_whisper_lock = threading.Lock()


def run_model(audio, prompt):
    """Returns a list of segment dicts (mlx_whisper's own dict format) with
    at least text/no_speech_prob/compression_ratio — flow.py's
    hallucination filters read these fields directly."""
    import mlx_whisper
    with _whisper_lock:
        result = mlx_whisper.transcribe(
            audio, path_or_hf_repo=WHISPER_REPO, initial_prompt=prompt,
            language="en", fp16=True, condition_on_previous_text=False,
        )
    return result["segments"]
