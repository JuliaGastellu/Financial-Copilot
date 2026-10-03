"""Evaluación determinística sobre los 60 casos versionados (proveedor simulado).

Comprueba los criterios de salida de la etapa. No mide la calidad de un modelo real: para
eso existe `python -m evals.run_eval --mode real`, que es optativo y no corre en CI.
"""
from __future__ import annotations

import pytest

from evals.runner import run


@pytest.fixture(scope="module")
def report() -> dict:
    return run("scripted")


def test_sixty_versioned_cases(report):
    assert report["version"] == "cases-v1"
    assert report["metrics"]["cases"] == 60


def test_zero_contradictions_in_critical_cases(report):
    m = report["metrics"]
    assert m["critical_cases"] >= 15
    assert m["critical_contradictions_delivered"] == 0
    assert m["contradictions_delivered"] == 0


def test_claims_are_supported(report):
    assert report["metrics"]["claim_support_rate"] >= 0.95
    assert report["metrics"]["injected_claims"] == 0


def test_abstention_in_every_designed_case(report):
    m = report["metrics"]
    assert m["abstention_rate_designed"] == 1.0
    assert m["designed_abstentions_correct"] == m["designed_abstentions"]


def test_answers_are_not_replaced_by_blanket_abstention(report):
    m = report["metrics"]
    # Abstenerse siempre aprobaría los criterios anteriores; exijo responder los casos respondibles.
    assert m["answerable_answered_with_expected_citation"] >= 0.8 * m["answerable_cases"]


def test_validation_catches_every_scripted_error(report):
    m = report["metrics"]
    assert m["expected_source_matches"] == 30
    assert report["failures"] == []
