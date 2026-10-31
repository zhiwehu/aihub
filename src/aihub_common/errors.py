"""The single error type crossing the model-service boundary."""

__all__ = ["ProviderError"]


class ProviderError(RuntimeError):
    """A model provider failed with a stable, machine-readable code.

    The code is what reaches the client (``provider_http_503``,
    ``local_model_busy``, ``invalid_transcript``…). Messages are not carried
    across the boundary: user-facing text is chosen by the caller so that it can
    stay localised and never leak provider detail.
    """

    def __init__(self, code):
        self.code = code
        super().__init__(code)
