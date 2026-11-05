"""
HUDCO Bot — Conversational Intelligence, Emotion Detection, and Intent Router.
File: pipeline/inference/conversational_agent.py

Provides:
1. Robust semantic intent understanding for greetings, capability inquiries, complaints, and ambiguous queries.
2. Emotional context & sentiment detection (frustration, grievance, urgency, confusion, appreciation).
3. Incomplete / ambiguous query handling with gentle clarifications.
4. Seamless language identification (English vs. Hindi/Hinglish).
"""

from __future__ import annotations

import re
from typing import Optional, Dict, Any, Tuple


# Words strongly indicating Hindi / Hinglish phrasing
HINGLISH_INDICATORS = {
    "mereko", "mujhe", "humko", "kahan", "kaha", "kahaa", "kidhar", "hai", "hain", "ha",
    "ka", "ki", "ke", "ko", "se", "mein", "mien", "me", "karna", "karni", "kare",
    "karen", "kaise", "kaisa", "kya", "bhi", "batao", "bataiye", "chahiye", "jana",
    "shikayat", "shikaayat", "paise", "naukri", "kitna", "kitni", "shuru", "kab", "kyun",
    "kyu", "namaste", "namaskar", "namashkar", "pranam", "pranaam", "khammaghani",
    "vanakkam", "adaab", "ram", "radhe", "dhanyawad", "shukriya", "pehle", "abhi",
    "tak", "kuch", "nahi", "hua", "inse", "baat", "sakta", "sakti", "ye", "log", "kam",
    "kaam", "rahe", "raha", "rahi", "thik", "theek", "badhiya", "haal", "hal", "aana",
    "milna", "chahta", "chahti", "gussa", "naraz", "dhokha", "bekaar", "ghatiya"
}

# Greeting word sets & regex phrases
GREETING_TOKENS = {
    "hi", "hello", "hey", "heya", "hiya", "namaste", "namaskar", "namashkar",
    "pranam", "pranaam", "khammaghani", "vanakkam", "sat sri akal", "sasrikaal",
    "kem cho", "adaab", "ram ram", "radhe radhe"
}

GREETING_PHRASES = [
    r"^(hi|hello|hey|heya|hiya)\b",
    r"^(namaste|namaskar|namashkar|pranam|pranaam|khammaghani|vanakkam|adaab|kem\s+cho)\b",
    r"^good\s+(morning|afternoon|evening|day)\b",
    r"^(how\s+are\s+you|hows\s+it\s+going|what('?s|\s+is)\s+up)\b",
    r"^(kaise\s+ho|kaisa\s+hai|kya\s+haal\s+hai|kya\s+haal|sab\s+badhiya|sab\s+theek|sab\s+thik)\b",
    r"^(namashkar|namaskar|namaste|pranaam|pranam|hello|hi)[,\s]+(ek\s+baat\s+puchni\s+thi|ek\s+sawal\s+tha|i\s+have\s+a\s+question)\b",
    r"^(ek\s+baat\s+puchni\s+thi|ek\s+sawal\s+tha|can\s+i\s+ask\s+a\s+question)\b",
]

# Domain substantive nouns that indicate this is a factual RAG query, even if a greeting is present
SUBSTANTIVE_NOUNS = {
    "profit", "loan", "sanction", "sanctions", "head office", "address", "net worth",
    "share", "shares", "dividend", "recruitment", "vacancy", "careers", "director",
    "cmd", "result", "results", "balance sheet", "pat", "crore", "lakh", "quarter",
    "annual report", "fy", "financial", "disbursement", "disbursements", "scheme",
    "uiwin", "subsidy", "interest", "pmay", "smart city"
}

# Regex patterns for Gratitude & Parting
GRATITUDE_PATTERNS = [
    r"\b(thank\s*you|thanks|thx|dhanyawad|shukriya|bahut\s+dhanyawad)\b",
    r"^(bye|goodbye|see\s+you|alvida|tata)\b",
]

