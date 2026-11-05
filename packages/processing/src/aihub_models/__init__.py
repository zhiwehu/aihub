"""AIHub model runtime: ASR, LLM, TTS, diarization, cleanup and meeting minutes.

Nothing here imports the server. The boundary in both directions is HTTP:

* the server starts a worker per model and calls ``/v1/audio/transcriptions``,
  ``/v1/chat/completions`` and ``/v1/audio/speech``;
* long jobs (denoise, re-diarization, minutes) go through this package's own
  service app on a single loopback port.

The only shared code is ``aihub-common``, which holds the model-free helpers.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
