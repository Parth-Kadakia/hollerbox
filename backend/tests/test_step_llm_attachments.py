"""LlmStep with attachments — images pass through; text-y files merge in."""

from __future__ import annotations

import pytest

from hollerbox.core.context import RunContext
from hollerbox.core.workflow import StepDefinition
from hollerbox.providers import MockProvider
from hollerbox.steps.llm import LlmStep


def _ctx(provider, **kw):
    return RunContext.new(providers={"mock": provider}, **kw)


def _step(**config):
    return LlmStep(
        StepDefinition(
            id="llm", type="llm", config={"provider": "mock", "prompt": "hi", **config}
        )
    )


def test_no_attachments_unchanged(tmp_path):
    p = MockProvider(default_text="ok")
    res = _step().run(_ctx(p))
    assert res.status == "success"
    assert p.calls[0]["attachments"] == []
    assert p.calls[0]["prompt"] == "hi"


def test_png_passes_through_as_native_attachment(tmp_path):
    img = tmp_path / "logo.png"
    # 1x1 transparent PNG (smallest valid).
    img.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000005000100020d0a2db40000000049"
            "454e44ae426082"
        )
    )

    p = MockProvider(default_text="describes the pixel")
    res = _step(attachments=[str(img)]).run(_ctx(p))
    assert res.status == "success", res.error

    atts = p.calls[0]["attachments"]
    assert len(atts) == 1
    assert atts[0].media_type == "image/png"
    assert atts[0].name == "logo.png"
    # Prompt is NOT polluted with image text — image goes via native channel.
    assert p.calls[0]["prompt"] == "hi"


def test_text_file_is_folded_into_prompt(tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("the secret word is bumblebee")

    p = MockProvider(default_text="ok")
    _step(attachments=[str(doc)]).run(_ctx(p))

    prompt = p.calls[0]["prompt"]
    assert "[file: notes.txt]" in prompt
    assert "bumblebee" in prompt
    # No native binary block for plain text.
    assert p.calls[0]["attachments"] == []


def test_csv_extracted_as_text(tmp_path):
    f = tmp_path / "rows.csv"
    f.write_text("name,age\nalice,30\nbob,25\n")
    p = MockProvider(default_text="ok")
    _step(attachments=[str(f)]).run(_ctx(p))
    prompt = p.calls[0]["prompt"]
    assert "alice" in prompt and "30" in prompt
    assert "[file: rows.csv]" in prompt


def test_excel_extracted_as_text(tmp_path):
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["item", "qty"])
    ws.append(["widget", 5])
    f = tmp_path / "stock.xlsx"
    wb.save(f)

    p = MockProvider(default_text="ok")
    _step(attachments=[str(f)]).run(_ctx(p))
    prompt = p.calls[0]["prompt"]
    assert "widget" in prompt
    assert "stock.xlsx" in prompt


def test_missing_file_surfaces_error_to_prompt(tmp_path):
    p = MockProvider(default_text="ok")
    res = _step(attachments=[str(tmp_path / "ghost.png")]).run(_ctx(p))
    assert res.status == "success"
    assert "could not be read" in p.calls[0]["prompt"].lower()
