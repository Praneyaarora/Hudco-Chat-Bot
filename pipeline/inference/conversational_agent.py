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
    "mereko", "mujhe", "humko", "mera", "meri", "mere", "kahan", "kaha", "kahaa", "kidhar", "hai", "hain", "ha",
    "ka", "ki", "ke", "ko", "se", "mein", "mien", "me", "karna", "karni", "kare", "kar", "karo", "de", "do",
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

# Abusive / Profane Language Patterns (English & Hindi/Hinglish)
ABUSIVE_PATTERNS = [
    r"\b(fuck|fucking|fucker|motherfucker|shit|bullshit|bitch|bastard|asshole|moron|idiot|stupid|dick|crap|scoundrel)\b",
    r"\b(chutiya|chutiye|chutiyapa|choot|gandu|bhosdi|bhosdike|bhosadike|bhenchod|behenchod|mc|bc|madarchod|madarjaat)\b",
    r"\b(kutta|kutti|kamina|kamine|harami|haramzada|saala|saale|randi|lauda|loda|gaand|teri\s+maa\s+ki)\b",
]

# Spam & Repetitive Keysmash Patterns
SPAM_PATTERNS = [
    r"(.)\1{5,}",  # 6 or more identical consecutive characters (e.g. aaaaaa, !!!!!, ?????, ...... )
    r"\b(?:[bcdfghjklmnpqrstvwxyz]{7,})\b",  # 7+ consecutive consonants (keysmash e.g. asdfghjkl, zxcvbnm)
    r"\b([a-zA-Z]{1,4})(?:\1){4,}\b",  # Repetitive short sequence (e.g. asdasdasdasd)
]


def detect_spam(query: str, recent_turns: Optional[list] = None) -> Tuple[bool, Optional[str]]:
    """
    Identifies spam chats, rapid repetitions, keysmashes, or repeated query flooding.
    Returns (is_spam, polite_warning_message).
    """
    if not query:
        return False, None

    q_strip = query.strip()
    q_lower = q_strip.lower()

    # 1. Check for keysmash / nonsense character repetitions
    for pat in SPAM_PATTERNS:
        if re.search(pat, q_lower):
            msg = (
                "Kripya spam ya baar-baar anavashyak sandesh bhejne se bachein. Hum HUDCO sambandhit sahayata ke liye uplabdh hain—kripya apna sawal spasht roop se poochein."
                if detect_language(q_strip) == "hinglish"
                else "Please refrain from sending spam or repetitive messages. We are here to assist you with official HUDCO information—please ask a clear question regarding our services, reports, or departments."
            )
            return True, msg

    # 2. Check for repeated identical words (e.g. 'test test test test test test')
    words = q_lower.split()
    if len(words) >= 6 and len(set(words)) <= 2:
        msg = (
            "Kripya ek hi shabd baar-baar repeat na karein. Aap apna prashn spasht roop se poochein taaki hum aapki madad kar sakein."
            if detect_language(q_strip) == "hinglish"
            else "Please refrain from repeating words or spamming. Please ask a clear question so we can help you with HUDCO information."
        )
        return True, msg

    # 3. Check for consecutive identical query flooding across recent turns
    if recent_turns and len(recent_turns) >= 2:
        prev_user_queries = []
        for t in recent_turns:
            role = t.get("role", "") if isinstance(t, dict) else getattr(t, "role", "")
            content = t.get("content", "") if isinstance(t, dict) else getattr(t, "content", "")
            if role == "user" and content.strip():
                prev_user_queries.append(content.strip().lower())

        if len(prev_user_queries) >= 2 and all(pq == q_lower for pq in prev_user_queries[-2:]):
            msg = (
                "Aapne yeh sawal pehle bhi pucha hai. Kripya spamming se bachein aur naya ya spasht sawal poochein."
                if detect_language(q_strip) == "hinglish"
                else "You have submitted this exact query multiple times consecutively. Please refrain from spamming and let us know what specific assistance you need."
            )
            return True, msg

    return False, None


def detect_abusive_content(query: str) -> Tuple[bool, Optional[str]]:
    """
    Detects abusive, vulgar, profane, or insulting language (English & Hindi/Hinglish).
    Returns (is_abusive, polite_mannerly_response).
    """
    if not query:
        return False, None

    q_lower = query.lower()
    for idx, pat in enumerate(ABUSIVE_PATTERNS):
        if re.search(pat, q_lower):
            is_hindi = (idx >= 1) or (detect_language(query) == "hinglish")
            msg = (
                "Hum aapse vinamra aur shisht bhasha ka upayog karne ka anurodh karte hain. Kripya maryada banaye rakhein aur batayein ki HUDCO sambandhit kis jaankari mein hum aapki madad kar sakte hain."
                if is_hindi
                else "We kindly request you to maintain a respectful and courteous dialogue. Please keep the conversation polite, and let us know how we may assist you with HUDCO's services, schemes, or reports."
            )
            return True, msg

    return False, None


