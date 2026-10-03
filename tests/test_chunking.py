"""Pruebas de fragmentación con el divisor principal y con el alternativo.

Ejecuto cada caso en un proceso aislado con tiempo máximo: si la fragmentación
vuelve a entrar en un bucle, la prueba falla por timeout en lugar de bloquear la suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 30

SIZE = 900
OVERLAP = 120


def _run_isolated(body: str, *, block_splitter: bool) -> list[str]:
    """Ejecuto el código en otro intérprete y devuelvo la lista impresa como JSON."""
    prelude = "import sys, json\n"
    if block_splitter:
        prelude += "sys.modules['langchain_text_splitters'] = None\n"
    script = prelude + textwrap.dedent(body)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"La fragmentación no terminó en {TIMEOUT_SECONDS} s.")
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _fallback_chunks(text: str) -> list[str]:
    body = f"""
    from app.core.config import Settings
    from app.rag import ingestion
    settings = Settings(environment="test", rag_chunk_size={SIZE}, rag_chunk_overlap={OVERLAP})
    print(json.dumps(ingestion.chunk_text(settings, {text!r})))
    """
    return _run_isolated(body, block_splitter=True)


def _window_chunks(text: str, size: int, overlap: int) -> list[str]:
    body = f"""
    from app.rag.ingestion import split_fixed_window
    print(json.dumps(split_fixed_window({text!r}, {size}, {overlap})))
    """
    return _run_isolated(body, block_splitter=True)


def _sample(length: int) -> str:
    # Uso texto sin espacios para que strip() no altere los límites esperados.
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    return "".join(alphabet[i % len(alphabet)] for i in range(length))


def test_fallback_empty_text_returns_no_chunks() -> None:
    assert _fallback_chunks("") == []


def test_fallback_whitespace_only_returns_no_chunks() -> None:
    assert _fallback_chunks("   \n\n  ") == []


def test_fallback_text_shorter_than_chunk() -> None:
    text = _sample(SIZE - 1)
    assert _fallback_chunks(text) == [text]


def test_fallback_text_exactly_chunk_size() -> None:
    # Este caso repetía indefinidamente el último fragmento antes de la corrección.
    text = _sample(SIZE)
    assert _fallback_chunks(text) == [text]


def test_fallback_long_text_covers_everything_with_overlap() -> None:
    text = _sample(SIZE * 5 + 37)
    chunks = _fallback_chunks(text)
    step = SIZE - OVERLAP

    assert len(chunks) == 6
    for index, chunk in enumerate(chunks):
        start = index * step
        assert chunk == text[start : start + SIZE]
    for previous, current in zip(chunks, chunks[1:]):
        assert previous[-OVERLAP:] == current[:OVERLAP]
    assert chunks[-1].endswith(text[-1])
    assert all(len(chunk) <= SIZE for chunk in chunks)


@pytest.mark.parametrize("overlap", [SIZE, SIZE + 50, -5])
def test_window_clamps_invalid_overlap_and_terminates(overlap: int) -> None:
    text = _sample(SIZE * 3)
    chunks = _window_chunks(text, SIZE, overlap)
    assert chunks
    assert chunks[-1].endswith(text[-1])
    assert len(chunks) <= len(text)


def test_window_rejects_non_positive_size() -> None:
    from app.rag.ingestion import split_fixed_window

    with pytest.raises(ValueError):
        split_fixed_window("abc", 0, 0)


def test_primary_splitter_handles_same_boundaries() -> None:
    body = f"""
    from app.core.config import Settings
    from app.rag.ingestion import chunk_text
    settings = Settings(environment="test", rag_chunk_size={SIZE}, rag_chunk_overlap={OVERLAP})
    print(json.dumps([len(chunk_text(settings, "a" * n)) for n in (0, {SIZE - 1}, {SIZE}, {SIZE * 4})]))
    """
    counts = _run_isolated(body, block_splitter=False)
    assert counts[0] == 0
    assert counts[1] == 1
    assert counts[2] == 1
    assert counts[3] >= 4
