"""Pramaan (प्रमाण, "proof") — explainable crime-scene evidence triage for Indian FSLs.

One deterministic engine exposed through three surfaces: an MCP server (for any
MCP client), a REST API + web dashboard, and a CLI. See ``pramaan.pipeline.run_triage``.
"""

from .config import ENGINE_VERSION as __version__

__all__ = ["__version__"]
