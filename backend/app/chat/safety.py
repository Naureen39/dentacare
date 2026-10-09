"""Checks that run before anything else, with no model and no database: text cleaning, personal
data masking, emergency wording, prompt injection wording and requests for medical advice."""

import re
import unicodedata

MAX_MESSAGE_CHARS = 500

_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_SPACES = re.compile(r"\s+")


def clean_text(raw: str) -> str:
    """Normalize, drop control and invisible direction characters, and collapse whitespace."""
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    return _SPACES.sub(" ", _CONTROL.sub("", text)).strip()


# --- personal data -----------------------------------------------------------------------------

_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_SSN = re.compile(r"(?<!\d)\d{3}[ -]\d{2}[ -]\d{4}(?!\d)")
_SSN_WORD = re.compile(
    r"\b(ssn|social security(?: number)?|tax id|passport(?: number)?|driver'?s? licen[cs]e)"
    r"\s*(?:is|number|no\.?|#|:)?\s*[:#]?\s*[A-Z0-9][A-Z0-9 -]{5,}",
    re.IGNORECASE,
)


def mask_pii(text: str) -> tuple[str, bool]:
    """Replace card numbers and government identifiers. Returns the text and whether it changed."""
    masked = _SSN_WORD.sub(lambda m: f"{m.group(1)} [removed]", text)
    masked = _SSN.sub("[ID removed]", masked)
    masked = _CARD.sub("[card number removed]", masked)
    return masked, masked != text


# --- emergencies -------------------------------------------------------------------------------

_EMERGENCY = [
    r"\b(can'?t|cannot|can not|unable to|struggling to|hard to|difficult to|difficulty|trouble|"
    r"problems?)\b.{0,20}\bbreath",
    r"\b(short of breath|gasping|choking|throat (is )?closing|airway)\b",
    r"\bsw(?:ell|oll)\w*\b.{0,40}\b(face|eye|eyes|throat|neck|jaw|cheek|spreading|rapidly|fast)\b",
    r"\b(face|eye|eyes|throat|neck|jaw|cheek)\b.{0,30}\bsw(?:ell|oll)\w*\b",
    r"\b(severe|massive|spreading|rapid(ly)?)\b.{0,20}\bsw(?:ell|oll)\w*\b",
    r"\b(uncontrolled|won'?t stop|will not stop|not stopping|can'?t stop|heavy|heavily|"
    r"profuse|excessive)\b.{0,25}\bbleed",
    r"\bbleed\w*\b.{0,30}\b(won'?t stop|will not stop|not stopping|can'?t stop|a lot|badly|"
    r"heavily|uncontrolled|non[- ]?stop)\b",
    r"\b(facial|face|jaw|mouth) (trauma|injury|fracture)\b",
    r"\b(broken|fractured|dislocated|smashed) (jaw|face|cheekbone)\b",
    r"\bjaw\b.{0,15}\b(broken|fractured|dislocated)\b",
    r"\b(hit|punched|kicked|struck) (in|on) the (face|jaw|mouth)\b",
    r"\b(car|bike|bicycle|sports?) (accident|crash)\b.{0,40}\b(face|mouth|jaw|teeth|tooth)\b",
    r"\b(fainting|fainted|passed out|unconscious|chest pain)\b",
]
EMERGENCY_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _EMERGENCY]


def is_emergency(text: str) -> bool:
    return any(p.search(text) for p in EMERGENCY_PATTERNS)


# --- prompt injection --------------------------------------------------------------------------