# Patterns detecting complaints, dissatisfaction, or service breakdown
COMPLAINT_SIGNALS = [
    r"\b(complaint|complain|grievance|shikayat|shikaayat)\b",
    r"\b(kaam\s+(hi\s+)?nahi\s+kar\s+rahe|koi\s+kaam\s+nahi|sun\s+nahi\s+rahe|koi\s+sunta\s+nahi|koi\s+sun\s+nahi\s+raha)\b",
    r"\b(kisi\s+kaam\s+ka\s+nahi|bekaar\s+service|worst\s+service|bad\s+service|ghatiya\s+service|ghatiya)\b",
    r"\b(fraud|scam|cheated|cheat|dhokha|harassment|loot\s+rahe)\b",
    r"\b(abhi\s+tak\s+kuch\s+nahi\s+hua|pehle\s+bhi\s+complaint|koi\s+response\s+nahi|no\s+response|stuck|delay|delayed)\b",
    r"\b(pareshan\s+kar\s+rakha|pareshan\s+ho\s+gaya|unhappy|dissatisfied|disappointed|gussa|naraz)\b",
    r"\b(consumer\s+forum|consumer\s+court|ombudsman|action\s+lo|action\s+lijiye|escalat(?:e|ion))\b",
    r"\b(helpline|customer\s+care).*(complaint|grievance|issue|problem|against)\b",
    r"\b(complaint|grievance|issue|problem).*(helpline|contact|call|number)\b",
]

# Ambiguous / Incomplete Visit Queries
AMBIGUOUS_VISIT_PATTERNS = [
    r"^(mereko|mujhe|humko|i\s+want\s+to)\s+(hudco\s+)?(jana|aana|visit|milna)\s+(hai|ha|chahta|chahti)\b",
    r"^(i\s+want\s+to\s+visit\s+hudco|how\s+to\s+visit\s+hudco)\b",
    r"^(hudco\s+jana\s+hai|hudco\s+visit\s+karna\s+hai)\b",
]


def detect_language(text: str) -> str:
    """
    Detects whether the user is communicating in English or Hindi/Hinglish.
    Returns: 'hinglish' or 'english'
    """
    if not text:
        return "english"

    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = set(cleaned.split())

    # Count Hinglish indicator tokens
    hinglish_matches = tokens.intersection(HINGLISH_INDICATORS)
    if len(hinglish_matches) >= 1 or (len(tokens) > 0 and len(hinglish_matches) / len(tokens) >= 0.15):
        return "hinglish"

    # Also detect Devanagari script characters
    if re.search(r"[\u0900-\u097F]", text):
        return "hinglish"

    return "english"


def detect_emotional_tone(text: str) -> Dict[str, Any]:
    """
    Analyzes emotional context, urgency, and grievance signals.
    Returns: {
        'is_complaint': bool,
        'tone': 'frustrated' | 'urgent' | 'gratitude' | 'neutral',
        'requires_empathy': bool
    }
    """
    q_lower = text.lower()

    is_complaint = any(re.search(pat, q_lower) for pat in COMPLAINT_SIGNALS)
    is_gratitude = any(re.search(pat, q_lower) for pat in GRATITUDE_PATTERNS)

    if is_complaint:
        return {
            "is_complaint": True,
            "tone": "frustrated",
            "requires_empathy": True
        }
    elif is_gratitude:
        return {
            "is_complaint": False,
            "tone": "gratitude",
            "requires_empathy": False
        }

    return {
        "is_complaint": False,
        "tone": "neutral",
        "requires_empathy": False
    }


