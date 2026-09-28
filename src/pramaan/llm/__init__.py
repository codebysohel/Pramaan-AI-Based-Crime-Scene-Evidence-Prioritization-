"""Optional language-model layer (IBM watsonx.ai Granite).

Pramaan's principle: *the LLM proposes, the rules dispose.* Granite is used to
(1) segment messy prose into exhibits, (2) pick an evidence type from the CLOSED
knowledge-base vocabulary when keyword rules are unsure, and (3) draft the
narrative paragraph of the FSL forwarding memo. It never produces or alters a
priority score. Every LLM output is validated; anything invalid falls back to
the deterministic path, and the run records which provider was used.
"""

from .client import LLMClient, LLMError, NullLLM, WatsonxLLM, get_llm

__all__ = ["LLMClient", "LLMError", "NullLLM", "WatsonxLLM", "get_llm"]
