"""Local meeting minutes built on the finished recording transcript."""

from .api import setup_minutes
from .generator import MinutesService
from .inference import MinutesEngine, MinutesError

__all__ = ['MinutesEngine', 'MinutesError', 'MinutesService', 'setup_minutes']
