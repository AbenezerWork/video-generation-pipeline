"""``vidpipe ui``: a local web console for one project (needs the optional ``ui`` extra).

The server only reads the project and its run state for now; runs are started from the CLI.
"""

from vidpipe.ui.app import create_app

__all__ = ["create_app"]
