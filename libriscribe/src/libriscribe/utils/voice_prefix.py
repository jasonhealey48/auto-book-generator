"""
Tiny helper that builds the audience + author voice lead-in
used by every LibriScribe agent.

Exports one function: voice_lead(ProjectKnowledgeBase) -> str
"""

from libriscribe.voice import voice_directive


def voice_lead(kb, prompt: str = "") -> str:
    """Return a capped audience/tone/author block ready to prepend to any prompt.

    If ``prompt`` is provided, the block is prepended to it so callers can do:
        prompt = voice_lead(kb, prompt)
    """
    if not kb:
        return prompt
    block = voice_directive(
        audience=getattr(kb, "target_audience", "") or "",
        tone=getattr(kb, "tone", "") or "",
        author_name=getattr(kb, "author_voice", "") or "",
        author_style=getattr(kb, "author_style", "") or "",
        author_donts=getattr(kb, "author_donts", "") or "",
        author_exemplar=getattr(kb, "author_exemplar", "") or "",
    )
    if not prompt:
        return block
    if not block:
        return prompt
    return f"{block}\n\n{prompt}"