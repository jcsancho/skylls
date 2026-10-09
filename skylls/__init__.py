"""skylls - share agent skills, agents and swarms through your own private GitHub repos."""

__version__ = "1.3.1"  # bump on every change to the tool (see CHANGES.md)

from skylls.cli import main  # noqa: E402  (after __version__: cli imports it)

__all__ = ["main", "__version__"]
