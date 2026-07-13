"""
Audience + author voice directive construction.

Single source of truth for all agents that want to inject the
audience/author guidance into their prompts. Keeps the directive
compact and bounded (~180 words) so token budget stays predictable.
"""

from typing import List


AUDIENCE_GUIDANCE = {
    "Children": (
        "Audience: Children (ages 5–9). "
        "Warm, simple, rhythmic voice. Very short sentences (4–8 words). "
        "Concrete nouns and active verbs. One tiny scene per beat. "
        "Repetition and rhyme welcome. End on a small hook."
    ),
    "Middle Grade": (
        "Audience: Middle Grade (ages 8–12). "
        "Clear, engaging voice. Short-to-medium sentences. "
        "Concrete action + mild emotion. Mild peril OK; warm resolution."
    ),
    "Young Adult": (
        "Audience: Young Adult (ages 13–18). "
        "Emotionally rich, identity-focused voice. "
        "Medium sentences, some subtext. Edgy but not explicit. "
        "Cliffhangers welcome."
    ),
    "Adult": (
        "Audience: Adult. "
        "Layered, nuanced voice. Medium-to-long sentences. "
        "Subtext, ambiguity, and complex feelings allowed. "
        "No hand-holding; reader earns the payoff."
    ),
    "All Ages": (
        "Audience: All Ages (7 to adult). "
        "Simple enough for a 7-year-old, satisfying for adults. "
        "Warm, clear, no graphic content. Short-to-medium sentences."
    ),
}

TONE_DEFAULTS = {
    "Children": "Warm, simple, playful",
    "Middle Grade": "Engaging, accessible",
    "Young Adult": "Emotional, edgy",
    "Adult": "Nuanced, restrained",
    "All Ages": "Warm, clear, universal",
}


def derive_tone(audience: str) -> str:
    return TONE_DEFAULTS.get(audience, "Informative")


def voice_directive(
    *,
    audience: str = "",
    tone: str = "",
    author_name: str = "",
    author_style: str = "",
    author_donts: str = "",
    author_exemplar: str = "",
) -> str:
    """
    Return a concise voice directive block (~180 words max) or ''.
    All fields are optional; the block is assembled from whatever is provided.
    """
    parts: List[str] = []

    aud = audience.strip() if audience else ""
    if aud and aud in AUDIENCE_GUIDANCE:
        parts.append(AUDIENCE_GUIDANCE[aud])
    elif aud:
        parts.append(f"Audience: {aud}.")

    if tone:
        parts.append(f"Tone: {tone}.")

    if author_name:
        parts.append(f"Author voice: {author_name}.")
    if author_style:
        parts.append(f"Style: {author_style}")
    if author_donts:
        parts.append(f"Avoid: {author_donts}")
    if author_exemplar:
        parts.append(f"Exemplar: {author_exemplar}")

    # When both an audience and an author are set, explicitly bind the author's
    # voice to the age range: keep the author's stylistic identity, but tune
    # vocabulary + sentence structure to the chosen audience (ages/length above).
    if author_name and aud:
        parts.append(
            "Combine the author voice above with the audience above: preserve this "
            "author's stylistic identity (rhythm, imagery, attitude, wit), but adapt "
            "VOCABULARY and SENTENCE STRUCTURE to match the age range and sentence-"
            "length guidance stated for that audience. The audience's vocabulary and "
            "sentence-length constraints take priority over the author's usual complexity."
        )

    if not parts:
        return ""

    block = "  ".join(parts).strip()
    # hard cap so we never blow token budget
    if len(block) > 800:
        block = block[:800].rstrip() + " …"
    return f"[Voice Directive]\n{block}"