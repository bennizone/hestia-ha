"""Limit-Mapping (WRITE-Seite, SERVE-only) — Arduino `map()`.

Das LLM lebt im **virtuellen 0–100-Raum** und kennt die echte Range einer Entität NICHT.
Der Admin konfiguriert pro Entität eine reale `[min,max]`-Prozent-Range (Panel). Der Executor
mapped den virtuellen Steuerwert auf die echte Range (nur beim `hass.services.async_call`) und
echot im Result weiter den **angeforderten (virtuellen)** Wert zurück.

Damit bleibt der Tool-Result byte-gleich zum Training: der Generator kennt kein Mapping (das
Modell soll die Range nie sehen), das Result trägt weiter den virtuellen Wert → **train==serve**
auf dem Tool-JSON bleibt intakt (Audit-Prinzip 2026-07-09). Mapping fasst ausschließlich den an
HA gesendeten Steuerwert an.

Rein serve, HA-frei, dep-frei (nur stdlib) — testbar wie `hestia_cap.result`.
Identität bei `min=0, max=100` (Default) ⇒ **kein Verhalten geändert**.

Beispiel (Roadmap): Range 0–70. Modell sagt 100 → Gerät 70 %. Modell sagt 50 → Gerät 35 %.
Allgemein: `real = min + virtuell/100 · (max − min)` (gerundet, geklemmt).
"""
from __future__ import annotations

# Prozent-Attribute, die im 0–100-Raum leben und gemappt werden (set_state/adjust).
# Reale-Einheit-Attribute (temperature °C, color_temp K) werden NICHT gemappt.
PCT_ATTRS = frozenset({"brightness", "volume", "position", "fan_speed"})


def norm(lo, hi) -> tuple | None:
    """`(lo, hi)` → normalisierte Range-Tuple **oder None** (Identität/ungültig).

    None heißt „kein Mapping" (Default 0–100, Unfug, oder degeneriert lo≥hi). Der Executor
    prüft nur auf Truthiness → kein Mapping-Zweig läuft bei None."""
    try:
        lo, hi = int(lo), int(hi)
    except (TypeError, ValueError):
        return None
    lo = max(0, min(100, lo))
    hi = max(0, min(100, hi))
    if lo < hi and (lo, hi) != (0, 100):
        return (lo, hi)
    return None


def apply(virtual, limit) -> int:
    """Virtuellen 0–100-Wert auf die echte Range mappen. `limit` = norm()-Tuple oder None.

    None → unverändert (Identität). Sonst linear auf `[lo, hi]`, gerundet + geklemmt."""
    if not limit:
        return int(round(virtual))
    lo, hi = limit
    v = max(0, min(100, virtual))
    return int(round(lo + v / 100 * (hi - lo)))


def to_virtual(real, limit) -> int:
    """Umkehrung: echten Wert aus der Range zurück in den virtuellen 0–100-Raum.

    Für das adjust-Echo (Vorher/Nachher lebt virtuell). None → unverändert."""
    if not limit or real is None:
        return real
    lo, hi = limit
    if hi <= lo:
        return 0
    v = (real - lo) / (hi - lo) * 100
    return int(round(max(0, min(100, v))))


def scale_step(virtual_step, limit) -> int:
    """Relativen (vorzeichenbehafteten) virtuellen pct-Schritt auf die Range skalieren.

    Ein virtueller Schritt von 25 über eine Range 0–70 bewegt real nur 25·70/100 ≈ 18 %.
    None → unverändert."""
    if not limit:
        return int(round(virtual_step))
    lo, hi = limit
    return int(round(virtual_step * (hi - lo) / 100))