def detect_ambiguity_or_conflict(query: str, recent_turns: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """
    Detects when a multi-department role or entity is asked ambiguously without department context
    (e.g., 'who is ed?', 'who is the executive director?', 'who is gm?').
    Requests specific user clarification rather than guessing or getting confused.
    """
    q_lower = query.lower().strip()
    q_clean = re.sub(r"[^\w\s]", "", q_lower).strip()
    lang = detect_language(query)

    # 1. Ambiguous Executive Director (ED) without department specification
    # Note: If user asks "list of ed" or "all eds" or "ed finance", that is NOT ambiguous.
    is_asking_all_or_list = any(k in q_clean for k in ["list", "all", "soochi", "sabhi", "saare"])
    has_specific_dept = any(k in q_clean for k in ["finance", "hr", "it", "law", "project", "projects", "hsmi", "training", "audit", "compliance"])

    if not is_asking_all_or_list and not has_specific_dept:
        # Check if query specifically targets singular ED
        if re.search(r"^(who\s+is\s+(the\s+)?ed\??|who\s+is\s+(the\s+)?executive\s+director\??|ed\s+kaun\s+hai\??|executive\s+director\s+kaun\s+hai\??)$", q_clean) or q_clean in ["who is ed", "ed", "who is the ed", "who is executive director", "who is the executive director"]:
            if lang == "hinglish":
                clarification = (
                    "HUDCO mein vibhinn vibhagon ke liye alag-alag Executive Directors (ED) hain, jaise:\n\n"
                    "• **ED (Finance)**: Shri Daljeet Singh Khatri (Executive Director - Finance)\n"
                    "• **ED (Projects & Operations)**\n"
                    "• **ED (Law)**\n"
                    "• **ED (HSMI / Training)**: Ms. Varsha Punhani\n\n"
                    "Kripya spasht karein ki aap kis vibhag ke Executive Director ke baare mein jaanna chahte hain, ya sabhi EDs ki poori soochi chahte hain?"
                )
            else:
                clarification = (
                    "HUDCO has Executive Directors (EDs) leading multiple functional wings, such as:\n\n"
                    "• **Executive Director (Finance)**: Shri Daljeet Singh Khatri\n"
                    "• **Executive Director (Projects & Operations)**\n"
                    "• **Executive Director (Law)**\n"
                    "• **Executive Director (HSMI / Training)**: Ms. Varsha Punhani\n\n"
                    "Could you please clarify which department's Executive Director you are inquiring about, or would you like a full list of all Executive Directors?"
                )
            return {
                "answer": clarification,
                "intent": "clarification_conflict",
                "language": lang
            }

        # 2. Ambiguous General Manager (GM) without department specification
        if re.search(r"^(who\s+is\s+(the\s+)?gm\??|who\s+is\s+(the\s+)?general\s+manager\??|gm\s+kaun\s+hai\??)$", q_clean) or q_clean in ["who is gm", "gm", "who is the gm"]:
            if lang == "hinglish":
                clarification = (
                    "HUDCO ke alag-alag departments mein General Managers (GM) karyarat hain, jaise:\n\n"
                    "• **GM (HR / Human Resources)**: Mr. Prabhjot Singh Makkar & Dr. Anand Prakash Tiwari\n"
                    "• **GM (IT / Information Technology)**: Ms. Hemlata Sharma\n"
                    "• **GM (Internal Audit)**: Mr. Manoj Vasant Deodhar\n"
                    "• **GM (PMAY Wing)**: Mr. Naresh Kumar\n\n"
                    "Kripya batayein ki aap kis department ke General Manager ki jaankari chahte hain?"
                )
            else:
                clarification = (
                    "HUDCO has General Managers (GMs) heading different departments, including:\n\n"
                    "• **General Manager (HR / Human Resources)**: Mr. Prabhjot Singh Makkar & Dr. Anand Prakash Tiwari\n"
                    "• **General Manager (IT / Information Technology)**: Ms. Hemlata Sharma\n"
                    "• **General Manager (Internal Audit)**: Mr. Manoj Vasant Deodhar\n"
                    "• **General Manager (PMAY Wing)**: Mr. Naresh Kumar\n\n"
                    "Could you please specify which department's General Manager you are looking for?"
                )
            return {
                "answer": clarification,
                "intent": "clarification_conflict",
                "language": lang
            }

    return None


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

    # 0a. Spam & Repetitive Keysmash Filter
    is_spam, spam_msg = detect_spam(q, recent_turns=recent_turns)
    if is_spam:
        return {
            "answer": spam_msg,
            "intent": "spam_guardrail",
            "language": lang
        }

    # 0b. Abusive & Profane Language Filter
    is_abusive, abusive_msg = detect_abusive_content(q)
    if is_abusive:
        return {
            "answer": abusive_msg,
            "intent": "abusive_guardrail",
            "language": lang
        }

    # 0c. Context Pyramid Conflict & Multi-Department Ambiguity Filter
    ambiguity_res = detect_ambiguity_or_conflict(q, recent_turns=recent_turns)
    if ambiguity_res:
        return ambiguity_res

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
