import good_citizen.model as gcmodel
import pytest

from neal.model import DEFAULT_MODEL, DiscoveryModel, ModelClient


class _FakeModel:
    def __init__(self):
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return "ok"


def test_fake_satisfies_the_seam_protocol():
    assert isinstance(_FakeModel(), ModelClient)


def test_discovery_model_delegates_to_good_citizen(monkeypatch):
    captured = {}

    def fake_generate(name, prompt, delightd_url=None, **opts):
        captured.update(name=name, prompt=prompt, delightd_url=delightd_url)
        return "the completion"

    monkeypatch.setattr(gcmodel, "generate", fake_generate)

    out = DiscoveryModel(delightd_url="http://d:8088").complete("hello?")

    assert out == "the completion"
    assert captured == {
        "name": DEFAULT_MODEL,
        "prompt": "hello?",
        "delightd_url": "http://d:8088",
    }


def _mistral_reachable():
    try:
        return gcmodel.resolve("mistral") is not None
    except Exception:
        return False


@pytest.mark.skipif(not _mistral_reachable(), reason="delightd/mistral not reachable")
def test_live_discovery_completion():
    out = DiscoveryModel().complete("Reply with the single word: pong.")
    assert isinstance(out, str) and out
