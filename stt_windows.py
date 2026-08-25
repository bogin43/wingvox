"""faster-whisper (CTranslate2) transcription backend for Windows. Segment
objects expose the same text/no_speech_prob/compression_ratio fields as
mlx-whisper's segment dicts (both are heuristics from Whisper's own decoder),
so flow.py's hallucination filters need no changes — only this module's
run_model() differs from stt_mac's."""

import os
import threading

import platform_compat as pc


def _configured_language() -> str:
    """Whisper language code from language.txt, or "en" if unset/missing.

    Duplicates the handful of lines in flow.py's load_language_choice()
    rather than importing it: flow.py imports this module near its own top,
    before its own LANGUAGE_PATH/load_language_choice() are even defined,
    so importing back the other way isn't available here."""
    try:
        code = (pc.data_dir() / "language.txt").read_text(encoding="utf-8").strip().lower()
        return code or "en"
    except OSError:
        return "en"


# large-v3-turbo (the Mac default) is fast there because mlx runs it on
# Apple Silicon's GPU/Neural Engine. On a random Windows laptop with no GPU,
# the same model on CPU would feel sluggish for a push-to-talk tool where
# perceived latency matters — default to a CPU-safe small model instead, with
# an escape hatch for anyone who does have a CUDA GPU.
#
# base.en/base over small.en/small: measured on a real low-power laptop CPU
# (i5-8250U, no CUDA) -- small.en took long enough per dictation that
# perceived latency was the top complaint about the Windows build. base.en
# decoded a benchmark clip roughly 3x faster than small.en there (1.15s vs
# 3.59s for a 4s clip) and is about a third the download size, at a real
# but modest accuracy cost -- an explicit trade a user asked for after
# comparing against the Mac build's speed. WINGVOX_WHISPER_MODEL is still
# there to go back to small.en/small (or up to medium/large) for anyone
# who'd rather trade the speed back for accuracy.
#
# base.en (English-only) and base (multilingual) are the same size/speed
# class -- the only difference is language coverage -- so there's no CPU-
# latency cost to picking the right one automatically from language.txt,
# instead of leaving language.txt and WINGVOX_WHISPER_MODEL to be paired up
# by hand. Previously: setting language.txt to anything but English was
# silently ineffective on Windows, since an .en-suffixed model can't decode
# other languages no matter what language= is passed to transcribe() --
# confirmed by a real user, who got fluent-sounding nonsense (Portuguese
# transcribed as vaguely-similar-sounding English words) rather than an
# error.
WHISPER_MODEL = os.environ.get(
    "WINGVOX_WHISPER_MODEL",
    "base.en" if _configured_language() == "en" else "base",
)

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


def run_model(audio, prompt, language="en"):
    """Returns a list of segment dicts with at least text/no_speech_prob/
    compression_ratio, matching stt_mac.run_model's contract.

    language is accepted for parity with stt_mac's signature, but has no
    effect on which weights get loaded -- WHISPER_MODEL above already picks
    "small.en" vs "small" from language.txt at import time, before this is
    ever called."""
    model = _get_model()
    with _transcribe_lock:
        segments, _info = model.transcribe(
            audio, language=language, initial_prompt=prompt,
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
