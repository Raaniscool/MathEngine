"""Application error types. The API maps these to HTTP status codes in api/app.py."""


class MathEngineError(Exception):
    """Base class for errors that are safe to show to the user."""


class NotFoundError(MathEngineError):
    """A concept, exercise or hint does not exist (or is not published)."""


class BadRequestError(MathEngineError):
    """The request is well-formed but asks for something that does not exist, e.g. hint 9 of 2."""


class IndexNotBuiltError(MathEngineError):
    """The generated knowledge index is missing. Run `python -m mathengine.cli build-index`."""
