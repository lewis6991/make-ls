"""makels package."""

__version__ = "0.1.0"

from .server import MakelsLanguageServer, create_server

__all__ = ["MakelsLanguageServer", "__version__", "create_server"]
