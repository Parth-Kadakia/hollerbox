"""Tests for hollerbox.steps.image.ImageStep — driven via Runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from hollerbox.core.context import RunContext
from hollerbox.core.runner import Runner
from hollerbox.core.workflow import StepDefinition, Workflow
from hollerbox.providers.image_base import ImageProvider, ImageResult
from hollerbox.steps.image import ImageStep
from hollerbox.store import init_db, make_engine, make_session_factory, repo, session_scope


class _FakeImageProvider(ImageProvider):
    name = "fake"

    def __init__(self, images: list[bytes], *, model: str = "fake-img-1"):
        self._images = images
        self._model = model
        self.calls: list[dict] = []

    def generate(self, *, prompt, model=None, size="1024x1024", n=1):
        self.calls.append({"prompt": prompt, "model": model, "size": size, "n": n})
        return ImageResult(images=list(self._images), model=model or self._model)


@pytest.fixture()
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)


def _make_step(config: dict) -> ImageStep:
    defn = StepDefinition(id="render", type="image", config=config)
    return ImageStep(defn)


# --------------------------- step unit tests ---------------------------

def test_single_image_written_to_disk(tmp_path: Path):
    out = tmp_path / "subdir" / "image.png"
    provider = _FakeImageProvider([b"\x89PNG-bytes"])
    step = _make_step({"provider": "fake", "prompt": "an otter", "save_to": str(out)})
    ctx = RunContext.new(image_providers={"fake": provider})

    result = step.run(ctx)
    assert result.status == "success"
    assert out.exists()
    assert out.read_bytes() == b"\x89PNG-bytes"
    assert result.output["paths"] == [str(out.resolve())]
    assert result.output["n"] == 1
    assert result.output["bytes_total"] == len(b"\x89PNG-bytes")
    assert result.output["provider"] == "fake"


def test_multiple_images_get_indexed_suffix(tmp_path: Path):
    out = tmp_path / "img.png"
    provider = _FakeImageProvider([b"one", b"two", b"three"])
    step = _make_step({"provider": "fake", "prompt": "x", "save_to": str(out), "n": 3})
    ctx = RunContext.new(image_providers={"fake": provider})

    result = step.run(ctx)
    assert result.status == "success"
    expected = sorted([tmp_path / "img_0.png", tmp_path / "img_1.png", tmp_path / "img_2.png"])
    assert sorted(Path(p) for p in result.output["paths"]) == expected
    assert (tmp_path / "img_0.png").read_bytes() == b"one"
    assert (tmp_path / "img_2.png").read_bytes() == b"three"


def test_provider_not_registered_fails_cleanly(tmp_path: Path):
    step = _make_step({"provider": "missing", "prompt": "x", "save_to": str(tmp_path / "x.png")})
    ctx = RunContext.new(image_providers={"fake": _FakeImageProvider([b"x"])})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "missing" in (result.error or "")
    assert not (tmp_path / "x.png").exists()


def test_provider_exception_becomes_step_failure(tmp_path: Path):
    class Boom(ImageProvider):
        name = "boom"

        def generate(self, **kw):
            raise RuntimeError("upstream 500")

    step = _make_step({"provider": "boom", "prompt": "x", "save_to": str(tmp_path / "x.png")})
    ctx = RunContext.new(image_providers={"boom": Boom()})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "upstream 500" in (result.error or "")


def test_empty_image_list_is_a_failure(tmp_path: Path):
    step = _make_step({"provider": "fake", "prompt": "x", "save_to": str(tmp_path / "x.png")})
    ctx = RunContext.new(image_providers={"fake": _FakeImageProvider([])})
    result = step.run(ctx)
    assert result.status == "failed"
    assert "0 images" in (result.error or "")


def test_default_destructive_is_true():
    step = _make_step({"provider": "fake", "prompt": "x", "save_to": "/tmp/x.png"})
    assert step.is_destructive is True


def test_template_resolution_in_prompt_and_path(tmp_path: Path):
    out = tmp_path / "pic.png"
    provider = _FakeImageProvider([b"templated-bytes"])
    defn = StepDefinition(
        id="render",
        type="image",
        config={
            "provider": "fake",
            "prompt": "draw ${inputs.subject}",
            "save_to": "${inputs.dir}/pic.png",
        },
    )
    step = ImageStep(defn)
    ctx = RunContext.new(
        inputs={"subject": "an otter", "dir": str(tmp_path)},
        image_providers={"fake": provider},
    )
    result = step.run(ctx)
    assert result.status == "success"
    assert out.read_bytes() == b"templated-bytes"
    assert provider.calls[0]["prompt"] == "draw an otter"


def test_settings_default_image_provider_fallback(tmp_path: Path):
    out = tmp_path / "x.png"
    provider = _FakeImageProvider([b"x"])
    defn = StepDefinition(
        id="r", type="image", config={"prompt": "x", "save_to": str(out)}  # no `provider`
    )
    step = ImageStep(defn)
    ctx = RunContext.new(
        settings={"default_image_provider": "fake"},
        image_providers={"fake": provider},
    )
    result = step.run(ctx)
    assert result.status == "success"


# --------------------------- Runner-driven test ---------------------------

def test_runner_threads_image_providers_into_ctx(session_factory, tmp_path: Path):
    out = tmp_path / "via-runner.png"
    provider = _FakeImageProvider([b"runner-bytes"])
    runner = Runner(session_factory, image_providers={"fake": provider})
    wf = Workflow(
        name="image_wf",
        steps=[
            StepDefinition(
                id="render",
                type="image",
                config={
                    "provider": "fake",
                    "prompt": "via runner",
                    "save_to": str(out),
                },
            )
        ],
    )
    result = runner.execute(wf)
    assert result.status == "success"
    assert out.read_bytes() == b"runner-bytes"
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        assert rows[0].output["paths"] == [str(out.resolve())]
        assert rows[0].output["provider"] == "fake"


def test_dry_run_does_not_write_image(session_factory, tmp_path: Path):
    """Image step is default_destructive=True, so dry-run must skip it."""
    out = tmp_path / "dry.png"
    provider = _FakeImageProvider([b"x"])
    runner = Runner(session_factory, image_providers={"fake": provider})
    wf = Workflow(
        name="dr",
        steps=[
            StepDefinition(
                id="render",
                type="image",
                config={"provider": "fake", "prompt": "x", "save_to": str(out)},
            )
        ],
    )
    result = runner.execute(wf, dry_run=True)
    assert result.status == "success"
    assert not out.exists()
    with session_scope(session_factory) as s:
        rows = list(repo.list_step_runs(s, result.run_id))
        assert rows[0].status == "dry_run"
        assert provider.calls == []  # provider never called
