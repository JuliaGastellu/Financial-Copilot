"""Controles sobre el corpus y las preguntas.

Trato los documentos como datos no confiables: un fragmento con instrucciones dirigidas al
sistema no se indexa ni se cita. Las respuestas educativas son extractivas, así que un texto
no puede cambiar el comportamiento; igual descarto esos fragmentos para no repetirlos.
"""
from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


_INJECTION_PATTERNS = [
    r"ignor(a|e|á|ar)\w*\s+(todas?\s+)?(las\s+|the\s+)?(instrucciones|instructions|reglas|rules)",
    r"(previous|prior|anteriores)\s+(instructions|instrucciones)",
    r"system\s*prompt|prompt\s+del\s+sistema|mensaje\s+del\s+sistema",
    r"(you\s+are\s+now|ahora\s+(sos|eres))\b",
    r"(responde|respond|answer|decile|decirle|tell)\w*\s+(al\s+usuario|the\s+user|a\s+la\s+persona)\s+que",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"(revela|reveal|muestra|show)\w*\s+(tus|your)\s+(instrucciones|instructions|claves|keys|secrets?)",
    r"(asistente|assistant|modelo|model|ia|ai)\s*:\s*(ignor|recomend|recommend)",
]
_INJECTION = [re.compile(p) for p in _INJECTION_PATTERNS]

# Pedidos de recomendación personalizada de instrumentos: fuera de alcance del producto.
_PERSONAL_ADVICE = [
    re.compile(p)
    for p in (
        r"\b(en\s+que|donde|que)\s+(invierto|deberia\s+invertir|me\s+conviene\s+invertir|compro|deberia\s+comprar)",
        r"\b(que|cual)\s+(accion|acciones|cripto|bono|bonos|fondo|cedear|cedears)\s+(compro|me\s+conviene|deberia)",
        r"\b(comprar|vender)\s+(acciones|bitcoin|cripto|dolares|cedears)\s+(ahora|hoy|ya)",
        r"\bshould\s+i\s+(buy|sell|invest)",
        r"\bwhat\s+(stock|crypto|fund)\s+should\s+i",
        r"\b(garantiza|garantizado|seguro\s+que\s+gano|rentabilidad\s+asegurada)",
    )
]


def injection_reason(text: str) -> str | None:
    folded = _fold(text)
    for pattern in _INJECTION:
        if pattern.search(folded):
            return "instruction_injection"
    return None


def out_of_scope_reason(query: str) -> str | None:
    folded = _fold(query)
    if any(p.search(folded) for p in _PERSONAL_ADVICE):
        return "personal_investment_advice"
    return None