def check_conversational_intent(query: str, recent_turns: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    Evaluates greetings, capability checks, gratitude, complaints, and ambiguous visit queries.
    Returns structured response dict if intent can be handled conversationally, or None for RAG.
    """
    q = query.strip()
    if not q:
        return {
            "answer": "Hello! Welcome to HUDCO Bot. How can I help you today?",
            "intent": "empty_prompt",
            "language": "english"
        }

    lang = detect_language(q)
    q_lower = q.lower().strip()
    q_clean = re.sub(r"[^\w\s]", " ", q_lower)
    tokens = set(q_clean.split())

    # Check for presence of substantive enterprise/factual topics
    has_substantive = any(noun in q_clean for noun in SUBSTANTIVE_NOUNS)

    # 1. Natural Concise Greeting (English & Hinglish)
    # Check if phrase matches greeting syntax or pure greeting tokens without factual domain queries
    is_greeting_match = (
        any(re.search(pat, q_lower) for pat in GREETING_PHRASES)
        or any(t in GREETING_TOKENS for t in tokens)
    )

    if is_greeting_match and not has_substantive and len(tokens) <= 8:
        if lang == "hinglish":
            greeting_text = "Namaste! HUDCO Bot mein aapka swagat hai. Aaj main aapki kya madad kar sakta hoon?"
        else:
            greeting_text = "Hello! Welcome to HUDCO Bot. How can I help you today?"
        return {
            "answer": greeting_text,
            "intent": "greeting",
            "language": lang
        }

    # 2. Complaints & Grievance Routing (Direct empathetic channel help)
    emotion = detect_emotional_tone(q)
    if emotion["is_complaint"]:
        is_asking_how_to_complain = any(re.search(p, q_lower) for p in [
            r"helpline", r"contact", r"kahan\s+contact", r"kaise\s+kar", r"kise\s+bol", r"number",
            r"how\s+to\s+file", r"where\s+to\s+call", r"who\s+to\s+contact", r"whom\s+to\s+reach",
            r"kaam\s+(hi\s+)?nahi\s+kar\s+rahe", r"pehle\s+bhi\s+complaint", r"abhi\s+tak\s+kuch\s+nahi"
        ])
        if is_asking_how_to_complain or len(tokens) <= 15:
            if lang == "hinglish":
                ans = (
                    "Main samajh sakta hoon ki aapko samasya ka samna karna pada hai aur iske liye khed hai. "
                    "Aap apni shikayat darj karne ke liye HUDCO ke verified Grievance Redressal channels se sampark kar sakte hain:\n\n"
                    "• **HUDCO Grievance Redressal Officer**: HUDCO Bhawan, Core 7-A, India Habitat Centre, Lodhi Road, New Delhi – 110003\n"
                    "• **Telephone**: 011-24649610 to 21 / 011-24616732\n"
                    "• **Email**: hudco@hudco.org\n"
                    "• **Online Portal**: Bharat Sarkar ke CPGRAMS portal https://pgportal.gov.in par bhi aap online shikayat darj kar sakte hain.\n\n"
                    "Agar aapka mudda kisi specific regional branch ya loan account se juda hai, toh kripya sheher ya reference number batayein taaki main direct sambandhit branch ki jaankari de sakoon."
                )
            else:
                ans = (
                    "I understand your frustration regarding this matter, and I apologize for the inconvenience caused. "
                    "To lodge a formal grievance with HUDCO, please reach out through the verified grievance channels:\n\n"
                    "• **Grievance Redressal Officer**: HUDCO Bhawan, Core 7-A, India Habitat Centre, Lodhi Road, New Delhi – 110003\n"
                    "• **Contact Numbers**: 011-24649610 to 21 / 011-24616732\n"
                    "• **Email**: hudco@hudco.org\n"
                    "• **Online Portal (CPGRAMS)**: You can also file a complaint online on the Government portal at https://pgportal.gov.in.\n\n"
                    "If your issue relates to a specific regional office or existing loan account, please provide the city or reference details so I can guide you further."
                )
            return {
                "answer": ans,
                "intent": "grievance_help",
                "language": lang
            }

    # 3. Gratitude or Parting
    for pattern in GRATITUDE_PATTERNS:
        if re.search(pattern, q_lower):
            is_bye = any(w in q_clean for w in ["bye", "goodbye", "alvida", "tata", "see you"])
            if is_bye:
                parting_text = (
                    "Alvida! Aapka din shubh ho. HUDCO se judi kisi bhi jaankari ke liye aap dobara jud sakte hain."
                    if lang == "hinglish"
                    else "Goodbye! Have a great day ahead. Feel free to return whenever you need HUDCO information."
                )
                return {
                    "answer": parting_text,
                    "intent": "parting",
                    "language": lang
                }
            gratitude_text = (
                "Aapka swagat hai! Agar aapko HUDCO ke baare mein koi aur jaankari chahiye toh zaroor batayein."
                if lang == "hinglish"
                else "You're very welcome! Please let me know if you need any more details about HUDCO."
            )
            return {
                "answer": gratitude_text,
                "intent": "gratitude",
                "language": lang
            }

    # 4. Ambiguous / Incomplete Visit Intent (e.g. "mereko hudco jana hai")
    for pattern in AMBIGUOUS_VISIT_PATTERNS:
        if re.search(pattern, q_lower):
            if lang == "hinglish":
                clarification_text = (
                    "Zaroor! Kya aap HUDCO ke New Delhi sthit Registered Head Office (India Habitat Centre) "
                    "jaana chahte hain, ya kisi specific state/sheher ke Regional Office ka address dhoondh rahe hain? "
                    "Kripya apna sheher ya rajya batayein."
                )
            else:
                clarification_text = (
                    "Sure! Are you looking to visit HUDCO's Registered Head Office in New Delhi (India Habitat Centre), "
                    "or are you looking for a specific Regional Office? Please specify your city or state."
                )
            return {
                "answer": clarification_text,
                "intent": "clarification_location",
                "language": lang
            }

    return None
