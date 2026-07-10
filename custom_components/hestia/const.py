"""Hestia-Konstanten."""
DOMAIN = "hestia"

# Config-Keys
CONF_LLAMA_URL = "llama_url"          # llama.cpp /completion-Basis (Test .111:8099 / Prod .112)
CONF_LOOP_DEPTH = "loop_depth"
CONF_EXPOSURE = "exposure"            # eigenes Set: entity_id -> {llm_name, aliases[], description, expose}
CONF_DENY = "deny"                    # Safety-Deny (Domains/Verben: lock, alarm_control_panel, ...)
CONF_UNSAFE_MODE = "unsafe_mode"      # Config-Toggle: an → Executor erlaubt Schloss/Alarm-Steuerung
                                      #   (nimmt lock/alarm aus deny). Aus (default) → safeguard blockt (err_unsafe).

DEFAULT_LOOP_DEPTH = 3
DEFAULT_DENY = ["lock", "alarm_control_panel"]
DEFAULT_UNSAFE_MODE = False
_SAFETY_DOMAINS = ("lock", "alarm_control_panel")


def effective_deny(deny: list | None, unsafe_mode: bool) -> list:
    """unsafe_mode an → Safety-Domains aus dem Deny nehmen (Executor erlaubt Steuerung); aus → deny wie ist."""
    d = list(deny if deny is not None else DEFAULT_DENY)
    if unsafe_mode:
        d = [x for x in d if x not in _SAFETY_DOMAINS]
    return d

# Loop-erschöpft-Meldungen (Addon, KEIN LLM — LOOP_ARCH §7.3)
LOOP_EXHAUSTED_TEXTS = [
    "Ich dreh mich im Kreis — das kriege ich gerade nicht hin, sorry.",
    "Da komme ich nicht weiter. Versuch es bitte nochmal.",
]
