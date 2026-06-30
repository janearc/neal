# The model seam: where a model first enters neal.
#
# neal resolves a logical model name (e.g. "mistral") to a backend through delightd's
# service discovery and runs a single completion, fail-closed -- via the good-citizen
# model client, the same path the rest of the fleet uses. neal never invents a local
# fallback: if nothing healthy serves the model, the error propagates. Silence over
# fabrication -- the same discipline the graph holds.
#
# ModelClient is the injectable seam: the extraction engine takes one, so tests pass a
# fake and never touch the mesh. DiscoveryModel is the real default.

from __future__ import annotations

from typing import Protocol, runtime_checkable

DEFAULT_MODEL = "mistral"


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, prompt: str) -> str: ...


class DiscoveryModel:
    # the real ModelClient: resolves `name` via delightd discovery (good_citizen,
    # fail-closed) and runs one non-streaming completion. complete() may raise
    # good_citizen.model.ModelUnavailable when nothing healthy serves the model --
    # neal lets that propagate rather than fabricating a result.
    def __init__(self, name: str = DEFAULT_MODEL, *, delightd_url: str | None = None):
        self.name = name
        self.delightd_url = delightd_url

    def complete(self, prompt: str) -> str:
        from good_citizen import model  # lazy: keep the mesh dependency out of import time

        return model.generate(self.name, prompt, delightd_url=self.delightd_url)
