"""mlx-whisper transcription backend — Apple Silicon only. Extracted
unchanged from what used to be inline in flow.py's transcribe(); byte-for-
byte identical behavior, just relocated so flow.py can dispatch between this
and stt_windows.py by platform."""

import os
import threading

# The 4-bit build, not the full-precision one: 0.46GB against 1.61GB, which
# is the single largest saving available in the install. A/B'd on identical
# audio across eight clips (names, numbers, currency, filler-heavy speech)
# and it matched the full model on six, beating it on the other two — it
# kept a capital letter and a full stop the full model dropped. Slightly
# faster too. Override to "mlx-community/whisper-large-v3-turbo" (or any
# other mlx-community Whisper repo) if you'd rather have the full weights.
WHISPER_REPO = os.environ.get(
    "WINGVOX_WHISPER_REPO", "mlx-community/whisper-large-v3-turbo-q4"
)

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
