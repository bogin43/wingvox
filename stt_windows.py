"""faster-whisper (CTranslate2) transcription backend for Windows. Segment
objects expose the same text/no_speech_prob/compression_ratio fields as
mlx-whisper's segment dicts (both are heuristics from Whisper's own decoder),
so flow.py's hallucination filters need no changes — only this module's
run_model() differs from stt_mac's."""

import os
import threading

# large-v3-turbo (the Mac default) is fast there because mlx runs it on
# Apple Silicon's GPU/Neural Engine. On a random Windows laptop with no GPU,
# the same model on CPU would feel sluggish for a push-to-talk tool where
# perceived latency matters — default to a CPU-safe small model instead, with
# an escape hatch for anyone who does have a CUDA GPU.
WHISPER_MODEL = os.environ.get("WINGVOX_WHISPER_MODEL", "small.en")

_model = None
_model_lock = threading.Lock()
_transcribe_lock = threading.Lock()


def _get_model():
    # WhisperModel(...) is a constructor, not a cached lookup like
    # mlx_whisper.transcribe() — calling it fresh on every press would
    # reload weights from disk every time. Must be a module-level singleton.
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                _model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="auto")
    return _model


def run_model(audio, prompt):
    """Returns a list of segment dicts with at least text/no_speech_prob/
    compression_ratio, matching stt_mac.run_model's contract."""
    model = _get_model()
    with _transcribe_lock:
        segments, _info = model.transcribe(
            audio, language="en", initial_prompt=prompt,
            condition_on_previous_text=False,
            # beam_size=5 (faster-whisper's default) barely changes accuracy
            # on short push-to-talk clips but costs real time on CPU --
            # beam_size=1 (greedy decoding) measured ~10% faster in a VM
            # benchmark with no noticeable transcription quality drop.
            beam_size=1,
            # Every recording has some silence padding (the gap between
            # pressing the hotkey and actually speaking, and again before
            # releasing it) -- vad_filter skips those silent stretches
            # instead of running the full model over them. onnxruntime (its
            # only extra dependency) is already bundled via faster-whisper.
            # threshold is lowered from Silero's 0.5 default: on a weak/
            # attenuated mic signal (a virtual/VM audio device, or just a
            # user speaking quietly), the default has a real risk of
            # misclassifying genuine quiet speech as silence and dropping it
            # entirely before transcription ever sees it -- surfacing as a
            # false "Heard nothing" for words that were actually spoken.
            vad_filter=True,
            vad_parameters={"threshold": 0.35},
        )
        # segments is a lazy generator — must materialize it here, inside
        # the lock, before returning (a generator can only be consumed
        # once, and flow.py's filters may want to inspect it more than once).
        return [
            {
                "text": seg.text,
                "no_speech_prob": seg.no_speech_prob,
                "compression_ratio": seg.compression_ratio,
            }
            for seg in segments
        ]
