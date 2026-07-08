"""Hestia-Konstanten."""
DOMAIN = "hestia"

# Config-Keys
CONF_LLAMA_URL = "llama_url"          # llama.cpp /completion-Basis (Test .111:8099 / Prod .112)
CONF_LOOP_DEPTH = "loop_depth"
CONF_EXPOSURE = "exposure"            # eigenes Set: entity_id -> {llm_name, aliases[], description, expose}
CONF_DENY = "deny"                    # Safety-Deny (Domains/Verben: lock, alarm_control_panel, ...)

DEFAULT_LOOP_DEPTH = 3
DEFAULT_DENY = ["lock", "alarm_control_panel"]

# Loop-erschöpft-Meldungen (Addon, KEIN LLM — LOOP_ARCH §7.3)
LOOP_EXHAUSTED_TEXTS = [
    "Ich dreh mich im Kreis — das kriege ich gerade nicht hin, sorry.",
    "Da komme ich nicht weiter. Versuch es bitte nochmal.",
]