_INJECTION = [
    r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}\b(previous|prior|above|earlier|all|any|"
    r"your|these|those)\b.{0,30}\b(instructions?|rules?|prompts?|guidelines?|directions?|"
    r"restrictions?)\b",
    r"\b(reveal|show|print|repeat|display|leak|tell me|give me|what('?s| is| are))\b.{0,30}"
    r"\b(system|hidden|initial|original|secret)\b.{0,12}\b(prompt|instructions?|message|rules?)\b",
    r"\byour (system|initial|original|hidden|secret) (prompt|instructions)\b|\byour prompt\b",
    r"\b(you are|you'?re) (now|no longer)\b",
    r"\bfrom now on\b.{0,40}\b(you|act|respond|answer|ignore)\b",
    r"\b(pretend|act|behave|roleplay|role-play)\b.{0,20}\b(to be|as|like)\b.{0,20}"
    r"\b(a|an|the)?\s*(different|new|unrestricted|evil|hacker|developer|admin|dan|jailbroken)\b",
    r"\b(developer|debug|admin|sudo|god|jailbreak|dan)\s+mode\b",
    r"\bjailbreak\b",
    r"</?\s*(system|assistant|context|question|instructions?)\s*>",
    r"\[\s*(system|inst)\s*\]|<\|im_(start|end)\|>",
    r"\b(base64|rot13)\b.{0,20}\b(decode|decoded)\b",
]
INJECTION_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION]


def looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in INJECTION_PATTERNS)


_TAG = re.compile(r"</?\s*(system|assistant|user|context|question|instructions?)\s*/?>", re.I)


def neutralize_delimiters(text: str) -> str:
    """Remove anything that could close or imitate the delimiters around user text."""
    return _TAG.sub(" ", text).replace("<", "(").replace(">", ")")


# --- medical advice ----------------------------------------------------------------------------

_MEDICAL_ADVICE = [
    r"\bshould i (take|use|give|try|put|apply|swallow)\b",
    r"\b(what|which) (medicine|medication|drug|antibiotic|painkiller|pills?|dose|dosage)\b",
    r"\b(how (much|many)) .{0,20}\b(ibuprofen|tylenol|acetaminophen|paracetamol|aspirin|"
    r"amoxicillin|antibiotics?|painkillers?|mg)\b",
    r"\b(ibuprofen|tylenol|acetaminophen|paracetamol|aspirin|amoxicillin|penicillin|codeine|"
    r"opioids?|oxycodone|clindamycin|antibiotics?)\b",
    r"\bdo i have\b.{0,30}\b(cavity|cavities|infection|abscess|gum disease|cancer|decay|"
    r"gingivitis|periodontitis)\b",
    r"\b(is|are) (this|these|my)\b.{0,30}\b(infected|an infection|cancer|cancerous|serious|"
    r"decayed|abscess)\b",
    r"\b(diagnose|diagnosis|what('?s| is) wrong with my)\b",
    r"\bwhy (does|is|do) my (tooth|teeth|gum|gums|jaw)\b.{0,30}\b(hurt|ache|bleed|swollen|"
    r"sensitive|loose)\b",
    r"\bmy (tooth|teeth|gum|gums|jaw)\b.{0,25}\b(hurts?|aching|aches|throbbing|bleeding)\b",
    r"\bcan i (skip|stop|delay|ignore)\b.{0,30}\b(treatment|root canal|antibiotics?|medication)\b",
]
MEDICAL_ADVICE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _MEDICAL_ADVICE]


def asks_for_medical_advice(text: str) -> bool:
    return any(p.search(text) for p in MEDICAL_ADVICE_PATTERNS)


# --- exiting a flow -----------------------------------------------------------------------------

_EXIT = re.compile(
    r"^\s*(cancel|stop|exit|quit|abort|never ?mind|nvm|forget it|no thanks?|leave it|"
    r"cancel (this|that|it|booking|the booking|everything))\s*[.!]*\s*$",
    re.IGNORECASE,
)
_RESTART = re.compile(r"^\s*(start over|restart|begin again|start again|reset)\s*[.!]*\s*$", re.I)


def wants_to_exit(text: str) -> bool:
    return bool(_EXIT.match(text))


def wants_to_restart(text: str) -> bool:
    return bool(_RESTART.match(text))
