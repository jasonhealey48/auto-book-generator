"""
Auto Book Generator - Professional Edition
===========================================

JSON-first generation: full book JSON is generated before any page text.
Every page written with COMPLETE book JSON as context.
Multi-agent backend via LibriScribe (concept, outline, characters, worldbuilding,
chapter writing, content review, editor, style editing).
"""

import sys
import os
import json
import time
import re
import hashlib
import base64
import urllib.parse
import traceback
import requests
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton, QSpinBox,
    QProgressBar, QMessageBox, QComboBox, QCheckBox, QGroupBox, QTabWidget,
    QSplitter, QScrollArea, QFrame, QFormLayout, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QTextBrowser, QMenu, QAction, QFileDialog, QSlider, QPlainTextEdit,
    QInputDialog, QTableWidget, QTableWidgetItem)
from PyQt5.QtGui import QPixmap, QFont, QIcon, QColor, QTextCursor, QImage, QDesktopServices, QCursor
from PyQt5.QtCore import (QThread, pyqtSignal, Qt, QTimer, QSize, QPoint, QRunnable,
    QThreadPool, pyqtSlot, QObject, QUrl)

from providers import (Provider, ProviderResult, ProviderConfig, Router,
    PollinationsProvider, make_nvidia, make_openrouter, make_huggingface, make_google, make_groq)
from image_providers import (ImageProvider, ImageResult, ImageProviderConfig,
    ImageRouter, make_image_provider, PollinationsImageProvider,
    StableHordeImageProvider, HFSpaceImageProvider, GoogleNanoBananaProvider,
    NANO_BANANA_MODELS)
from author_voices import (AuthorVoice, AUTHORS_BY_GENRE, authors_for_genre,
    get_author_voice, research_author_voice, DEFAULT_PROSE)
from models_catalog import (ModelInfo, fetch_for)
from PIL import Image, ImageDraw, ImageFont
from book_engine import BookEngine, PROVIDER_DISPLAY_NAMES

CONFIG_FILE = "book_config.json"
PROJECT_FILE = "book_project.json"

AUDIENCES = ["Children", "Middle Grade", "Young Adult", "Adult", "All Ages"]
GENRES = ["Fantasy", "Sci-Fi", "Horror", "Mystery", "Romance",
          "Adventure", "Comedy", "Drama", "Thriller", "Literary", "Graphic Novel"]


def _is_graphic(genre) -> bool:
    """True when 'Graphic Novel' is among the (possibly comma-joined) genres."""
    return bool(genre) and any(
        g.strip().lower() == "graphic novel" for g in str(genre).split(",")
    )


def _genre_guidance(genre_str) -> str:
    """Join GENRE_GUIDANCE for every genre in a (possibly comma-joined) string."""
    parts = []
    for g in str(genre_str or "").split(","):
        g = g.strip()
        if g:
            v = GENRE_GUIDANCE.get(g)
            if v:
                parts.append(v)
    return " ".join(parts)

AUDIENCE_GUIDANCE = {
    "Children": ("Picture-book ages 5-9. Warm, conversational voice. Short sentences (6-10 words). Concrete nouns/verbs. ONE scene per page. End on a small hook."),
    "Middle Grade": ("Ages 8-12. Richer vocabulary. Mild peril OK. Coming-of-age themes. Warm resolution."),
    "Young Adult": ("Ages 13-18. Deep emotions, identity, moral ambiguity. Edgy but not explicit. Cliffhangers OK."),
    "Adult": ("Mature readers. Complex prose, layered themes. Allows ambiguous endings."),
    "All Ages": ("Universal: simple for 7yo, satisfying for adults. Warm, clear, no graphic content."),
}

GENRE_GUIDANCE = {
    "Horror": "Dread/atmosphere without gore. Sound, chill, shadow. Scary thing is lonely/kind.",
    "Fantasy": "Coherent magic or whimsical logic. Mythic archetypes. Wonder and awe.",
    "Sci-Fi": "Clever what-if. Tech with tradeoffs. Sense of vastness.",
    "Mystery": "Fair clues. One puzzle. Resolution satisfies all clues.",
    "Romance": "Emotional beats. Small gestures. Earn the relationship.",
    "Adventure": "Escalating stakes, puzzles, narrow escapes. Momentum.",
    "Comedy": "Voice, wordplay, callbacks. Warmth under humor.",
    "Drama": "Restraint. Internal conflict. Show don't tell.",
    "Thriller": "Pace and stakes. Short sentences in tension.",
    "Literary": "Subtext, restraint, observed detail. Ambiguity OK.",
    "Graphic Novel": "Visual-first storytelling. Panels over prose. Snappy dialogue, "
                      "minimal narration; let the art carry the scene. Strong composition, "
                      "clear readable shapes, room for speech bubbles and captions.",
}

# ---- Hover help: descriptions keyed by widget objectName ----
_HOVER_DESCRIPTIONS = {
    "theme_edit": ("Theme", "The emotional idea your book explores (e.g. friendship, courage). Shapes plot and tone."),
    "setting_edit": ("Setting", "Where/when the story happens (e.g. a magical forest kingdom). Grounds the world."),
    "genre_list": ("Genres", "Pick one or more (e.g. Graphic Novel + Fantasy). Graphic Novel is a visual format layered on any story genre."),
    "audience_combo": ("Audience", "Target reader age. Drives sentence length, peril level, and the voice directive sent to every agent."),
    "author_combo": ("Author Voice", "The prose style to imitate. Changing it rewrites how ALL chapters sound."),
    "author_search": ("Research Author", "Type any author's name and hit 'Analyze Author' to build a custom voice card from web + model knowledge."),
    "analyze_author_btn": ("Analyze Author", "Researches the typed author online and adds their voice to the dropdown for this session."),
    "pages_spin": ("Total Pages", "Rough length target. The engine estimates chapter count from this."),
    "review_preference_combo": ("Chapter Review", "AI = automatic content review + editing. Human = skip automated polishing."),
    "worldbuilding_check": ("Worldbuilding", "Enable the Worldbuilding Agent to flesh out the story's world, history, and rules."),
    "include_images": ("Generate Images", "Turn on AI illustration of pages/scenes using the selected image provider."),
    "img_freq_combo": ("Image Frequency", "How often to create images: none, per chapter, per page, or every N pages."),
    "img_interval_spin": ("Every N Pages", "When frequency is 'every_n', generate an image on this page interval."),
    "color_combo": ("Image Style", "Color or black-and-white illustrations."),
    "style_edit": ("Art Style", "Free-text art direction for images (e.g. watercolor, ink sketch, digital art)."),
    "generate_btn": ("Generate Book", "Run the multi-agent pipeline: concept -> outline -> characters -> (world) -> chapters -> export."),
    "status_label": ("Status", "Live progress and last action from the generation engine."),
    "text_provider_combo": ("Text Provider", "LLM service used to write the book. API key + model configured alongside."),
    "img_provider_combo": ("Image Provider", "Service used to generate illustrations."),
    "vertex_ai_check": ("Use Vertex AI", "Route Google image generation through GCP Vertex AI using your project credentials."),
}

_AUDIENCE_DESCRIPTIONS = AUDIENCE_GUIDANCE

AUDIENCE_VISUAL_GUIDANCE = {
    "Children":     "Soft peril only: menacing shadows, glowing eyes, gentle monster silhouettes. Wholesome, warm colors.",
    "Middle Grade": "Stylized peril: cartoonish claw marks, faint scars, simple shadow villains. Rich colors but not grim.",
    "Young Adult":  "PG-13 fantasy combat: armoured wounds, magical burns, occasional severed dragon head shown as silhouette. Cinematic chiaroscuro; no explicit gore.",
    "Adult":        "Frank fantasy violence when story demands: beheading, dismemberment, battlefield carnage. Painterly / realist-leaning palette.",
    "All Ages":     "PG-equivalent of the genre: victory-scene peril at most. Clean comic linework.",
}

AUDIENCE_VIOLENCE_FORBIDDEN = {
    "Children":    "FORBIDDEN: severed body parts, blood pools, modern firearms, torture, detailed corpses, sexual content of any kind.",
    "Middle Grade":"FORBIDDEN: dismemberment, glistening gore, modern firearms, torture, sexual content.",
    "Young Adult": "FORBIDDEN: sexualized violence, sustained torture, flinching/body horror for its own sake.",
    "Adult":       "(rely on writer judgment; no hard lines).",
    "All Ages":    "FORBIDDEN: anything beyond stylized implied peril at most.",
}

AUTHOR_CHAPTER_HEADER = {
    "Children":    False,
    "Middle Grade": True,
    "Young Adult":  True,
    "Adult":        True,
    "All Ages":     True,
}


def _audience_image_directive(audience: str) -> str:
    g = AUDIENCE_VISUAL_GUIDANCE.get(audience, "")
    f = AUDIENCE_VIOLENCE_FORBIDDEN.get(audience, "")
    if g and f and not str(f).startswith("(rely"):
        return f"AUDIENCE: {audience}. {g} {f}"
    if g:
        return f"AUDIENCE: {audience}. {g}"
    return ""


def _chapter_header_enabled(audience: str) -> bool:
    return AUTHOR_CHAPTER_HEADER.get(audience, True)


def _drop_pollinations_when_banana_active(
    configs: List["ImageProviderConfig"],
    banana_enabled: bool,
) -> List["ImageProviderConfig"]:
    """Block 3: drop Pollinations from the image-router config list when
    Google Nano Banana is actively enabled. Returns a new list; never mutates
    the input. If Banana is not enabled, returns the list unchanged.
    """
    if not banana_enabled:
        return list(configs)
    return [c for c in configs if getattr(c, "name", "") != "Pollinations"]


# Block 7 — graphic-novel content minimums. We refuse to render an
# export if the engine produced empty or scaffold page text and we
# know the format is graphic-novel.
_GRAPHIC_SCAFFOLD_TEXT = (
    "[scene content unavailable]",
    "[scene 1 content unavailable]",
    "no logline available",
    "the story continues with new developments.",
    "a new chapter in the unfolding story.",
)
_MIN_PAGE_CHARS = 40


def _collect_graphic_minimum_issues(book: Dict) -> list:
    issues: list = []
    pages = book.get("pages") or []
    if not pages:
        issues.append("engine produced 0 pages")
        return issues
    empty_text = 0
    scaffold_text = 0
    for idx, p in enumerate(pages, start=1):
        text = (p.get("text") or "").strip()
        if not text:
            empty_text += 1
            continue
        low = text.lower().strip()
        if low in _GRAPHIC_SCAFFOLD_TEXT or "scene content unavailable" in low:
            scaffold_text += 1
        elif len(text) < _MIN_PAGE_CHARS and low.startswith("**scene"):
            scaffold_text += 1
    if empty_text:
        issues.append(f"{empty_text} pages have empty text")
    if scaffold_text:
        issues.append(f"{scaffold_text} pages contain only scaffold text")

    chars = book.get("characters") or []
    if not chars:
        issues.append("graphic-novel must have at least one character")
    return issues


def _build_visual_doctrine(book: Dict) -> str:
    """Build a concise cross-page character/location visual doctrine.

    Returns a short directive suitable for prepending to every image prompt so
    the generative model renders the same face/hair/clothing/palette across
    every page. Returns "" if there's not enough structured data.
    """
    try:
        chars = (book.get("characters") or [])[:3]
        locs = (book.get("locations") or [])[:2]
    except Exception:
        return ""
    parts = []
    for c in chars:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        desc = (
            c.get("physical_description")
            or c.get("description")
            or c.get("background")
            or ""
        ).strip()
        if not name and not desc:
            continue
        if desc:
            parts.append(f"{name}: {desc}" if name else desc)
        else:
            parts.append(name)
    for loc in locs:
        if not isinstance(loc, dict):
            continue
        name = (loc.get("name") or loc.get("title") or "").strip()
        desc = (loc.get("description") or loc.get("summary") or "").strip()
        if not name:
            continue
        if desc:
            parts.append(f"Location {name}: {desc}")
        else:
            parts.append(f"Location {name}")
    if not parts:
        return ""
    return (
        "VISUAL DOCTRINE — keep all character/location features IDENTICAL across every "
        "page: " + "; ".join(parts)
    )


AUTHOR_CHAPTER_STYLE = {
    "Margaret Weis & Tracy Hickman": (5, 8),
    "R.A. Salvatore": (6, 7),
    "Brandon Sanderson": (4, 10),
    "Patrick Rothfuss": (3, 12),
    "Ursula K. Le Guin": (4, 10),
    "J.R.R. Tolkien": (4, 10),
    "Robin Hobb": (5, 8),
    "Neil Gaiman": (5, 8),
    "Naomi Novik": (5, 8),
    "Susanna Clarke": (4, 10),
    "Tad Williams": (5, 8),
    "Isaac Asimov": (6, 7),
    "Lois McMaster Bujold": (6, 7),
    "Robert A. Heinlein": (6, 7),
    "Arthur C. Clarke": (5, 8),
    "Philip K. Dick": (6, 7),
    "William Gibson": (6, 7),
    "Octavia Butler": (5, 8),
    "Becky Chambers": (6, 7),
    "Ann Leckie": (5, 8),
    "Liu Cixin": (4, 12),
    "Andy Weir": (7, 6),
    "Stephen King": (6, 7),
    "Shirley Jackson": (4, 10),
    "H.P. Lovecraft": (4, 10),
    "Daniel Handler": (6, 7),
    "Thomas Ligotti": (4, 10),
    "Clive Barker": (5, 8),
}


def _estimate_chapters(total_pages: int, author_name: str) -> int:
    """Estimate chapter count based on pages and author style."""
    for name, (min_ch, max_ch) in AUTHOR_CHAPTER_STYLE.items():
        if name.lower() in (author_name or '').lower():
            return min(max_ch, max(min_ch, total_pages // 3))
    return max(3, total_pages // 4)


def _author_chapter_plan(total_pages: int, author_name: str) -> list:
    ch_count = _estimate_chapters(total_pages, author_name)
    base = total_pages // ch_count
    rem = total_pages % ch_count
    plan = []
    for i in range(ch_count):
        pc = base + (1 if i < rem else 0)
        plan.append((f"Chapter {i+1}", pc))
    return plan


def _structure_directive_short(num_pages: int, idx: int) -> str:
    pct = (idx + 1) / num_pages
    if pct <= 0.15:
        return "SETUP: Establish world, protagonist, status quo. Hook the reader."
    elif pct <= 0.35:
        return "INCITING INCIDENT: Disrupt status quo. Protagonist reacts. Stakes appear."
    elif pct <= 0.6:
        return "RISING ACTION: Complications. Allies/enemies. Skills tested. Secrets revealed."
    elif pct <= 0.85:
        return "CLIMAX: Highest tension. Confrontation. Irreversible choice."
    else:
        return "RESOLUTION: Aftermath. New equilibrium. Emotional payoff."


def _page_length(audience: str) -> str:
    return {
        "Children": "~60-90 words. One simple scene. 3-5 short sentences.",
        "Middle Grade": "~150-200 words. One focused scene. 6-10 sentences.",
        "Young Adult": "~200-300 words. One scene with subtext. 8-12 sentences.",
        "Adult": "~250-350 words. Layered scene. 10-15 sentences.",
        "All Ages": "~100-150 words. Clear scene. 5-8 sentences.",
    }.get(audience, "~200 words. One scene.")


def _extract_json_str_value(text: str, key: str) -> Optional[str]:
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            return data.get(key, '')
    except Exception:
        pass
    return None


def _looks_like_leak(text: str) -> bool:
    return any(marker in text.lower() for marker in [
        'as an ai', 'here is the', 'i cannot', 'certainly!', 'here are',
        'i would be happy', 'of course!', 'sure, here'
    ])


def _ends_properly(text: str) -> bool:
    text = text.strip()
    return text.endswith(('.', '!', '?', '"', ')', '...', '—', '”', '…'))


def _generate_outline(settings, router) -> list:
    """Generate a chapter outline with beats. Returns list of chapter dicts."""
    s = settings
    theme = s['theme']
    setting = s.get('setting', '') or 'an unspecified place'
    audience = s['audience']
    genre = s['genre']
    author_name = s.get('author_voice') or ''
    author = get_author_voice(author_name, genre)
    num_pages = s['num_pages']
    aud_guide = AUDIENCE_GUIDANCE.get(audience, '')
    gen_guide = _genre_guidance(genre)

    prompt = f'You are planning a {audience} {genre} book.'
    prompt += f' AUDIENCE: {aud_guide}'
    prompt += f' GENRE: {gen_guide}'
    prompt += f' AUTHOR: {author.name}. {author.style}'
    prompt += f' The total pages: {num_pages}.'
    prompt += f' Chapter plan: {_author_chapter_plan(num_pages, author_name)}'
    prompt += f' Theme: {theme}. Setting: {setting}.'
    prompt += ' Produce a JSON outline with exact structure:'
    prompt += ' {"chapters": [{"title": "Ch 1", "beats": ["beat1", "beat2"]}]}'
    prompt += ' Each beat = ONE page, one sentence. Consistent characters.'
    prompt += ' No meta commentary. Just the JSON.'

    try:
        text = _generate_with_retry(prompt, router)
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            data = json.loads(text[start:end])
            chapters = data.get('chapters', [])
            if chapters:
                return chapters
    except Exception:
        pass
    return _synthesize_outline(num_pages, audience, genre, theme, setting)


def _synthesize_outline(num_pages, audience, genre, theme, setting) -> list:
    plan = _author_chapter_plan(num_pages, '')
    chapters, idx = [], 0
    for title, pc in plan:
        beats = []
        for i in range(pc):
            stage = 'setup' if idx < num_pages * 0.25 else 'develop' if idx < num_pages * 0.65 else 'climax' if idx < num_pages - 1 else 'resolution'
            beats.append(f'Page {idx+1}: {stage} - scene about {theme} in {setting}')
            idx += 1
        chapters.append({'title': title, 'beats': beats})
    return chapters


def _generate_with_retry(prompt, router, retries=3):
    last_err = ''
    for attempt in range(retries + 1):
        try:
            messages = [{'role': 'user', 'content': prompt}]
            res, used = router.complete(messages, max_tokens=1500, temperature=0.8)
            if res.ok and res.text and len(res.text) >= 20:
                return res.text
            last_err = res.error or f'too short ({len(res.text) if res.text else 0} chars)'
        except Exception as e:
            last_err = str(e)
        time.sleep(3 + attempt * 3)
    raise RuntimeError(f'Text generation failed after {retries+1} attempts: {last_err}')


def generate_full_book_json(settings, router) -> dict:
    """Generate the COMPLETE book JSON before any page text."""
    s = settings
    theme = s['theme']
    setting = s.get('setting', '') or 'an unspecified place'
    audience = s['audience']
    genre = s['genre']
    author_name = s.get('author_voice') or ''
    author = get_author_voice(author_name, genre)
    num_pages = max(1, int(s.get('num_pages', 12)))

    outline = _generate_outline(settings, router)

    char_prompt = f'List 2-5 characters for a {audience} {genre} book.'
    char_prompt += f' Theme: {theme}. Setting: {setting}'
    char_prompt += ' Return JSON: {"characters": [{"name": "", "role": "", "traits": []}]}'

    characters = [
        {'id': 'protagonist', 'name': 'Unknown', 'role': 'protagonist', 'traits': ['brave', 'curious']},
        {'id': 'ally', 'name': 'Unknown', 'role': 'ally', 'traits': ['wise', 'cautious']},
        {'id': 'antagonist', 'name': 'Unknown', 'role': 'antagonist', 'traits': ['mysterious', 'powerful']},
    ]

    try:
        text = _generate_with_retry(char_prompt, router)
        start = text.find('{')
        end = text.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            if parsed.get('characters'):
                characters = parsed['characters']
    except Exception:
        pass

    flat_beats = []
    for c_idx, ch in enumerate(outline):
        for b_idx, beat in enumerate(ch.get('beats', [])):
            flat_beats.append({'ch': c_idx, 'beat': beat, 'title': ch.get('title', 'Chapter')})

    book_json = {
        'metadata': {
            'title': 'Untitled',
            'blurb': '',
            'audience': audience,
            'genre': genre,
            'author_voice': author_name,
            'theme': theme,
            'setting': setting,
            'total_pages': num_pages,
            'target_words': 250 * num_pages,
            'created': datetime.now().isoformat(),
        },
        'characters': characters,
        'locations': [],
        'items': [],
        'plot_threads': [],
        'key_questions': [],
        'chapter_summaries': [],
        'outline': outline,
        'flat_beats': flat_beats,
        'pages': [],
        'cover_url': None,
        'images': [],
    }
    return book_json


class WorkerSignals(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    page_ready = pyqtSignal(int, str, str)


class ImageGenerationFailed(RuntimeError):
    """Raised when the image router fails to deliver an image after retries.

    Carries a 1-based page index and the last error string so the GUI
    can surface a precise failure reason (per Block 2).
    """
    def __init__(self, page_index: int, message: str):
        super().__init__(f"Image generation failed on page {page_index}: {message}")
        self.page_index = page_index
        self.message = message


class EngineGenerationWorker(QRunnable):
    """Background worker that runs the LibriScribe/BookEngine pipeline."""

    def __init__(self, engine: BookEngine, settings: Dict, image_router: ImageRouter):
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.image_router = image_router
        self.signals = WorkerSignals()
        self._cancelled = False
        self._visual_doctrine = ""
        self._book = None

    def cancel(self):
        self._cancelled = True
        self.engine.cancel()

    def _author_art_hint(self) -> str:
        """Visual-style hint for illustrations, derived from the chosen author voice."""
        author_name = self.settings.get('author_voice', '')
        genre = self.settings.get('genre', '')
        av = get_author_voice(author_name, genre)
        if av and getattr(av, 'visual_style', ''):
            return av.visual_style
        if av and getattr(av, 'name', ''):
            return f"art style evocative of {av.name}'s illustrated books"
        return ""

    def _audience_for(self, book: Dict) -> str:
        md = (book.get('metadata') or {})
        return (md.get('audience') or self.settings.get('audience', '') or '').strip()

    def _llm_text(self, prompt: str) -> str:
        """Run a text prompt through the engine's LLM client (or free fallback)."""
        client = getattr(getattr(self.engine, '_pm', None), 'llm_client', None)
        if client is not None:
            try:
                return client.generate_content(prompt, max_tokens=900, temperature=0.4) or ""
            except Exception:
                pass
        # Fallback: Pollinations anonymous text endpoint (no key).
        try:
            import urllib.parse, requests
            url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt[:2000])
            r = requests.get(url, timeout=90)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        return ""

    @pyqtSlot()
    def run(self):
        try:
            book = self._run_generation()
            self.signals.finished.emit(book)
        except Exception:
            self.signals.error.emit(traceback.format_exc())

    def _run_generation(self) -> Dict:
        settings = self.settings
        total_pages = max(1, int(settings.get('num_pages', 12)))
        total_chapters = _estimate_chapters(total_pages, settings.get('author_voice', ''))

        self.signals.progress.emit('Phase 1/5: Generating concept...')
        self.engine.generate_concept()
        if self._cancelled:
            raise RuntimeError('Generation cancelled')

        self.signals.progress.emit('Phase 2/5: Generating characters...')
        self.engine.generate_characters()
        if self._cancelled:
            raise RuntimeError('Generation cancelled')

        if settings.get('worldbuilding_needed', False):
            self.signals.progress.emit('Phase 3/5: Generating worldbuilding...')
            self.engine.generate_worldbuilding()
            if self._cancelled:
                raise RuntimeError('Generation cancelled')

        self.signals.progress.emit('Phase 4/5: Generating outline (informed by characters/world)...')
        self.engine.generate_outline()
        if self._cancelled:
            raise RuntimeError('Generation cancelled')

        self.signals.progress.emit(f'Phase 5/5: Writing {total_chapters} chapters...')
        for chapter_num in range(1, total_chapters + 1):
            if self._cancelled:
                raise RuntimeError('Generation cancelled')
            self.signals.progress.emit(f'Writing chapter {chapter_num}/{total_chapters}...')
            self.engine.write_chapter(chapter_num)

        book = self.engine.to_legacy_book_json()
        if not book:
            raise RuntimeError('Book engine returned empty book data')

        genre = book.get('metadata', {}).get('genre', self.settings.get('genre', ''))
        if _is_graphic(genre):
            issues = _collect_graphic_minimum_issues(book)
            if issues:
                raise RuntimeError(
                    "Graphic-novel content did not meet export minimums: "
                    + "; ".join(issues)
                )

        self._book = book
        self._visual_doctrine = _build_visual_doctrine(book) or ""
        if not self._visual_doctrine:
            try:
                self.signals.progress.emit(
                    "No structured character/location data — visuals will rely on author style only.")
            except Exception:
                pass

        self._generate_images(book)
        return book

    def _generate_images(self, book: Dict):
        include_images = self.settings.get('include_images', False)
        if not include_images:
            return

        genre = book.get('metadata', {}).get('genre', self.settings.get('genre', ''))
        if _is_graphic(genre):
            self._generate_graphic_novel(book)
            return

        image_freq = self.settings.get('image_freq', 'none')
        img_interval = max(1, int(self.settings.get('img_interval', 5)))
        style_phrase = self.settings.get('style_phrase', 'professional illustration')
        genre = book.get('metadata', {}).get('genre', self.settings.get('genre', ''))
        theme = self.settings.get('theme', '')
        setting = self.settings.get('setting', '')
        title = book.get('metadata', {}).get('title', 'Untitled')


        pages = book.get('pages', [])
        audience_directive = _audience_image_directive(self._audience_for(book))
        visual_doctrine = self._visual_doctrine or ''
        if image_freq == 'every_page':
            for idx, page in enumerate(pages):
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                self.signals.progress.emit(f'Generating image {idx+1}/{len(pages)}...')
                art_prompt = (
                    f'{style_phrase}, {self._author_art_hint()}, {audience_directive}, '
                    f'{visual_doctrine}, {genre} book art: {page.get("text", "")[:120]}'
                ).replace(', ,', ',')
                try:
                    res, _ = self.image_router.generate(art_prompt)
                    if res.ok:
                        page['img_url'] = res.path
                except Exception:
                    pass
        elif image_freq == 'every_n':
            for idx, page in enumerate(pages):
                if idx % img_interval != 0:
                    continue
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                self.signals.progress.emit(f'Generating image for page {idx+1}...')
                art_prompt = (
                    f'{style_phrase}, {self._author_art_hint()}, {audience_directive}, '
                    f'{visual_doctrine}, {genre} book art: {page.get("text", "")[:120]}'
                ).replace(', ,', ',')
                try:
                    res, _ = self.image_router.generate(art_prompt)
                    if res.ok:
                        page['img_url'] = res.path
                except Exception:
                    pass
        elif image_freq == 'every_chapter':
            seen = set()
            for idx, page in enumerate(pages):
                chapter = page.get('chapter', '')
                if not chapter or chapter in seen:
                    continue
                seen.add(chapter)
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                self.signals.progress.emit(f'Generating chapter image: {chapter}...')
                art_prompt = (
                    f'{style_phrase}, {self._author_art_hint()}, {audience_directive}, '
                    f'{visual_doctrine}, {genre} chapter illustration, {chapter}: '
                    f'{page.get("text", "")[:120]}'
                ).replace(', ,', ',')
                try:
                    res, _ = self.image_router.generate(art_prompt)
                    if res.ok:
                        page['img_url'] = res.path
                except Exception:
                    pass

        self.signals.progress.emit('Generating cover...')
        cover_prompt = (
            f'{style_phrase}, {self._author_art_hint()}, {audience_directive}, '
            f'{visual_doctrine}, {genre} book cover, KDP 2560x1600, professional: '
            f'{theme} in {setting}. Title: {title}'
        ).replace(', ,', ',')
        try:
            res, _ = self.image_router.generate(cover_prompt)
            if res.ok:
                book['cover_url'] = res.path
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Graphic Novel pipeline
    # ------------------------------------------------------------------
    def _parse_gn_script(self, raw: str) -> Dict:
        """Extract a {panels, dialoge, narrator} dict from an LLM response."""
        import re, json
        if not raw:
            return {"panels": [], "dialogue": [], "narrator": ""}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return {"panels": [], "dialogue": [], "narrator": ""}
        try:
            d = json.loads(m.group(0))
        except Exception:
            return {"panels": [], "dialogue": [], "narrator": ""}
        panels = d.get("panels") or []
        if isinstance(panels, list) and panels and isinstance(panels[0], str):
            panels = [{"desc": p} for p in panels]
        dialogue = d.get("dialogue") or []
        if not isinstance(dialogue, list):
            dialogue = [str(dialogue)]
        return {
            "panels": [{"desc": str(p.get("desc", ""))} for p in panels if isinstance(p, dict)],
            "dialogue": [str(x) for x in dialogue],
            "narrator": str(d.get("narrator", "")),
        }

    def _parse_panel_script_text(self, raw: str) -> Dict:
        """Parse an already-written panel script (the [Panel N] / VISUAL: /
        NARRATION: / DIALOGUE: markdown the chapter writer emits) into the
        same {panels, dialogue, narrator} shape as _parse_gn_script.

        This lets the graphic image stage use the REAL chapter text instead of
        re-deriving a script from it (which is what produced images before
        the chapter text was ready).
        """
        import re
        panels, dialogue, narrator_parts = [], [], []
        for blk in re.split(r"\[Panel\s*\d+\]", raw or ""):
            blk = blk.strip()
            if not blk:
                continue
            vis = ""
            m = re.search(r"VISUAL:\s*(.*?)(?=NARRATION:|DIALOGUE:|$)",
                          blk, re.DOTALL | re.IGNORECASE)
            if m:
                vis = m.group(1).strip()
            nar = ""
            m = re.search(r"NARRATION:\s*(.*?)(?=DIALOGUE:|$)",
                          blk, re.DOTALL | re.IGNORECASE)
            if m:
                nar = m.group(1).strip()
            dlg = []
            m = re.search(r"DIALOGUE:\s*(.*)$", blk, re.DOTALL | re.IGNORECASE)
            if m:
                for line in m.group(1).splitlines():
                    line = line.strip()
                    if line:
                        dlg.append(line)
            if vis:
                panels.append({"desc": vis})
            if nar:
                narrator_parts.append(nar)
            dialogue.extend(dlg)
        return {
            "panels": panels,
            "dialogue": dialogue,
            "narrator": " ".join(narrator_parts),
        }

    def _draw_text_wrapped(self, draw, xy, text, font, max_w, fill):
        """Draw text wrapped to max_w px, returning the y just below it."""
        import textwrap
        x, y = xy
        for line in textwrap.wrap(text, width=max(8, max_w // max(1, font.size))) or [""]:
            draw.text((x, y), line, font=font, fill=fill)
            y += int(font.size * 1.25)
        return y

    def _load_pil_font(self, size: int):
        """Try to load a real TTF font; fall back to PIL default.

        Honors Windows system fonts (Segoe UI, Arial, Consolas, Verdana)
        first so lettered image text is readable; on other platforms
        drops straight to PIL's bundled default.
        """
        try:
            from PIL import ImageFont
        except Exception:
            return None
        candidates = []
        if sys.platform == "win32":
            win_fonts = os.environ.get("WINDIR", r"C:\Windows") + r"\Fonts"
            candidates += [
                os.path.join(win_fonts, "segoeuib.ttf"),  # Segoe UI Semibold
                os.path.join(win_fonts, "segoeui.ttf"),
                os.path.join(win_fonts, "arialbd.ttf"),
                os.path.join(win_fonts, "arial.ttf"),
                os.path.join(win_fonts, "consola.ttf"),
            ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _letter_gn_image(
        self,
        img_path: str,
        script: Dict,
        *,
        draw_chapter_strip: bool = False,
        chapter_label: str = "",
        page_index: Optional[int] = None,
        total_pages: Optional[int] = None,
    ) -> Optional[str]:
        """Composite narrator caption + speech bubbles onto the page image.

        Optional overlays (Block 5):
          * Top-left chapter title strip on the first page of each chapter
            (skipped for "Children" audience by the caller).
          * Bottom-right page-number badge (always-on, e.g. "3 / 12").

        Returns the lettered image path (falls back to the original when PIL
        is unavailable). Uses only PIL (no external font deps).
        """
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
        except Exception:
            return None
        try:
            img = Image.open(img_path).convert("RGBA")
        except Exception:
            return None
        W, H = img.size
        draw = ImageDraw.Draw(img)

        # Chapter title strip (Block 5) — drawn first so bubbles can overlap.
        if draw_chapter_strip and chapter_label:
            header_h = max(28, int(H * 0.07))
            strip_font = self._load_pil_font(max(14, int(H * 0.035)))
            draw.rectangle([(0, 0), (W, header_h)], fill=(0, 0, 0, 170))
            text_color = (255, 255, 255, 255)
            label = str(chapter_label).strip()
            if label:
                if strip_font is not None:
                    draw.text(
                        (16, max(4, (header_h - int(H * 0.04)) // 2)),
                        label[:90],
                        font=strip_font,
                        fill=text_color,
                    )
                else:
                    draw.text((16, 6), label[:90], fill=text_color)

        # Narrator caption bar (existing behavior). If the chapter header
        # already drew on the top strip, push the narrator bar below it.
        narrator = script.get("narrator", "")
        if narrator:
            default_font = self._load_pil_font(max(14, int(H * 0.04)))
            bar_top = header_h if draw_chapter_strip and chapter_label else 0
            bar_h = max(24, int(H * 0.10))
            draw.rectangle([(0, bar_top), (W, bar_top + bar_h)],
                           fill=(0, 0, 0, 150))
            if default_font is not None:
                self._draw_text_wrapped(
                    draw, (10, bar_top + 6), narrator,
                    default_font, W - 20, (255, 255, 255, 255),
                )

        # Speech bubbles (bottom-up)
        dialogue = script.get("dialogue", [])
        bubble_font = self._load_pil_font(max(14, int(H * 0.04)))
        if dialogue and bubble_font is not None:
            n = len(dialogue)
            bubble_h = max(26, int(H * 0.12))
            gap = 6
            total = n * bubble_h + (n - 1) * gap
            y = H - total - 8
            for i, line in enumerate(dialogue):
                top = y + i * (bubble_h + gap)
                draw.ellipse([(8, top), (W - 8, top + bubble_h)],
                             fill=(255, 255, 255, 235),
                             outline=(0, 0, 0, 255))
                self._draw_text_wrapped(draw, (18, top + 5), line,
                                        bubble_font, W - 36, (0, 0, 0, 255))

        # Page-number badge (always emitted in graphic-novel flow).
        if page_index is not None and total_pages:
            try:
                badge_font = self._load_pil_font(max(12, int(H * 0.022)))
                pad_x = 12
                pad_y = 6
                txt = f"{int(page_index)} / {int(total_pages)}"
                tw = 0
                th = 0
                if badge_font is not None:
                    try:
                        bbox = badge_font.getbbox(txt)
                        tw = (bbox[2] - bbox[0]) if bbox else len(txt) * 7
                        th = (bbox[3] - bbox[1]) if bbox else int(H * 0.022)
                    except Exception:
                        tw = len(txt) * 7
                        th = int(H * 0.022)
                box_w = tw + pad_x * 2
                box_h = th + pad_y * 2
                x0 = max(0, W - box_w - 14)
                y0 = max(0, H - box_h - 14)
                draw.rectangle(
                    [(x0, y0), (x0 + box_w, y0 + box_h)],
                    fill=(0, 0, 0, 170),
                )
                if badge_font is not None:
                    draw.text(
                        (x0 + pad_x, y0 + pad_y),
                        txt,
                        font=badge_font,
                        fill=(255, 255, 255, 255),
                    )
            except Exception:
                pass

        out = img_path.rsplit(".", 1)[0] + "_lettered.png"
        try:
            img.convert("RGB").save(out)
        except Exception:
            return None
        return out

    def _generate_graphic_novel(self, book: Dict):
        """Visual-first pipeline: prose -> panel script -> art -> editor lettering.

        Cuts the heavy prose down to a panel script, spills the panel
        descriptions into the image generator, then has the editor fill in
        speech-bubble dialogue + a narrator caption, composited onto the art.
        """
        pages = book.get("pages", [])
        genre = book.get("metadata", {}).get("genre", "Graphic Novel")
        author_art = self._author_art_hint()
        theme = self.settings.get("theme", "")
        setting = self.settings.get("setting", "")
        audience = self._audience_for(book)
        audience_directive = _audience_image_directive(audience)
        visual_doctrine = self._visual_doctrine or ""
        header_enabled = _chapter_header_enabled(audience)
        total_pages = max(1, len(pages))

        prev_chapter = None
        for idx, page in enumerate(pages):
            if self._cancelled:
                raise RuntimeError("Generation cancelled")
            self.signals.progress.emit(f"Graphic novel page {idx+1}/{len(pages)}...")

            # The chapter text MUST exist before we can draw anything.
            prose = (page.get("text", "") or "").strip()
            if not prose:
                self.signals.progress.emit(
                    f"Skip page {idx+1}: chapter text not available yet")
                continue

            # 1) Get the panel script. If the chapter text is ALREADY a
            #    panel script (engine path), use it directly. Otherwise
            #    derive one from the prose via the LLM (legacy path).
            is_script = bool(re.search(r"\[Panel|VISUAL:", prose, re.IGNORECASE))
            if is_script:
                script = self._parse_panel_script_text(prose)
            else:
                script_prompt = (
                    f"You are a comic-book scriptwriter. Turn the scene into a "
                    f"{genre} graphic-novel page. Output STRICT JSON only:\n"
                    '{"panels":[{"desc":"visual description, no text"}], '
                    '"dialogue":["short line","short line"], "narrator":"one short caption"}\n'
                    "Keep each dialogue line <=12 words. Scene:\n" + prose[:700]
                )
                script = self._parse_gn_script(self._llm_text(script_prompt))
                if not script.get("panels"):
                    raise RuntimeError(
                        f"Page {idx+1}: panel script generation returned no panels.")

            # 2) Spill the panel descriptions into the image generator.
            panel_desc = " | ".join(
                p.get("desc", "") for p in script["panels"]
            ) or prose[:200]
            full_prompt = (
                f"{author_art}, {audience_directive}, {visual_doctrine}, "
                f"{genre} graphic novel page art: {panel_desc[:220]}"
            ).replace(", ,", ",").strip()

            # Block 2: retry up to 3 attempts — same prompt, then simplified,
            # then raise ImageGenerationFailed if all fail. No silent skip,
            # so export can never ship a half-illustrated graphic novel.
            attempts = [
                full_prompt,
                full_prompt,
                f"{author_art}, {genre} graphic novel page art: {panel_desc[:220]}",
            ]
            res = None
            last_err = None
            for attempt_idx, attempt_prompt in enumerate(attempts, start=1):
                try:
                    res, _ = self.image_router.generate(attempt_prompt)
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
                    res = None
                if res and getattr(res, "ok", False) and getattr(res, "path", ""):
                    break
                last_err = last_err or (getattr(res, "error", "") or "unknown")
                if attempt_idx < len(attempts):
                    time.sleep(1.0)

            if not res or not getattr(res, "ok", False) or not getattr(res, "path", ""):
                raise ImageGenerationFailed(
                    idx + 1, last_err or "all image providers failed")
            img_path = res.path

            # 3) If we derived the script via LLM, let the editor refine the
            #    bubble dialogue + narrator voice. When the script came
            #    straight from the chapter text, keep that wording.
            if not is_script:
                edit_prompt = (
                    f"For this {genre} graphic novel panel, write the FINAL speech-bubble "
                    f"lines and a narrator caption. STRICT JSON only:\n"
                    '{"dialogue":["line","line"], "narrator":"caption"}\n'
                    "Panels depicted: " + panel_desc[:300]
                )
                edited = self._parse_gn_script(self._llm_text(edit_prompt))
                if edited.get("dialogue"):
                    script["dialogue"] = edited["dialogue"]
                if edited.get("narrator"):
                    script["narrator"] = edited["narrator"]

            # Block 5: chapter strip on the first page of each new chapter
            # (skipped for "Children" audience).
            chapter_label = page.get("chapter", "") or ""
            draw_chapter_strip = bool(
                header_enabled
                and chapter_label
                and chapter_label != prev_chapter
            )
            prev_chapter = chapter_label or prev_chapter

            # 4) Lettering: chapter strip + page badge + bubbles + caption.
            lettered = self._letter_gn_image(
                img_path,
                script,
                draw_chapter_strip=draw_chapter_strip,
                chapter_label=chapter_label,
                page_index=idx + 1,
                total_pages=total_pages,
            )
            page["img_url"] = lettered or img_path
            page["gn_script"] = script

        # Cover (visual-first, no text). Use the same visual doctrine +
        # audience directive so cover and pages match.
        self.signals.progress.emit("Generating cover...")
        cover_prompt = (
            f"{author_art}, {audience_directive}, {visual_doctrine}, "
            f"{genre} graphic novel cover art, professional: "
            f"{theme} in {setting}. No text, no titles."
        ).replace(", ,", ",").strip()
        try:
            res, _ = self.image_router.generate(cover_prompt)
            if res.ok and getattr(res, "path", ""):
                book["cover_url"] = res.path
        except Exception:
            pass


class GenerationWorker(QRunnable):
    """QRunnable worker for safe threading with QThreadPool."""
    def __init__(self, settings: Dict, router: Router, image_router: ImageRouter):
        super().__init__()
        self.settings = settings
        self.router = router
        self.image_router = image_router
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        try:
            book = self._run_generation()
            self.signals.finished.emit(book)
        except Exception as e:
            self.signals.error.emit(traceback.format_exc())

    def _run_generation(self) -> Dict:
        s = self.settings
        theme = s['theme']
        setting = s.get('setting', '') or 'an unspecified place'
        audience = s['audience']
        genre = s['genre']
        author_name = s.get('author_voice') or ''
        author = get_author_voice(author_name, genre)
        num_pages = max(1, int(s.get('num_pages', 12)))
        include_images = s.get('include_images', False)
        image_freq = s.get('image_freq', 'none')
        img_interval = max(1, int(s.get('img_interval', 5)))
        style_phrase = s.get('style_phrase', '')
        aud_guide = AUDIENCE_GUIDANCE.get(audience, '')
        gen_guide = _genre_guidance(genre)

        self.signals.progress.emit('Phase 1/4: Generating full book JSON...')
        book = generate_full_book_json(s, self.router)

        self.signals.progress.emit('Generating title and blurb...')
        title_prompt = f'Give a compelling title and 2-sentence blurb for a {audience} {genre} book. Theme: {theme}. Setting: {setting}. Author: {author.name}. Return JSON: {{"title": "", "blurb": ""}}'
        try:
            text = _generate_with_retry(title_prompt, self.router)
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                meta = json.loads(text[start:end])
                book['metadata']['title'] = meta.get('title', 'Untitled')
                book['metadata']['blurb'] = meta.get('blurb', '')
        except Exception:
            book['metadata']['title'] = book['metadata'].get('title', 'Untitled')
            book['metadata']['blurb'] = ''

        flat_beats = book.get('flat_beats', [])
        total_pages = min(num_pages, len(flat_beats))
        if total_pages == 0:
            raise RuntimeError('No beats generated')

        self.signals.progress.emit(f'Phase 2/4: Writing {total_pages} pages...')

        CHUNK_SIZE = 50
        pages_written = 0
        last_page_text = ''
        chapter_summaries = []
        summarized_chapters = set()

        for chunk_start in range(0, total_pages, CHUNK_SIZE):
            if self._cancelled:
                raise RuntimeError('Generation cancelled')
            chunk_end = min(chunk_start + CHUNK_SIZE, total_pages)
            self.signals.progress.emit(f'Writing pages {chunk_start+1}-{chunk_end}...')

            for page_idx in range(chunk_start, chunk_end):
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                fb = flat_beats[page_idx]
                role = _structure_directive_short(total_pages, page_idx)

                chars_str = json.dumps(book.get('characters', []), indent=2)[:2000]
                summaries_str = '\n'.join(chapter_summaries[-5:])
                if summaries_str:
                    summaries_str = 'Previous chapters:\n' + summaries_str

                page_prompt = f'You are writing page {page_idx+1} of {total_pages} for a {audience} {genre} book.'
                page_prompt += f' AUDIENCE: {aud_guide}'
                page_prompt += f' GENRE: {gen_guide}'
                page_prompt += f' AUTHOR: {author.name}'
                page_prompt += f' AUTHOR STYLE: {author.style}'
                page_prompt += f' AVOID: {author.donts}'
                page_prompt += f' THIS PAGE ROLE: {role}'
                page_prompt += f' CHAPTER: {fb["title"]}. BEAT: {fb["beat"]}'
                if last_page_text:
                    page_prompt += f' Previous page ended: {last_page_text[-200:]}. Continue from there.'
                page_prompt += summaries_str
                page_prompt += f' CHARACTERS:\n{chars_str}'
                page_prompt += f' LENGTH: {_page_length(audience)}'
                page_prompt += ' RULES: Consistent character names. Cause and effect. End on a small turn.'
                page_prompt += ' Output ONLY the page prose.'
                page_prompt += f' Theme: {theme}. Setting: {setting}.'

                page_text = self._generate_text(page_prompt)
                page_text = self._clean_text(page_text)

                if page_text and len(page_text) >= 30:
                    book['pages'].append({'text': page_text, 'img_url': None})
                    last_page_text = page_text
                    pages_written += 1
                    self.signals.page_ready.emit(page_idx, page_text, '')

                    current_ch = fb['ch']
                    next_ch = flat_beats[page_idx + 1]['ch'] if page_idx + 1 < total_pages else -1
                    if current_ch != next_ch and current_ch not in summarized_chapters:
                        ch = book.get('outline', [])[current_ch] if current_ch < len(book.get('outline', [])) else None
                        if ch:
                            chapter_summaries.append(f'Chapter {current_ch+1}: {ch.get("title", "")}')
                            summarized_chapters.add(current_ch)
                else:
                    self.signals.progress.emit(f'Page {page_idx+1} too short, skipping')

            if include_images and image_freq == 'every_n' and chunk_end > chunk_start:
                self.signals.progress.emit(f'Generating batch images for pages {chunk_start+1}-{chunk_end}...')
                for pi in range(chunk_start, min(chunk_end, len(book['pages']))):
                    if (pi - chunk_start) % img_interval != 0:
                        continue
                    if self._cancelled:
                        raise RuntimeError('Generation cancelled')
                    page = book['pages'][pi]
                    art_prompt = f'{style_phrase}, {genre} book art: {page["text"][:120]}'
                    try:
                        res, _ = self.image_router.generate(art_prompt)
                        if res.ok:
                            page['img_url'] = res.path
                    except Exception as e:
                        self.signals.progress.emit(f'Batch image {pi+1} failed: {e}')

        if not book['pages']:
            raise RuntimeError('No pages could be generated')

        if include_images and image_freq == 'every_chapter':
            self.signals.progress.emit('Phase 3/4: Generating chapter images...')
            outline = book.get('outline', [])
            page_idx = 0
            for ch_idx, ch in enumerate(outline):
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                ch_title = ch.get('title', f'Chapter {ch_idx+1}')
                beats = ch.get('beats', [])
                first_beat = beats[0] if beats else ''
                art_prompt = f'{style_phrase}, {genre} book chapter illustration, title "{ch_title}": {first_beat[:120]}'
                self.signals.progress.emit(f'Image for Chapter {ch_idx+1}: {ch_title}...')
                try:
                    res, _ = self.image_router.generate(art_prompt)
                    if res.ok and page_idx < len(book['pages']):
                        book['pages'][page_idx]['img_url'] = res.path
                except Exception as e:
                    self.signals.progress.emit(f'Chapter {ch_idx+1} image failed: {e}')
                page_idx += len(beats)

        if include_images and image_freq == 'every_page':
            self.signals.progress.emit('Phase 3/4: Generating per-page images...')
            for i, page in enumerate(book['pages']):
                if self._cancelled:
                    raise RuntimeError('Generation cancelled')
                art_prompt = f'{style_phrase}, {genre} book art: {page["text"][:120]}'
                try:
                    res, _ = self.image_router.generate(art_prompt)
                    if res.ok:
                        page['img_url'] = res.path
                except Exception as e:
                    self.signals.progress.emit(f'Image {i+1} failed: {e}')

        self.signals.progress.emit('Generating cover...')
        cover_prompt = f'{style_phrase}, {self._author_art_hint()}, {genre} book cover, KDP 2560x1600, professional: {theme} in {setting}. Title: {book["metadata"]["title"]}'
        try:
            res, _ = self.image_router.generate(cover_prompt)
            if res.ok:
                book['cover_url'] = res.path
        except Exception as e:
            self.signals.progress.emit(f'Cover failed: {e}')

        book['metadata']['chapter_summaries'] = chapter_summaries
        self.signals.progress.emit('Phase 4/4: Exporting...')
        return book

    def _generate_text(self, prompt: str, retries: int = 3) -> str:
        last_err = ''
        for attempt in range(retries + 1):
            try:
                messages = [{'role': 'user', 'content': prompt}]
                res, used = self.router.complete(messages, max_tokens=1500, temperature=0.8)
                if res.ok:
                    cleaned = self._clean_text(res.text)
                    if cleaned and len(cleaned) >= 30:
                        return cleaned
                    last_err = f'Response too short ({len(cleaned)} chars) from {used}'
                else:
                    last_err = res.error or 'unknown provider error'
            except Exception as e:
                last_err = str(e)
            time.sleep(3 + attempt * 3)
        raise RuntimeError(f'Text generation failed after {retries+1} attempts: {last_err}')

    def _clean_text(self, raw: str) -> str:
        raw = raw.strip()
        if not raw:
            return ''
        for marker in ('Assistant:', 'Response:', 'Output:', 'Text:', 'User:'):
            if raw.startswith(marker):
                raw = raw[len(marker):].strip()
        raw = raw.strip().strip('*"\'')
        return raw


def save_book_to_html(book: Dict, filepath: str) -> bool:
    try:
        html = ['<!DOCTYPE html><html><head><meta charset="utf-8"><title>', book['metadata'].get('title', 'Untitled'), '</title>']
        html.append('<style>body{font-family:Georgia,serif;max-width:700px;margin:2rem auto;line-height:1.6;padding:0 1rem}img{max-width:100%;height:auto}.page{page-break-after:always;margin-bottom:2rem}.cover{text-align:center;margin-bottom:2rem}</style></head><body>')
        if book.get('cover_url'):
            html.append(f'<div class="cover"><img src="{book["cover_url"]}" style="max-width:300px"><br><h1>{book["metadata"].get("title","")}</h1></div>')
        for i, page in enumerate(book['pages']):
            html.append(f'<div class="page"><h3>Page {i+1}</h3>')
            if page.get('img_url'):
                html.append(f'<img src="{page["img_url"]}">')
            html.append(f'<p>{page["text"].replace(chr(10), "</p><p>")}</p></div>')
        html.append('</body></html>')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(''.join(html))
        return True
    except Exception as e:
        print(f'HTML export failed: {e}')
        return False


def save_book_to_epub(book: Dict, filepath: str) -> bool:
    try:
        from ebooklib import epub
        from ebooklib.epub import EpubBook, EpubHtml, EpubNav, EpubNcx
        import uuid

        epub_book = EpubBook()
        epub_book.set_identifier(str(uuid.uuid4()))
        epub_book.set_title(book['metadata'].get('title', 'Untitled'))
        epub_book.set_language('en')
        epub_book.add_author(book['metadata'].get('author_voice', 'AI Author'))

        if book.get('cover_url') and os.path.exists(book['cover_url']):
            with open(book['cover_url'], 'rb') as f:
                epub_book.set_cover('cover.jpg', f.read())

        style = 'BODY {font-family: Georgia, serif; line-height: 1.6; margin: 1.5em;} H1 {text-align: center; page-break-before: always;} .page {page-break-after: always;}'
        nav_css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
        epub_book.add_item(nav_css)

        chapters = []
        title_html = f'<html><body><h1>{book["metadata"].get("title", "Untitled")}</h1><p>{book["metadata"].get("blurb", "")}</p></body></html>'
        title_ch = EpubHtml(title='Title', file_name='title.xhtml', lang='en')
        title_ch.content = title_html
        epub_book.add_item(title_ch)
        chapters.append(title_ch)

        copyright_html = f'<html><body><p>Copyright \u00a9 {datetime.now().year} {book["metadata"].get("author_voice", "AI Author")}</p><p>All rights reserved.</p></body></html>'
        copyright_ch = EpubHtml(title='Copyright', file_name='copyright.xhtml', lang='en')
        copyright_ch.content = copyright_html
        epub_book.add_item(copyright_ch)
        chapters.append(copyright_ch)

        toc_html = '<html><body><h1>Table of Contents</h1><ul>'
        for ch_idx, ch in enumerate(book.get('outline', [])):
            toc_html += f'<li>Chapter {ch_idx+1}: {ch.get("title", "")}</li>'
        toc_html += '</ul></body></html>'
        toc_ch = EpubHtml(title='Table of Contents', file_name='toc.xhtml', lang='en')
        toc_ch.content = toc_html
        epub_book.add_item(toc_ch)
        chapters.append(toc_ch)

        page_idx = 0
        for ch_idx, ch in enumerate(book.get('outline', [])):
            ch_title = ch.get('title', f'Chapter {ch_idx+1}')
            ch_content = f'<html><body><h1>{ch_title}</h1>'
            beats = ch.get('beats', [])
            for b_idx, beat in enumerate(beats):
                if page_idx >= len(book['pages']):
                    break
                page = book['pages'][page_idx]
                ch_content += f'<div class="page"><h3>Page {page_idx+1}</h3>'
                if page.get('img_url') and os.path.exists(page['img_url']):
                    img_name = f'img_{page_idx}.jpg'
                    with open(page['img_url'], 'rb') as img_f:
                        img_data = img_f.read()
                    epub_book.add_item(epub.EpubImage(uid=img_name, file_name=f'images/{img_name}', media_type='image/jpeg', content=img_data))
                    ch_content += f'<img src="images/{img_name}">'
                ch_content += f'<p>{page["text"].replace(chr(10), "</p><p>")}</p></div>'
                page_idx += 1
            ch_content += '</body></html>'
            ch_file = f'ch{ch_idx+1}.xhtml'
            chapter = EpubHtml(title=ch_title, file_name=ch_file, lang='en')
            chapter.content = ch_content
            chapter.add_item(nav_css)
            epub_book.add_item(chapter)
            chapters.append(chapter)

        about_html = f'<html><body><h1>About the Author</h1><p>Generated with Auto Book Generator using {book["metadata"].get("author_voice", "AI")} voice.</p></body></html>'
        about_ch = EpubHtml(title='About the Author', file_name='about.xhtml', lang='en')
        about_ch.content = about_html
        epub_book.add_item(about_ch)
        chapters.append(about_ch)

        epub_book.toc = [(epub.Section('Contents'), chapters)]
        epub_book.add_item(EpubNcx())
        epub_book.add_item(EpubNav())
        epub_book.spine = ['nav'] + chapters

        epub.write_epub(filepath, epub_book, {})
        return True
    except Exception as e:
        print(f'EPUB export failed: {e}')
        return False


def save_book_to_pdf(book: Dict, filepath: str) -> bool:
    try:
        from fpdf import FPDF
        import unicodedata

        def sanitize(text: str) -> str:
            return unicodedata.normalize('NFKD', text).encode('latin-1', 'replace').decode('latin-1')

        class PDF(FPDF):
            def header(self):
                if self.page_no() > 1:
                    self.set_font('Helvetica', 'I', 8)
                    self.cell(0, 5, sanitize(book['metadata'].get('title', '')), 0, 0, 'L')
                    self.cell(0, 5, f'Page {self.page_no()}', 0, 1, 'R')
                    self.line(10, 12, 200, 12)
                    self.ln(4)

            def footer(self):
                self.set_y(-15)
                self.set_font('Helvetica', 'I', 8)
                self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

        pdf = PDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        if book.get('cover_url') and os.path.exists(book['cover_url']):
            pdf.image(book['cover_url'], x=10, y=10, w=190)
            pdf.add_page()

        pdf.set_font('Helvetica', 'B', 24)
        pdf.ln(40)
        pdf.multi_cell(0, 12, sanitize(book['metadata'].get('title', 'Untitled')), align='C')
        pdf.ln(10)
        pdf.set_font('Helvetica', '', 14)
        pdf.multi_cell(0, 8, sanitize(book['metadata'].get('blurb', '')), align='C')
        pdf.add_page()

        pdf.set_font('Helvetica', '', 10)
        pdf.ln(60)
        pdf.cell(0, 6, sanitize(f'Copyright \u00a9 {datetime.now().year} {book["metadata"].get("author_voice", "AI Author")}'), 0, 1, 'C')
        pdf.cell(0, 6, 'All rights reserved.', 0, 1, 'C')
        pdf.add_page()

        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 10, 'Table of Contents', 0, 1, 'C')
        pdf.ln(5)
        pdf.set_font('Helvetica', '', 11)
        for ch_idx, ch in enumerate(book.get('outline', [])):
            pdf.cell(0, 8, sanitize(f'Chapter {ch_idx+1}: {ch.get("title", "")}'), 0, 1)
        pdf.add_page()

        page_idx = 0
        for ch_idx, ch in enumerate(book.get('outline', [])):
            pdf.set_font('Helvetica', 'B', 16)
            pdf.cell(0, 12, sanitize(ch.get('title', f'Chapter {ch_idx+1}')), 0, 1, 'C')
            pdf.ln(5)

            beats = ch.get('beats', [])
            for b_idx, beat in enumerate(beats):
                if page_idx >= len(book['pages']):
                    break
                page = book['pages'][page_idx]

                if page.get('img_url') and os.path.exists(page['img_url']):
                    try:
                        pdf.image(page['img_url'], x=15, w=180)
                        pdf.ln(5)
                    except Exception:
                        pass

                pdf.set_font('Helvetica', '', 11)
                pdf.multi_cell(0, 6, sanitize(page['text']))
                pdf.ln(8)
                page_idx += 1

        pdf.add_page()
        pdf.set_font('Helvetica', 'B', 16)
        pdf.cell(0, 12, 'About the Author', 0, 1, 'C')
        pdf.ln(5)
        pdf.set_font('Helvetica', '', 11)
        pdf.multi_cell(0, 6, sanitize(f'Generated with Auto Book Generator using {book["metadata"].get("author_voice", "AI")} voice.'))

        pdf.output(filepath)
        return True
    except Exception as e:
        print(f'PDF export failed: {e}')
        return False


def save_project_state(state: Dict) -> bool:
    try:
        with open(PROJECT_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f'Save failed: {e}')
        return False


def load_project_state() -> Optional[Dict]:
    if os.path.exists(PROJECT_FILE):
        try:
            with open(PROJECT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


class _ResearchSignals(QObject):
    finished = pyqtSignal(object)   # AuthorVoice or None
    error = pyqtSignal(str)


class AuthorResearchWorker(QRunnable):
    """Background worker: research an author and build a runtime AuthorVoice."""

    def __init__(self, name: str, llm_fn):
        super().__init__()
        self.name = name
        self.llm_fn = llm_fn
        self.signals = _ResearchSignals()

    def run(self):
        try:
            av = research_author_voice(self.name, self.llm_fn)
            self.signals.finished.emit(av)
        except Exception as e:  # noqa: BLE001
            self.signals.error.emit(str(e))


class BookGeneratorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Auto Book Generator')
        self.resize(1440, 920)
        self.setAcceptDrops(True)

        self.book_engine = BookEngine()
        self.image_router = None
        self.worker = None
        self.thread_pool = QThreadPool.globalInstance()
        self.current_book = None
        self._generation_running = False
        self._outline_updating = False

        self._build_ui()
        self._load_config()
        self._probe_all()
        self._restore_project()

        # Connect BookEngine signals
        self.book_engine.stage_started.connect(self._on_stage_started)
        self.book_engine.stage_completed.connect(self._on_stage_completed)
        self.book_engine.stage_failed.connect(self._on_stage_failed)
        self.book_engine.progress.connect(self._on_progress)
        self.book_engine.chapter_ready.connect(self._on_chapter_ready)
        self.book_engine.book_ready.connect(self._on_book_ready)
        self.book_engine.cost_update.connect(self._on_cost_update)
        self.book_engine.concept_ready.connect(self._on_concept_ready)
        self.book_engine.outline_ready.connect(self._on_outline_ready)
        self.book_engine.characters_ready.connect(self._on_characters_ready)
        self.book_engine.worldbuilding_ready.connect(self._on_worldbuilding_ready)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_api_tab()
        self._build_settings_tab()
        self._build_outline_tab()
        self._build_pages_tab()
        self._build_characters_tab()
        self._build_worldbuilding_tab()  # NEW
        self._build_images_tab()
        self._build_expert_config_tab()  # NEW
        self._build_cost_tracker_tab()   # NEW
        self._build_prompts_tab()        # NEW
        self._build_finished_tab()

        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.status_label = QLabel('Ready')
        self.status_label.setObjectName('status_label')
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.generate_btn = QPushButton('Generate Book')
        self.generate_btn.setObjectName('generate_btn')
        self.generate_btn.clicked.connect(self.on_generate_clicked)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setObjectName('cancel_btn')
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        self.cancel_btn.setEnabled(False)
        bar.addWidget(self.status_label)
        bar.addWidget(self.progress_bar)
        bar.addStretch()
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.generate_btn)
        main_layout.addLayout(bar)

        self._assign_help_objectnames()
        self._install_help()

    def _assign_help_objectnames(self):
        """Tag the key controls so the hover-help system can describe them."""
        for w, name in [
            (self.theme_edit, 'theme_edit'),
            (self.setting_edit, 'setting_edit'),
            (self.genre_list, 'genre_list'),
            (self.audience_combo, 'audience_combo'),
            (self.author_combo, 'author_combo'),
            (self.pages_spin, 'pages_spin'),
            (self.review_preference_combo, 'review_preference_combo'),
            (self.worldbuilding_check, 'worldbuilding_check'),
            (self.include_images, 'include_images'),
            (self.img_freq_combo, 'img_freq_combo'),
            (self.img_interval_spin, 'img_interval_spin'),
            (self.color_combo, 'color_combo'),
            (self.style_edit, 'style_edit'),
            (self.text_provider_combo, 'text_provider_combo'),
            (self.img_provider_combo, 'img_provider_combo'),
            (self.vertex_ai_check, 'vertex_ai_check'),
            (self.generate_btn, 'generate_btn'),
        ]:
            if w is not None:
                w.setObjectName(name)

    def _author_art_hint(self) -> str:
        """Visual-style hint for illustrations, derived from the chosen author voice.

        Falls back to a generic 'evocative of <author>' description so every
        author (not just the curated ones) gets a coherent art direction.
        """
        author_name = self.settings.get('author_voice', '')
        genre = self.settings.get('genre', '')
        av = get_author_voice(author_name, genre)
        if av and getattr(av, 'visual_style', ''):
            return av.visual_style
        if av and getattr(av, 'name', ''):
            return f"art style evocative of {av.name}'s illustrated books"
        return ""

    def _llm_text(self, prompt: str, system: str = "") -> str:
        """Run a text prompt through the configured text provider (or free fallback)."""
        router = getattr(self, 'text_router', None)
        if router is not None:
            try:
                messages = []
                if system:
                    messages.append({'role': 'system', 'content': system})
                messages.append({'role': 'user', 'content': prompt})
                res, _ = router.complete(messages)
                if res is not None and getattr(res, 'text', ''):
                    return res.text
            except Exception:
                pass
        # Fallback: Pollinations anonymous text endpoint (no key).
        try:
            import urllib.parse, requests
            url = "https://text.pollinations.ai/" + urllib.parse.quote(prompt[:2000])
            r = requests.get(url, timeout=90)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        return ""

    def _on_analyze_author_clicked(self):
        name = self.author_search.text().strip()
        if not name:
            QMessageBox.information(self, "Analyze Author",
                                    "Type an author's name to research.")
            return
        self.analyze_author_btn.setEnabled(False)
        self.status_label.setText(f"Researching author: {name}...")
        worker = AuthorResearchWorker(name, self._llm_text)
        worker.signals.finished.connect(
            lambda av: self._on_author_researched(name, av))
        worker.signals.error.connect(
            lambda msg: self._on_author_research_error(msg))
        self.thread_pool.start(worker)

    def _on_author_researched(self, name: str, av):
        self.analyze_author_btn.setEnabled(True)
        self.status_label.setText("Ready")
        if av is None or not getattr(av, 'style', ''):
            QMessageBox.warning(self, "Analyze Author",
                               f"Could not build a voice card for '{name}'.")
            return
        self._author_voice_cache[name] = av
        self.author_combo.blockSignals(True)
        if self.author_combo.findText(name) == -1:
            self.author_combo.addItem(name)
            idx = self.author_combo.count() - 1
            tooltip = f"{av.style}\n\nAvoid: {av.donts}"
            self.author_combo.setItemData(idx, tooltip, Qt.ToolTipRole)
        self.author_combo.blockSignals(False)
        self.author_combo.setCurrentText(name)
        QMessageBox.information(
            self, "Author Analyzed",
            f"Added voice card for '{name}'.\n\nStyle: {av.style[:160]}")

    def _on_author_research_error(self, msg: str):
        self.analyze_author_btn.setEnabled(True)
        self.status_label.setText("Ready")
        QMessageBox.warning(self, "Analyze Author",
                            f"Author research failed: {msg}")

    def _install_help(self):
        """Create the cursor-following hover help box and wire the idle timer."""
        self.help_box = QFrame(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.help_box.setFrameShape(QFrame.StyledPanel)
        self.help_box.setStyleSheet(
            "QFrame{background:#fffbe6;border:1px solid #d4b106;"
            "border-radius:6px;padding:6px;} QLabel{background:transparent;}")
        hb_layout = QVBoxLayout(self.help_box)
        hb_layout.setContentsMargins(8, 6, 8, 6)
        hb_layout.setSpacing(2)
        self.help_title = QLabel('')
        self.help_title.setStyleSheet("font-weight:bold;color:#5b4b00;")
        self.help_desc = QLabel('')
        self.help_desc.setWordWrap(True)
        self.help_desc.setMaximumWidth(320)
        hb_layout.addWidget(self.help_title)
        hb_layout.addWidget(self.help_desc)
        self.help_box.hide()

        self._hover_key = None
        self._hover_pos = None
        self._hover_timer = QTimer()
        self._hover_timer.setSingleShot(True)
        self._hover_timer.timeout.connect(self._show_help)
        self._hide_timer = QTimer()
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_help)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        t = event.type()
        if t in (QEvent.HoverMove, QEvent.Enter, QEvent.Leave):
            key = self._help_key_for(obj)
            if key is None:
                if self._hover_key is not None:
                    self._hover_key = None
                    self._hover_timer.stop()
                    self._hide_timer.start(600)
                return False
            # Over a help target
            self._hide_timer.stop()
            self._hover_key = key
            self._hover_pos = QCursor.pos()
            self.help_box.hide()
            self._hover_timer.start(2000)
            return False
        return super().eventFilter(obj, event)

    def _help_key_for(self, obj) -> Optional[Tuple[str, str]]:
        """Return (label, description) for a widget, or None if not a help target."""
        if obj is self.author_combo:
            name = self.author_combo.currentText()
            av = self._author_voice_cache.get(name)
            if av is not None:
                desc = f"{av.style}\nAvoid: {av.donts}"
            else:
                desc = "Clean modern prose, lean description, clear action."
            return ("Author Voice", f"{name}: {desc}")
        if obj is self.audience_combo:
            aud = self.audience_combo.currentText()
            return ("Audience", _AUDIENCE_DESCRIPTIONS.get(aud, aud))
        name = obj.objectName() if hasattr(obj, 'objectName') else ''
        entry = _HOVER_DESCRIPTIONS.get(name)
        if entry:
            return (entry[0], entry[1])
        return None

    def _show_help(self):
        if self._hover_key is None or self._hover_pos is None:
            return
        label, desc = self._hover_key
        self.help_title.setText(label)
        self.help_desc.setText(desc)
        self.help_box.adjustSize()
        pos = self._hover_pos + QPoint(16, 16)
        screen = QApplication.primaryScreen().availableGeometry()
        if pos.x() + self.help_box.width() > screen.right():
            pos.setX(self._hover_pos.x() - self.help_box.width() - 16)
        if pos.y() + self.help_box.height() > screen.bottom():
            pos.setY(self._hover_pos.y() - self.help_box.height() - 16)
        self.help_box.move(pos)
        self.help_box.show()

    def _hide_help(self):
        self.help_box.hide()
        self._hover_key = None

    def _build_api_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        # --- Text Providers ---
        text_group = QGroupBox('Text Provider — API Keys & Models')
        tg_layout = QVBoxLayout(text_group)

        text_form = QFormLayout()
        self.text_provider_combo = QComboBox()
        self.text_provider_combo.addItems([
            'Pollinations (Free)',
            'OpenRouter',
            'NVIDIA NIM',
            'HuggingFace',
            'Google (Gemini)',
            'Groq',
        ])
        self.text_provider_combo.currentTextChanged.connect(self._on_text_provider_changed)
        text_form.addRow('Provider:', self.text_provider_combo)

        self.text_api_key = QLineEdit()
        self.text_api_key.setEchoMode(QLineEdit.Password)
        self.text_api_key.setPlaceholderText('Enter API key (not needed for free providers)')
        text_form.addRow('API Key:', self.text_api_key)

        self.text_model_combo = QComboBox()
        self.text_model_combo.setMinimumWidth(300)
        text_form.addRow('Model:', self.text_model_combo)

        tg_layout.addLayout(text_form)

        text_btn_row = QHBoxLayout()
        self.text_fetch_btn = QPushButton('Fetch Models')
        self.text_fetch_btn.clicked.connect(self._fetch_text_models)
        self.text_probe_btn = QPushButton('Test Connection')
        self.text_probe_btn.clicked.connect(self._probe_text_one)
        text_btn_row.addWidget(self.text_fetch_btn)
        text_btn_row.addWidget(self.text_probe_btn)
        text_btn_row.addStretch()
        tg_layout.addLayout(text_btn_row)

        self.text_status = QLabel('Select a provider and click Test Connection')
        self.text_status.setWordWrap(True)
        tg_layout.addWidget(self.text_status)

        inner_layout.addWidget(text_group)

        # --- Image Providers ---
        img_group = QGroupBox('Image Provider — API Keys & Models')
        ig_layout = QVBoxLayout(img_group)

        img_form = QFormLayout()
        self.img_provider_combo = QComboBox()
        self.img_provider_combo.addItems([
            'Pollinations (Free)',
            'Google Nano Banana',
            'Stable Horde',
            'HuggingFace Space',
        ])
        self.img_provider_combo.currentTextChanged.connect(self._on_img_provider_changed)
        img_form.addRow('Provider:', self.img_provider_combo)

        self.img_api_key = QLineEdit()
        self.img_api_key.setEchoMode(QLineEdit.Password)
        self.img_api_key.setPlaceholderText('Enter API key (not needed for Vertex AI)')
        img_form.addRow('API Key:', self.img_api_key)

        self.vertex_ai_check = QCheckBox('Use Vertex AI (uses $300 Cloud credits — cheapest)')
        self.vertex_ai_check.setChecked(True)
        self.vertex_ai_check.stateChanged.connect(self._on_vertex_ai_toggled)
        img_form.addRow('', self.vertex_ai_check)

        self.vertex_project_id = QLineEdit()
        self.vertex_project_id.setPlaceholderText('e.g. my-project-12345')
        img_form.addRow('GCP Project ID:', self.vertex_project_id)

        self.vertex_location = QComboBox()
        self.vertex_location.addItems([
            'us-central1', 'us-east4', 'us-west1', 'us-west4',
            'europe-west1', 'europe-west4', 'asia-east1', 'asia-northeast1',
        ])
        img_form.addRow('Region:', self.vertex_location)

        self.img_model_combo = QComboBox()
        self.img_model_combo.setMinimumWidth(300)
        img_form.addRow('Model:', self.img_model_combo)

        ig_layout.addLayout(img_form)

        img_btn_row = QHBoxLayout()
        self.img_fetch_btn = QPushButton('Fetch Models')
        self.img_fetch_btn.clicked.connect(self._fetch_image_models)
        self.img_probe_btn = QPushButton('Test Connection')
        self.img_probe_btn.clicked.connect(self._probe_image_one)
        img_btn_row.addWidget(self.img_fetch_btn)
        img_btn_row.addWidget(self.img_probe_btn)
        img_btn_row.addStretch()
        ig_layout.addLayout(img_btn_row)

        self.img_status = QLabel('Select a provider and click Test Connection')
        self.img_status.setWordWrap(True)
        ig_layout.addWidget(self.img_status)

        inner_layout.addWidget(img_group)

        # --- Free Models Reference ---
        ref_group = QGroupBox('Free Models Quick Reference')
        rg_layout = QVBoxLayout(ref_group)
        self.free_models_browser = QTextBrowser()
        self.free_models_browser.setMaximumHeight(200)
        self._update_free_models_ref()
        rg_layout.addWidget(self.free_models_browser)
        inner_layout.addWidget(ref_group)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.tabs.addTab(tab, 'API Keys & Models')

    def _on_text_provider_changed(self, provider_text):
        name = provider_text
        if 'Pollinations' in name:
            key_name = 'Pollinations'
        elif 'OpenRouter' in name:
            key_name = 'OpenRouter'
        elif 'NVIDIA' in name:
            key_name = 'NVIDIA'
        elif 'HuggingFace' in name:
            key_name = 'HuggingFace'
        elif 'Google' in name:
            key_name = 'Google'
        elif 'Groq' in name:
            key_name = 'Groq'
        else:
            key_name = 'Pollinations'
        self._populate_text_models(key_name)

    def _on_img_provider_changed(self, provider_text):
        name = provider_text
        is_google = 'Google' in name
        self.vertex_ai_check.setVisible(is_google)
        self.vertex_project_id.setVisible(is_google)
        self.vertex_location.setVisible(is_google)
        if 'Pollinations' in name:
            key_name = 'Pollinations'
        elif is_google:
            key_name = 'Google Nano Banana'
        elif 'Stable' in name:
            key_name = 'Stable Horde'
        elif 'HuggingFace' in name:
            key_name = 'HFSpace'
        else:
            key_name = 'Pollinations'
        self._populate_image_models(key_name)

    def _on_vertex_ai_toggled(self, state):
        self.img_api_key.setEnabled(not state)

    def _populate_text_models(self, provider_name):
        api_key = self.text_api_key.text().strip()
        models = fetch_for(provider_name, api_key)
        self.text_model_combo.clear()
        for m in models:
            self.text_model_combo.addItem(m.display(), m.id)
        if models:
            self.text_model_combo.setCurrentIndex(0)

    def _populate_image_models(self, provider_name):
        self.img_model_combo.clear()
        if provider_name == 'Pollinations':
            self.img_model_combo.addItem('flux (default)', 'flux')
            self.img_model_combo.addItem('turbo', 'turbo')
        elif provider_name == 'Google Nano Banana':
            for model_id, label in NANO_BANANA_MODELS.items():
                self.img_model_combo.addItem(label, model_id)
        elif provider_name == 'Stable Horde':
            self.img_model_combo.addItem('Deliberate', 'Deliberate')
            self.img_model_combo.addItem('Stable Diffusion XL', 'SDXL 1.0')
            self.img_model_combo.addItem('Stable Diffusion', 'stable_diffusion')
        elif provider_name == 'HFSpace':
            self.img_model_combo.addItem('FLUX.1-schnell', 'black-forest-labs/FLUX.1-schnell')

    def _fetch_text_models(self):
        name = self.text_provider_combo.currentText()
        if 'Pollinations' in name:
            key_name = 'Pollinations'
        elif 'OpenRouter' in name:
            key_name = 'OpenRouter'
        elif 'NVIDIA' in name:
            key_name = 'NVIDIA'
        elif 'HuggingFace' in name:
            key_name = 'HuggingFace'
        elif 'Google' in name:
            key_name = 'Google'
        elif 'Groq' in name:
            key_name = 'Groq'
        else:
            key_name = 'Pollinations'

        api_key = self.text_api_key.text().strip()
        self.text_status.setText(f'Fetching models for {key_name}...')
        QApplication.processEvents()
        models = fetch_for(key_name, api_key)
        self.text_model_combo.clear()
        for m in models:
            self.text_model_combo.addItem(m.display(), m.id)
        self.text_status.setText(f'Loaded {len(models)} models for {key_name}')

    def _fetch_image_models(self):
        name = self.img_provider_combo.currentText()
        if 'Pollinations' in name:
            key_name = 'Pollinations'
        elif 'Google' in name:
            key_name = 'Google Nano Banana'
        elif 'Stable' in name:
            key_name = 'Stable Horde'
        elif 'HuggingFace' in name:
            key_name = 'HFSpace'
        else:
            key_name = 'Pollinations'
        self._populate_image_models(key_name)
        self.img_status.setText(f'Loaded image models for {key_name}')

    def _update_free_models_ref(self):
        html = '<b>Pollinations (no key):</b> flux, turbo<br>'
        html += '<b>OpenRouter (free tier):</b> models ending in :free<br>'
        html += '<b>NVIDIA NIM (free preview):</b> llama-3.1-8b-instruct, gemma-2-2b-it<br>'
        html += '<b>HuggingFace (free):</b> Llama 3 8B, Mistral 7B, Gemma 1.1 7B<br>'
        html += '<b>Google Gemini (free tier):</b> gemini-2.0-flash, gemini-2.0-flash-lite<br>'
        html += '<b>Groq (free tier):</b> llama-3.1-8b-instant, gemma2-9b-it<br>'
        html += '<b>Image — Pollinations (no key):</b> flux, turbo<br>'
        html += '<b>Image — Google Nano Banana (Vertex AI):</b> gemini-2.5-flash-image ($0.039/img with $300 credits)'
        self.free_models_browser.setHtml(html)

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)

        book_group = QGroupBox('Book Settings')
        bg_layout = QFormLayout(book_group)
        self.theme_edit = QLineEdit()
        self.theme_edit.setPlaceholderText('e.g., friendship, courage, redemption')
        bg_layout.addRow('Theme:', self.theme_edit)
        self.setting_edit = QLineEdit()
        self.setting_edit.setPlaceholderText('e.g., a magical forest kingdom')
        bg_layout.addRow('Setting:', self.setting_edit)
        self.genre_list = QListWidget()
        self.genre_list.setObjectName('genre_list')
        self.genre_list.setFixedHeight(96)
        for _g in GENRES:
            _it = QListWidgetItem(_g)
            _it.setFlags(_it.flags() | Qt.ItemIsUserCheckable)
            _it.setCheckState(Qt.Checked if _g == "Fantasy" else Qt.Unchecked)
            self.genre_list.addItem(_it)
        self.genre_list.itemChanged.connect(
            lambda *_: self._populate_authors_for_genre(self.selected_genres(), self.audience_combo.currentText()))
        bg_layout.addRow('Genre(s):', self.genre_list)
        self.audience_combo = QComboBox()
        self.audience_combo.addItems(AUDIENCES)
        bg_layout.addRow('Audience:', self.audience_combo)
        self.author_combo = QComboBox()
        self.author_combo.setObjectName('author_combo')
        self._author_voice_cache: Dict[str, 'AuthorVoice'] = {}
        self._populate_authors_for_genre(self.selected_genres(),
                                         self.audience_combo.currentText())
        bg_layout.addRow('Author Voice:', self.author_combo)
        self.audience_combo.currentTextChanged.connect(
            lambda a: self._populate_authors_for_genre(self.selected_genres(), a))

        # --- Research any author online -> build a runtime voice card ---
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.author_search = QLineEdit()
        self.author_search.setObjectName('author_search')
        self.author_search.setPlaceholderText('Research any author (e.g. Octavia Butler, Mo Willems)')
        self.analyze_author_btn = QPushButton('Analyze Author')
        self.analyze_author_btn.setObjectName('analyze_author_btn')
        self.analyze_author_btn.clicked.connect(self._on_analyze_author_clicked)
        search_row.addWidget(self.author_search)
        search_row.addWidget(self.analyze_author_btn)
        bg_layout.addRow('Or research:', search_row)

        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(1, 1000)
        self.pages_spin.setValue(20)
        bg_layout.addRow('Total Pages:', self.pages_spin)

        # NEW: Review preference
        self.review_preference_combo = QComboBox()
        self.review_preference_combo.addItems(['AI (automatic)', 'Human (manual)'])
        bg_layout.addRow('Chapter Review:', self.review_preference_combo)

        # NEW: Worldbuilding toggle
        self.worldbuilding_check = QCheckBox('Enable Worldbuilding Agent')
        self.worldbuilding_check.setChecked(False)
        bg_layout.addRow('', self.worldbuilding_check)

        inner_layout.addWidget(book_group)

        img_settings = QGroupBox('Image Settings')
        isg_layout = QFormLayout(img_settings)
        self.include_images = QCheckBox('Generate Images')
        isg_layout.addRow(self.include_images)
        self.img_freq_combo = QComboBox()
        self.img_freq_combo.addItems(['none', 'every_chapter', 'every_page', 'every_n'])
        isg_layout.addRow('Frequency:', self.img_freq_combo)
        self.img_interval_spin = QSpinBox()
        self.img_interval_spin.setRange(1, 20)
        self.img_interval_spin.setValue(5)
        isg_layout.addRow('Every N pages:', self.img_interval_spin)
        self.color_combo = QComboBox()
        self.color_combo.addItems(['color', 'bw'])
        isg_layout.addRow('Style:', self.color_combo)
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText('e.g., watercolor, digital art, ink sketch')
        isg_layout.addRow('Art Style:', self.style_edit)
        self.include_images.stateChanged.connect(self._on_images_toggled)
        inner_layout.addWidget(img_settings)

        config_layout = QHBoxLayout()
        self.save_config_btn = QPushButton('Save Config')
        self.save_config_btn.clicked.connect(self._save_full_config)
        self.load_config_btn = QPushButton('Load Config')
        self.load_config_btn.clicked.connect(self._load_config)
        config_layout.addWidget(self.save_config_btn)
        config_layout.addWidget(self.load_config_btn)
        inner_layout.addLayout(config_layout)

        inner_layout.addStretch()
        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.tabs.addTab(tab, 'Book Settings')

    def _on_images_toggled(self, state):
        enabled = (state == Qt.Checked)
        self.img_freq_combo.setEnabled(enabled)
        self.img_interval_spin.setEnabled(enabled)
        self.color_combo.setEnabled(enabled)
        self.style_edit.setEnabled(enabled)

    def _build_outline_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderLabels(['Chapter / Beat', 'Details'])
        self.outline_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.outline_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.outline_tree.setEditTriggers(QTreeWidget.DoubleClicked | QTreeWidget.EditKeyPressed)
        self.outline_tree.itemChanged.connect(self._on_outline_item_changed)
        layout.addWidget(self.outline_tree)
        btn_layout = QHBoxLayout()
        self.regen_outline_btn = QPushButton('Regenerate Outline')
        self.regen_outline_btn.clicked.connect(self._regenerate_outline)
        self.export_json_btn = QPushButton('Export Book JSON')
        self.export_json_btn.clicked.connect(self._export_book_json)
        btn_layout.addWidget(self.regen_outline_btn)
        btn_layout.addWidget(self.export_json_btn)
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, 'Outline')

    def _build_pages_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.pages_list = QListWidget()
        self.pages_list.currentRowChanged.connect(self._on_page_selected)
        left_layout.addWidget(QLabel('Pages'))
        left_layout.addWidget(self.pages_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.page_text = QTextBrowser()
        self.page_text.setReadOnly(True)
        right_layout.addWidget(QLabel('Page Content'))
        right_layout.addWidget(self.page_text)
        self.regen_page_btn = QPushButton('Regenerate This Page')
        self.regen_page_btn.clicked.connect(self._regenerate_current_page)
        right_layout.addWidget(self.regen_page_btn)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 800])
        layout.addWidget(splitter)
        self.tabs.addTab(tab, 'Pages')

    def _build_characters_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.char_tree = QTreeWidget()
        self.char_tree.setHeaderLabels(['Characters', 'Role', 'Traits', 'Status'])
        self.char_tree.header().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(QLabel('Character Registry'))
        layout.addWidget(self.char_tree)

        btn_layout = QHBoxLayout()
        self.refresh_registry_btn = QPushButton('Refresh from Book')
        self.refresh_registry_btn.clicked.connect(self._refresh_registry)
        self.add_char_btn = QPushButton('Add Character')
        self.add_char_btn.clicked.connect(self._add_character)
        self.edit_char_btn = QPushButton('Edit Selected')
        self.edit_char_btn.clicked.connect(self._edit_character)
        self.delete_char_btn = QPushButton('Delete Selected')
        self.delete_char_btn.clicked.connect(self._delete_character)
        btn_layout.addWidget(self.refresh_registry_btn)
        btn_layout.addWidget(self.add_char_btn)
        btn_layout.addWidget(self.edit_char_btn)
        btn_layout.addWidget(self.delete_char_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, 'Characters/Registry')

    def _build_worldbuilding_tab(self):
        """NEW: Worldbuilding tab for setting, magic systems, geography, etc."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_layout = QFormLayout(inner)

        self.wb_geography = QPlainTextEdit()
        self.wb_geography.setPlaceholderText('Continents, climate, major landmarks...')
        self.wb_geography.setMaximumHeight(80)
        inner_layout.addRow('Geography:', self.wb_geography)

        self.wb_culture = QPlainTextEdit()
        self.wb_culture.setPlaceholderText('Customs, social norms, festivals, taboos...')
        self.wb_culture.setMaximumHeight(80)
        inner_layout.addRow('Culture & Society:', self.wb_culture)

        self.wb_history = QPlainTextEdit()
        self.wb_history.setPlaceholderText('Major historical events, wars, eras...')
        self.wb_history.setMaximumHeight(80)
        inner_layout.addRow('History:', self.wb_history)

        self.wb_rules = QPlainTextEdit()
        self.wb_rules.setPlaceholderText('Laws, government, magic rules, taboos...')
        self.wb_rules.setMaximumHeight(80)
        inner_layout.addRow('Rules & Laws:', self.wb_rules)

        self.wb_tech = QPlainTextEdit()
        self.wb_tech.setPlaceholderText('Technology level, key inventions...')
        self.wb_tech.setMaximumHeight(80)
        inner_layout.addRow('Technology Level:', self.wb_tech)

        self.wb_magic = QPlainTextEdit()
        self.wb_magic.setPlaceholderText('Magic system rules, costs, limitations...')
        self.wb_magic.setMaximumHeight(80)
        inner_layout.addRow('Magic System:', self.wb_magic)

        self.wb_locations = QPlainTextEdit()
        self.wb_locations.setPlaceholderText('Key cities, ruins, dungeons, ports...')
        self.wb_locations.setMaximumHeight(80)
        inner_layout.addRow('Key Locations:', self.wb_locations)

        self.wb_orgs = QPlainTextEdit()
        self.wb_orgs.setPlaceholderText('Guilds, kingdoms, cults, companies...')
        self.wb_orgs.setMaximumHeight(80)
        inner_layout.addRow('Organizations:', self.wb_orgs)

        self.wb_flora = QPlainTextEdit()
        self.wb_flora.setPlaceholderText('Unique plants, animals, monsters...')
        self.wb_flora.setMaximumHeight(80)
        inner_layout.addRow('Flora & Fauna:', self.wb_flora)

        self.wb_languages = QPlainTextEdit()
        self.wb_languages.setPlaceholderText('Constructed languages, dialects...')
        self.wb_languages.setMaximumHeight(60)
        inner_layout.addRow('Languages:', self.wb_languages)

        self.wb_religions = QPlainTextEdit()
        self.wb_religions.setPlaceholderText('Gods, beliefs, rituals, holy sites...')
        self.wb_religions.setMaximumHeight(80)
        inner_layout.addRow('Religions & Beliefs:', self.wb_religions)

        self.wb_economy = QPlainTextEdit()
        self.wb_economy.setPlaceholderText('Currency, trade routes, resources...')
        self.wb_economy.setMaximumHeight(60)
        inner_layout.addRow('Economy:', self.wb_economy)

        self.wb_conflicts = QPlainTextEdit()
        self.wb_conflicts.setPlaceholderText('Ongoing wars, tensions, rivalries...')
        self.wb_conflicts.setMaximumHeight(80)
        inner_layout.addRow('Conflicts:', self.wb_conflicts)

        wb_btn_row = QHBoxLayout()
        self.generate_wb_btn = QPushButton('Generate Worldbuilding')
        self.generate_wb_btn.clicked.connect(self._generate_worldbuilding)
        self.save_wb_btn = QPushButton('Save Worldbuilding')
        self.save_wb_btn.clicked.connect(self._save_worldbuilding)
        wb_btn_row.addWidget(self.generate_wb_btn)
        wb_btn_row.addWidget(self.save_wb_btn)
        wb_btn_row.addStretch()
        inner_layout.addRow('', wb_btn_row)

        scroll.setWidget(inner)
        layout.addWidget(scroll)
        self.tabs.addTab(tab, 'Worldbuilding')

    def _build_images_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.images_grid = QWidget()
        self.images_grid_layout = QVBoxLayout(self.images_grid)
        scroll.setWidget(self.images_grid)
        layout.addWidget(scroll)
        btn_layout = QHBoxLayout()
        self.regen_cover_btn = QPushButton('Regenerate Cover')
        self.regen_cover_btn.clicked.connect(self._regenerate_cover)
        self.regen_all_images_btn = QPushButton('Regenerate All Images')
        self.regen_all_images_btn.clicked.connect(self._regenerate_all_images)
        btn_layout.addWidget(self.regen_cover_btn)
        btn_layout.addWidget(self.regen_all_images_btn)
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, 'Images')

    def _build_expert_config_tab(self):
        """NEW: Expert Config tab for YAML/JSON project configuration."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel('LibriScribe Expert Configuration — Load/save full project configs (YAML/JSON).')
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.load_expert_btn = QPushButton('Load Expert Config')
        self.load_expert_btn.clicked.connect(self._load_expert_config)
        self.save_expert_btn = QPushButton('Save Expert Config')
        self.save_expert_btn.clicked.connect(self._save_expert_config)
        self.export_yaml_btn = QPushButton('Export as YAML')
        self.export_yaml_btn.clicked.connect(self._export_yaml_config)
        btn_row.addWidget(self.load_expert_btn)
        btn_row.addWidget(self.save_expert_btn)
        btn_row.addWidget(self.export_yaml_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.expert_config_editor = QPlainTextEdit()
        self.expert_config_editor.setPlaceholderText('Expert configuration YAML will appear here...')
        font = QFont('Consolas', 10)
        self.expert_config_editor.setFont(font)
        layout.addWidget(self.expert_config_editor)

        self.tabs.addTab(tab, 'Expert Config')

    def _build_cost_tracker_tab(self):
        """NEW: Cost Tracker tab showing LLM usage from llm_usage.jsonl."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel('LLM Usage & Cost Tracking — Auto-logged from libriscribe/llm_usage.jsonl')
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.refresh_cost_btn = QPushButton('Refresh')
        self.refresh_cost_btn.clicked.connect(self._refresh_cost_tracker)
        self.clear_cost_btn = QPushButton('Clear Log')
        self.clear_cost_btn.clicked.connect(self._clear_cost_log)
        btn_row.addWidget(self.refresh_cost_btn)
        btn_row.addWidget(self.clear_cost_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.cost_table = QTableWidget()
        self.cost_table.setColumnCount(6)
        self.cost_table.setHorizontalHeaderLabels(['Timestamp', 'Provider', 'Model', 'Input Tokens', 'Output Tokens', 'Cost (USD)'])
        self.cost_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.cost_table)

        self.total_cost_label = QLabel('Total Cost: $0.0000')
        self.total_cost_label.setFont(QFont('Arial', 12, QFont.Bold))
        layout.addWidget(self.total_cost_label)

        self.tabs.addTab(tab, 'Cost Tracker')

    def _build_prompts_tab(self):
        """NEW: Prompts tab for editing YAML prompt templates."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel('Customize agent prompt templates. Edit and save to libriscribe/prompts/templates/')
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self.prompt_agent_combo = QComboBox()
        self.prompt_agent_combo.addItems([
            'concept_generator', 'outliner', 'character_generator',
            'worldbuilding', 'chapter_writer', 'content_reviewer',
            'editor', 'style_editor', 'fact_checker', 'plagiarism_checker',
            'researcher', 'formatting', 'scene_generator', 'scene_outliner'
        ])
        self.prompt_agent_combo.currentTextChanged.connect(self._load_prompt_template)
        btn_row.addWidget(QLabel('Agent:'))
        btn_row.addWidget(self.prompt_agent_combo)

        self.reload_prompt_btn = QPushButton('Reload')
        self.reload_prompt_btn.clicked.connect(self._load_prompt_template)
        self.save_prompt_btn = QPushButton('Save Template')
        self.save_prompt_btn.clicked.connect(self._save_prompt_template)
        btn_row.addWidget(self.reload_prompt_btn)
        btn_row.addWidget(self.save_prompt_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.prompt_editor = QPlainTextEdit()
        self.prompt_editor.setPlaceholderText('YAML prompt template...')
        font = QFont('Consolas', 10)
        self.prompt_editor.setFont(font)
        layout.addWidget(self.prompt_editor)

        self.tabs.addTab(tab, 'Prompts')

    def _build_finished_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        header = QLabel('Finished Book')
        header.setFont(QFont('Arial', 16, QFont.Bold))
        layout.addWidget(header)

        self.finished_info = QLabel('No book generated yet.')
        self.finished_info.setWordWrap(True)
        layout.addWidget(self.finished_info)

        self.finished_book_viewer = QTextBrowser()
        self.finished_book_viewer.setOpenExternalLinks(True)
        layout.addWidget(self.finished_book_viewer)

        btn_row = QHBoxLayout()
        self.open_folder_btn = QPushButton('Open Book Folder')
        self.open_folder_btn.clicked.connect(self._open_book_folder)
        self.open_folder_btn.setEnabled(False)
        btn_row.addWidget(self.open_folder_btn)

        self.open_images_btn = QPushButton('Open Images Folder')
        self.open_images_btn.clicked.connect(self._open_images_folder)
        btn_row.addWidget(self.open_images_btn)

        self.load_project_btn = QPushButton('Load Project')
        self.load_project_btn.clicked.connect(self._restore_project)
        btn_row.addWidget(self.load_project_btn)

        self.export_epub_btn = QPushButton('Export EPUB')
        self.export_epub_btn.clicked.connect(self._export_epub)
        self.export_epub_btn.setEnabled(False)
        btn_row.addWidget(self.export_epub_btn)

        self.export_pdf_btn = QPushButton('Export PDF')
        self.export_pdf_btn.clicked.connect(self._export_pdf)
        self.export_pdf_btn.setEnabled(False)
        btn_row.addWidget(self.export_pdf_btn)

        self.export_html_btn = QPushButton('Export HTML')
        self.export_html_btn.clicked.connect(self._export_html)
        self.export_html_btn.setEnabled(False)
        btn_row.addWidget(self.export_html_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.tabs.addTab(tab, 'Finished Book')

    def _open_book_folder(self):
        if not self.current_book:
            return
        title = self.current_book.get('metadata', {}).get('title', 'untitled')
        out_dir = os.path.join('Generated_Books', title.replace(' ', '_'))
        os.makedirs(out_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(out_dir)))

    def _open_images_folder(self):
        img_dir = os.path.join('Generated_Books', 'images')
        os.makedirs(img_dir, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(img_dir)))

    def _populate_finished_tab(self, book: Dict):
        meta = book.get('metadata', {})
        title = meta.get('title', 'Untitled')
        out_dir = os.path.join('Generated_Books', title.replace(' ', '_'))
        pages = book.get('pages', [])

        self.finished_info.setText(
            f'<b>{title}</b> | {len(pages)} pages | '
            f'Saved to: {os.path.abspath(out_dir)}'
        )

        html = f'<h2>{title}</h2>'
        if meta.get('genre'):
            html += f'<p><i>Genre: {meta["genre"]} | Audience: {meta.get("audience", "")}</i></p>'
        if meta.get('blurb'):
            html += f'<p>{meta["blurb"]}</p>'
        html += '<hr>'
        for i, page in enumerate(pages):
            ch = page.get('chapter', '')
            if ch:
                html += f'<h3>{ch}</h3>'
            html += f'<p><b>Page {i+1}</b></p>'
            html += f'<p>{page.get("text", "")}</p>'
            img = page.get('img_url', '')
            if img and os.path.exists(img):
                abs_path = os.path.abspath(img).replace('\\', '/')
                html += f'<p><img src="file:///{abs_path}" width="300"></p>'
            html += '<br>'

        self.finished_book_viewer.setHtml(html)
        self.open_folder_btn.setEnabled(True)
        self.export_epub_btn.setEnabled(True)
        self.export_pdf_btn.setEnabled(True)
        self.export_html_btn.setEnabled(True)

    def _export_epub(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export EPUB', 'book.epub', 'EPUB Files (*.epub)')
        if path:
            if save_book_to_epub(self.current_book, path):
                QMessageBox.information(self, 'Exported', f'EPUB saved to {path}')
            else:
                QMessageBox.critical(self, 'Export Error', 'EPUB export failed. Check that ebooklib is installed.')

    def _export_pdf(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export PDF', 'book.pdf', 'PDF Files (*.pdf)')
        if path:
            if save_book_to_pdf(self.current_book, path):
                QMessageBox.information(self, 'Exported', f'PDF saved to {path}')
            else:
                QMessageBox.critical(self, 'Export Error', 'PDF export failed. Check that fpdf2 is installed.')

    def _export_html(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export HTML', 'book.html', 'HTML Files (*.html)')
        if path:
            if save_book_to_html(self.current_book, path):
                QMessageBox.information(self, 'Exported', f'HTML saved to {path}')
            else:
                QMessageBox.critical(self, 'Export Error', 'HTML export failed.')

    def _probe_all(self):
        self._probe_text_one()
        self._probe_image_one()

    def _probe_text_one(self):
        provider_name = self.text_provider_combo.currentText()
        api_key = self.text_api_key.text().strip()
        model_id = self.text_model_combo.currentData() or ''

        if provider_name == 'Pollinations (Free)':
            configs = [ProviderConfig(name='Pollinations', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif provider_name == 'OpenRouter' and api_key:
            configs = [ProviderConfig(name='OpenRouter', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif provider_name == 'NVIDIA NIM' and api_key:
            configs = [ProviderConfig(name='NVIDIA', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif provider_name == 'HuggingFace' and api_key:
            configs = [ProviderConfig(name='HuggingFace', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif provider_name == 'Google (Gemini)' and api_key:
            configs = [ProviderConfig(name='Google', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif provider_name == 'Groq' and api_key:
            configs = [ProviderConfig(name='Groq', api_key=api_key, model=model_id, enabled=True, priority=0)]
        else:
            configs = [ProviderConfig(name='Pollinations', api_key='', enabled=True, priority=0)]

        self.text_router = Router(configs=configs)

        self.text_status.setText(f'Testing {provider_name}...')
        QApplication.processEvents()
        try:
            res, used = self.text_router.complete([{'role': 'user', 'content': 'Say hello in 5 words'}], max_tokens=20)
            if res.ok:
                self.text_status.setText(f'OK: {used} — "{res.text[:50]}"')
            else:
                self.text_status.setText(f'FAILED: {res.error}')
        except Exception as e:
            self.text_status.setText(f'ERROR: {e}')
        self.status_label.setText(self.text_status.text())

    def _probe_image_one(self):
        provider_name = self.img_provider_combo.currentText()
        api_key = self.img_api_key.text().strip()
        model_id = self.img_model_combo.currentData() or ''
        use_vertex = self.vertex_ai_check.isChecked()
        project_id = self.vertex_project_id.text().strip()
        location = self.vertex_location.currentText()

        if 'Pollinations' in provider_name:
            configs = [ImageProviderConfig(name='Pollinations', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif 'Google' in provider_name:
            configs = [ImageProviderConfig(
                name='Google Nano Banana', api_key=api_key, model=model_id,
                enabled=True, priority=0,
                use_vertex_ai=use_vertex, vertex_project_id=project_id,
                vertex_location=location)]
        elif 'Stable' in provider_name and api_key:
            configs = [ImageProviderConfig(name='Stable Horde', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif 'HuggingFace' in provider_name:
            configs = [ImageProviderConfig(name='HFSpace', api_key=api_key, model=model_id, enabled=True, priority=0)]
        else:
            configs = [ImageProviderConfig(name='Pollinations', api_key='', enabled=True, priority=0)]

        configs = _drop_pollinations_when_banana_active(
            configs,
            banana_enabled=('Google' in provider_name),
        )
        self.image_router = ImageRouter(configs=configs)

        self.img_status.setText(f'Testing {provider_name}...')
        QApplication.processEvents()
        try:
            res, used = self.image_router.generate('test image 10x10')
            if res.ok:
                self.img_status.setText(f'OK: {used} — saved to {res.path[:60]}')
            else:
                self.img_status.setText(f'FAILED: {res.error}')
        except Exception as e:
            self.img_status.setText(f'ERROR: {e}')
        self.status_label.setText(self.img_status.text())

    def _save_full_config(self):
        config = self._get_current_settings()
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        QMessageBox.information(self, 'Saved', f'Config saved to {CONFIG_FILE}')

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            self._apply_config(config)
            QMessageBox.information(self, 'Loaded', f'Config loaded from {CONFIG_FILE}')
        else:
            QMessageBox.warning(self, 'Not Found', f'{CONFIG_FILE} does not exist.')

    def selected_genres(self) -> str:
        """Return the checked genres as a comma-joined string (e.g. 'Graphic Novel, Fantasy')."""
        out = []
        for i in range(self.genre_list.count()):
            it = self.genre_list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.text())
        return ", ".join(out)

    def _set_genres(self, genre_str: str):
        """Check the list items that match a stored genre string (single or comma-joined)."""
        wanted = {g.strip().lower() for g in str(genre_str or "").split(",") if g.strip()}
        for i in range(self.genre_list.count()):
            it = self.genre_list.item(i)
            it.setCheckState(Qt.Checked if it.text().lower() in wanted else Qt.Unchecked)

    def _populate_authors_for_genre(self, genre: str, audience: str):
        """Rebuild the author voice dropdown.

        Every author voice (all genres + the Children's roster) is available
        regardless of the selected audience, so any voice can be paired with any
        audience. Caches the resolved AuthorVoice per name for tooltips/engine.
        """
        from PyQt5.QtCore import Qt
        self._author_voice_cache = {}
        current = self.author_combo.currentText()
        self.author_combo.blockSignals(True)
        self.author_combo.clear()
        self.author_combo.addItem('Default (Clean Prose)')
        self._author_voice_cache['Default (Clean Prose)'] = DEFAULT_PROSE

        seen = set()
        for bucket in AUTHORS_BY_GENRE.values():
            for av in bucket:
                if av.name in seen:
                    continue
                seen.add(av.name)
                self.author_combo.addItem(av.name)
                self._author_voice_cache[av.name] = av
                idx = self.author_combo.count() - 1
                tooltip = f"{av.style}\n\nAvoid: {av.donts}"
                self.author_combo.setItemData(idx, tooltip, Qt.ToolTipRole)

        # restore prior selection if still present, else default
        if current in self._author_voice_cache:
            self.author_combo.setCurrentText(current)
        else:
            self.author_combo.setCurrentText('Default (Clean Prose)')
        self.author_combo.blockSignals(False)

    def _get_current_settings(self) -> Dict:
        return {
            'theme': self.theme_edit.text(),
            'setting': self.setting_edit.text(),
            'genre': self.selected_genres(),
            'audience': self.audience_combo.currentText(),
            'author_voice': self.author_combo.currentText(),
            'num_pages': self.pages_spin.value(),
            'include_images': self.include_images.isChecked(),
            'image_freq': self.img_freq_combo.currentText(),
            'img_interval': self.img_interval_spin.value(),
            'color_style': self.color_combo.currentText(),
            'style_phrase': self.style_edit.text(),
            'text_provider': self.text_provider_combo.currentText(),
            'text_api_key': self.text_api_key.text(),
            'text_model': self.text_model_combo.currentData() or '',
            'image_provider': self.img_provider_combo.currentText(),
            'image_api_key': self.img_api_key.text(),
            'image_model': self.img_model_combo.currentData() or '',
            'use_vertex_ai': self.vertex_ai_check.isChecked(),
            'vertex_project_id': self.vertex_project_id.text(),
            'vertex_location': self.vertex_location.currentText(),
            'review_preference': self.review_preference_combo.currentText(),
            'worldbuilding_needed': self.worldbuilding_check.isChecked(),
        }

    def _apply_config(self, config: Dict):
        self.theme_edit.setText(config.get('theme', ''))
        self.setting_edit.setText(config.get('setting', ''))
        self._set_genres(config.get('genre', 'Fantasy'))
        self.audience_combo.setCurrentText(config.get('audience', 'Young Adult'))
        self._populate_authors_for_genre(self.selected_genres(),
                                         self.audience_combo.currentText())
        self.author_combo.setCurrentText(config.get('author_voice', 'Default (Clean Prose)'))
        self.pages_spin.setValue(config.get('num_pages', 20))
        self.include_images.setChecked(config.get('include_images', False))
        self.img_freq_combo.setCurrentText(config.get('image_freq', 'none'))
        self.img_interval_spin.setValue(config.get('img_interval', 5))
        self.color_combo.setCurrentText(config.get('color_style', 'color'))
        self.style_edit.setText(config.get('style_phrase', ''))
        self.review_preference_combo.setCurrentText(config.get('review_preference', 'AI (automatic)'))
        self.worldbuilding_check.setChecked(config.get('worldbuilding_needed', False))

        self.text_provider_combo.setCurrentText(config.get('text_provider', 'Pollinations (Free)'))
        self.text_api_key.setText(config.get('text_api_key', ''))
        self.img_provider_combo.setCurrentText(config.get('image_provider', 'Pollinations (Free)'))
        self.img_api_key.setText(config.get('image_api_key', ''))
        self.vertex_ai_check.setChecked(config.get('use_vertex_ai', True))
        self.vertex_project_id.setText(config.get('vertex_project_id', ''))
        loc = config.get('vertex_location', 'us-central1')
        idx = self.vertex_location.findText(loc)
        if idx >= 0:
            self.vertex_location.setCurrentIndex(idx)

        # Rebuild routers
        text_provider = config.get('text_provider', 'Pollinations (Free)')
        text_api_key = config.get('text_api_key', '')
        text_model = config.get('text_model', '')
        if text_provider == 'Pollinations (Free)':
            configs = [ProviderConfig(name='Pollinations', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        elif text_provider == 'OpenRouter' and text_api_key:
            configs = [ProviderConfig(name='OpenRouter', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        elif text_provider == 'NVIDIA NIM' and text_api_key:
            configs = [ProviderConfig(name='NVIDIA', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        elif text_provider == 'HuggingFace' and text_api_key:
            configs = [ProviderConfig(name='HuggingFace', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        elif text_provider == 'Google (Gemini)' and text_api_key:
            configs = [ProviderConfig(name='Google', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        elif text_provider == 'Groq' and text_api_key:
            configs = [ProviderConfig(name='Groq', api_key=text_api_key, model=text_model, enabled=True, priority=0)]
        else:
            configs = [ProviderConfig(name='Pollinations', api_key='', enabled=True, priority=0)]
        self.text_router = Router(configs=configs)

        image_provider = config.get('image_provider', 'Pollinations (Free)')
        image_api_key = config.get('image_api_key', '')
        image_model = config.get('image_model', '')
        use_vertex = config.get('use_vertex_ai', True)
        project_id = config.get('vertex_project_id', '')
        location = config.get('vertex_location', 'us-central1')

        if 'Pollinations' in image_provider:
            configs = [ImageProviderConfig(name='Pollinations', api_key=image_api_key, model=image_model, enabled=True, priority=0)]
        elif 'Google' in image_provider:
            configs = [ImageProviderConfig(
                name='Google Nano Banana', api_key=image_api_key, model=image_model,
                enabled=True, priority=0,
                use_vertex_ai=use_vertex, vertex_project_id=project_id,
                vertex_location=location)]
        elif 'Stable' in image_provider and image_api_key:
            configs = [ImageProviderConfig(name='Stable Horde', api_key=image_api_key, model=image_model, enabled=True, priority=0)]
        elif 'HuggingFace' in image_provider:
            configs = [ImageProviderConfig(name='HFSpace', api_key=image_api_key, model=image_model, enabled=True, priority=0)]
        else:
            configs = [ImageProviderConfig(name='Pollinations', api_key='', enabled=True, priority=0)]

        configs = _drop_pollinations_when_banana_active(
            configs,
            banana_enabled=('Google' in image_provider),
        )
        self.image_router = ImageRouter(configs=configs)

        saved_text_model = config.get('text_model', '')
        if saved_text_model:
            idx = self.text_model_combo.findData(saved_text_model)
            if idx >= 0:
                self.text_model_combo.setCurrentIndex(idx)
        saved_img_model = config.get('image_model', '')
        if saved_img_model:
            idx = self.img_model_combo.findData(saved_img_model)
            if idx >= 0:
                self.img_model_combo.setCurrentIndex(idx)

    def closeEvent(self, event):
        if self._generation_running:
            if self.worker:
                self.worker.cancel()
                self.thread_pool.waitForDone(3000)
        if self.current_book:
            save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
        event.accept()

    # ========== Generation Flow ==========

    def on_generate_clicked(self):
        if self._generation_running:
            return

        settings = self._get_current_settings()
        if not settings['theme']:
            QMessageBox.warning(self, 'Missing', 'Please enter a theme.')
            return

        # Configure BookEngine
        provider_map = {
            'Pollinations (Free)': 'pollinations',
            'OpenRouter': 'openrouter',
            'NVIDIA NIM': 'nvidia',
            'HuggingFace': 'huggingface',
            'Google (Gemini)': 'google_ai_studio',
            'Groq': 'groq',
        }
        provider = provider_map.get(settings['text_provider'], 'pollinations')
        api_key = settings['text_api_key']
        model = settings['text_model']

        self.book_engine.configure(provider, api_key, model, settings)

        # Create project
        project_name = f"book_{int(time.time())}"
        self.book_engine.create_project(project_name, settings)

        # Start multi-stage generation
        self._generation_running = True
        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText('Starting generation...')

        # Run in background thread
        self.worker = EngineGenerationWorker(self.book_engine, settings, self.image_router)
        self.worker.signals.finished.connect(self.on_generation_finished)
        self.worker.signals.error.connect(self.on_generation_error)
        self.worker.signals.progress.connect(self.update_status)
        self.worker.signals.page_ready.connect(self._on_page_ready_legacy)
        self.thread_pool.start(self.worker)

    def on_cancel_clicked(self):
        if self._generation_running:
            if self.worker:
                self.worker.cancel()
            self.book_engine.cancel()
            self.status_label.setText('Cancelling...')

    def on_generation_finished(self, book: Dict):
        self._generation_running = False
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.current_book = book
        self._populate_finished_tab(book)
        self._refresh_registry()
        self._refresh_images_tab()
        self._populate_outline_tree(book)
        self._populate_pages_list(book)
        save_project_state({'book': book, 'settings': self._get_current_settings()})
        self.status_label.setText('Generation complete!')

    def on_generation_error(self, err: str):
        self._generation_running = False
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, 'Generation Failed', err)
        self.status_label.setText('Generation failed')

    def update_status(self, message: str):
        self.status_label.setText(message)

    def _on_page_ready_legacy(self, page_idx: int, text: str, img_url: str):
        if self.current_book and page_idx < len(self.current_book.get('pages', [])):
            self.current_book['pages'][page_idx]['text'] = text
        self._on_page_selected(page_idx)

    # ========== BookEngine Signal Handlers ==========

    def _on_stage_started(self, stage: str, desc: str):
        self.status_label.setText(f'{stage}: {desc}')

    def _on_stage_completed(self, stage: str):
        self.status_label.setText(f'{stage} completed')

    def _on_stage_failed(self, stage: str, error: str):
        self.status_label.setText(f'{stage} failed: {error}')

    def _on_progress(self, message: str):
        self.status_label.setText(message)

    def _on_chapter_ready(self, chapter_num: int, content: str):
        self.status_label.setText(f'Chapter {chapter_num} ready')

    def _on_book_ready(self, book_data: Dict):
        self.current_book = book_data
        self._populate_finished_tab(book_data)
        self._refresh_registry()
        self._refresh_images_tab()
        self._populate_outline_tree(book_data)
        self._populate_pages_list(book_data)

    def _on_cost_update(self, total_cost: float):
        self.total_cost_label.setText(f'Total Cost: ${total_cost:.4f}')

    def _on_concept_ready(self, concept: Dict):
        title = concept.get('title', 'Untitled')
        self.status_label.setText(f'Concept ready: {title}')

    def _on_outline_ready(self, outline: str):
        self._refresh_outline_from_engine()

    def _on_characters_ready(self, characters: Dict):
        self._refresh_registry()

    def _on_worldbuilding_ready(self, worldbuilding: Dict):
        self._load_worldbuilding_to_tab(worldbuilding)

    def _refresh_outline_from_engine(self):
        if not self.book_engine:
            return
        book = self.book_engine.to_legacy_book_json()
        if book:
            self.current_book = book
            self._populate_outline_tree(book)

    # ========== Worldbuilding ==========

    def _generate_worldbuilding(self):
        if not self.book_engine._pm or not self.book_engine._kb:
            QMessageBox.warning(self, 'Not Ready', 'Generate concept and outline first.')
            return
        self.book_engine.generate_worldbuilding()

    def _save_worldbuilding(self):
        # Read from tab and save to engine
        wb = {
            'geography': self.wb_geography.toPlainText(),
            'culture_and_society': self.wb_culture.toPlainText(),
            'history': self.wb_history.toPlainText(),
            'rules_and_laws': self.wb_rules.toPlainText(),
            'technology_level': self.wb_tech.toPlainText(),
            'magic_system': self.wb_magic.toPlainText(),
            'key_locations': self.wb_locations.toPlainText(),
            'important_organizations': self.wb_orgs.toPlainText(),
            'flora_and_fauna': self.wb_flora.toPlainText(),
            'languages': self.wb_languages.toPlainText(),
            'religions_and_beliefs': self.wb_religions.toPlainText(),
            'economy': self.wb_economy.toPlainText(),
            'conflicts': self.wb_conflicts.toPlainText(),
        }
        if self.book_engine._kb:
            self.book_engine._kb.worldbuilding = self.book_engine._kb.worldbuilding.__class__(**wb)
            self.book_engine.save_project()
            QMessageBox.information(self, 'Saved', 'Worldbuilding saved to project.')

    def _load_worldbuilding_to_tab(self, wb: Dict):
        self.wb_geography.setPlainText(wb.get('geography', ''))
        self.wb_culture.setPlainText(wb.get('culture_and_society', ''))
        self.wb_history.setPlainText(wb.get('history', ''))
        self.wb_rules.setPlainText(wb.get('rules_and_laws', ''))
        self.wb_tech.setPlainText(wb.get('technology_level', ''))
        self.wb_magic.setPlainText(wb.get('magic_system', ''))
        self.wb_locations.setPlainText(wb.get('key_locations', ''))
        self.wb_orgs.setPlainText(wb.get('important_organizations', ''))
        self.wb_flora.setPlainText(wb.get('flora_and_fauna', ''))
        self.wb_languages.setPlainText(wb.get('languages', ''))
        self.wb_religions.setPlainText(wb.get('religions_and_beliefs', ''))
        self.wb_economy.setPlainText(wb.get('economy', ''))
        self.wb_conflicts.setPlainText(wb.get('conflicts', ''))

    # ========== Expert Config ==========

    def _load_expert_config(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load Expert Config', '', 'YAML Files (*.yaml *.yml);;JSON Files (*.json)')
        if path:
            try:
                import yaml
                with open(path, 'r') as f:
                    if path.endswith('.json'):
                        data = json.load(f)
                    else:
                        data = yaml.safe_load(f)
                self.expert_config_editor.setPlainText(yaml.dump(data, sort_keys=False))
                QMessageBox.information(self, 'Loaded', f'Loaded expert config from {path}')
            except Exception as e:
                QMessageBox.critical(self, 'Error', f'Failed to load: {e}')

    def _save_expert_config(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save Expert Config', 'expert_config.yaml', 'YAML Files (*.yaml *.yml);;JSON Files (*.json)')
        if path:
            try:
                import yaml
                text = self.expert_config_editor.toPlainText()
                data = yaml.safe_load(text)
                with open(path, 'w') as f:
                    if path.endswith('.json'):
                        json.dump(data, f, indent=2)
                    else:
                        yaml.dump(data, f, sort_keys=False)
                QMessageBox.information(self, 'Saved', f'Saved to {path}')
            except Exception as e:
                QMessageBox.critical(self, 'Error', f'Failed to save: {e}')

    def _export_yaml_config(self):
        # Export current project as expert config YAML
        if not self.book_engine._kb:
            QMessageBox.warning(self, 'No Project', 'Generate a book first.')
            return
        # Build expert config from current project
        import yaml
        config = {
            'version': 1,
            'project': {
                'project_name': self.book_engine._kb.project_name,
                'title': self.book_engine._kb.title,
                'genre': self.book_engine._kb.genre,
                'description': self.book_engine._kb.description,
                'category': self.book_engine._kb.category,
                'language': self.book_engine._kb.language,
                'num_characters': self.book_engine._kb.num_characters,
                'worldbuilding_needed': self.book_engine._kb.worldbuilding_needed,
                'review_preference': self.book_engine._kb.review_preference,
                'book_length': self.book_engine._kb.book_length,
                'num_chapters': self.book_engine._kb.num_chapters,
                'llm_provider': 'pollinations',  # would need mapping
                'model': 'openai-fast',
            },
            'workflow': {
                'concept_approval': 'auto',
                'outline_review': 'auto',
                'character_generation': 'auto',
                'worldbuilding_generation': 'auto',
                'chapter_writing': 'auto',
                'chapter_error_mode': 'continue',
                'formatting': 'auto',
                'output_format': 'markdown',
            }
        }
        self.expert_config_editor.setPlainText(yaml.dump(config, sort_keys=False))
        QMessageBox.information(self, 'Exported', 'Expert config exported to editor tab.')

    # ========== Cost Tracker ==========

    def _refresh_cost_tracker(self):
        log_path = os.path.join('libriscribe', 'llm_usage.jsonl')
        if not os.path.exists(log_path):
            log_path = 'llm_usage.jsonl'
        if os.path.exists(log_path):
            self.cost_table.setRowCount(0)
            total = 0.0
            with open(log_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        row = self.cost_table.rowCount()
                        self.cost_table.insertRow(row)
                        self.cost_table.setItem(row, 0, QTableWidgetItem(entry.get('timestamp', '')))
                        self.cost_table.setItem(row, 1, QTableWidgetItem(entry.get('provider', '')))
                        self.cost_table.setItem(row, 2, QTableWidgetItem(entry.get('model', '')))
                        self.cost_table.setItem(row, 3, QTableWidgetItem(str(entry.get('input_tokens', 0))))
                        self.cost_table.setItem(row, 4, QTableWidgetItem(str(entry.get('output_tokens', 0))))
                        cost = entry.get('cost_usd', 0)
                        total += cost
                        self.cost_table.setItem(row, 5, QTableWidgetItem(f'${cost:.6f}'))
                    except Exception:
                        pass
            self.total_cost_label.setText(f'Total Cost: ${total:.4f}')
        else:
            QMessageBox.information(self, 'No Data', 'No llm_usage.jsonl found yet.')

    def _clear_cost_log(self):
        log_path = os.path.join('libriscribe', 'llm_usage.jsonl')
        if os.path.exists(log_path):
            os.remove(log_path)
        self.cost_table.setRowCount(0)
        self.total_cost_label.setText('Total Cost: $0.0000')

    # ========== Prompts ==========

    def _load_prompt_template(self):
        agent = self.prompt_agent_combo.currentText()
        template_dir = os.path.join('libriscribe', 'prompts', 'templates')
        path = os.path.join(template_dir, f'{agent}.yml')
        if os.path.exists(path):
            with open(path, 'r') as f:
                self.prompt_editor.setPlainText(f.read())
        else:
            self.prompt_editor.setPlainText(f'# Template not found: {path}')

    def _save_prompt_template(self):
        agent = self.prompt_agent_combo.currentText()
        template_dir = os.path.join('libriscribe', 'prompts', 'templates')
        os.makedirs(template_dir, exist_ok=True)
        path = os.path.join(template_dir, f'{agent}.yml')
        with open(path, 'w') as f:
            f.write(self.prompt_editor.toPlainText())
        QMessageBox.information(self, 'Saved', f'Saved prompt template for {agent}')

    # ========== Outline / Pages / Characters ==========

    def _populate_outline_tree(self, book: Dict):
        self._outline_updating = True
        self.outline_tree.clear()
        for ch_idx, ch in enumerate(book.get('outline', [])):
            ch_item = QTreeWidgetItem([f'Chapter {ch_idx+1}: {ch.get("title", "")}', ''])
            ch_item.setFlags(ch_item.flags() | Qt.ItemIsEditable)
            for b_idx, beat in enumerate(ch.get('beats', [])):
                beat_item = QTreeWidgetItem([f'  Beat {b_idx+1}', beat])
                beat_item.setFlags(beat_item.flags() | Qt.ItemIsEditable)
                ch_item.addChild(beat_item)
            self.outline_tree.addTopLevelItem(ch_item)
        self.outline_tree.expandAll()
        self._outline_updating = False

    def _populate_pages_list(self, book: Dict):
        self.pages_list.clear()
        for i, page in enumerate(book.get('pages', [])):
            item = QListWidgetItem(f'Page {i+1}: {page["text"][:80]}...')
            item.setData(Qt.UserRole, i)
            self.pages_list.addItem(item)

    def _on_outline_item_changed(self, item, column):
        if self._outline_updating or not self.current_book:
            return
        outline = self.current_book.get('outline', [])
        parent = item.parent()
        if parent is None:
            ch_idx = self.outline_tree.indexOfTopLevelItem(item)
            if 0 <= ch_idx < len(outline):
                title_text = item.text(0)
                prefix = f'Chapter {ch_idx+1}: '
                if title_text.startswith(prefix):
                    title_text = title_text[len(prefix):]
                outline[ch_idx]['title'] = title_text
        else:
            ch_idx = self.outline_tree.indexOfTopLevelItem(parent)
            b_idx = parent.indexOfChild(item)
            if 0 <= ch_idx < len(outline):
                beats = outline[ch_idx].get('beats', [])
                if 0 <= b_idx < len(beats):
                    outline[ch_idx]['beats'][b_idx] = item.text(1)
        flat_beats = []
        for c_idx, ch in enumerate(outline):
            for b_idx, beat in enumerate(ch.get('beats', [])):
                flat_beats.append({'ch': c_idx, 'beat': beat, 'title': ch.get('title', 'Chapter')})
        self.current_book['flat_beats'] = flat_beats
        save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})

    def _regenerate_outline(self):
        if not self.current_book or not self.text_router:
            return
        settings = self._get_current_settings()
        self.status_label.setText('Regenerating outline...')
        QApplication.processEvents()
        try:
            new_outline = _generate_outline(settings, self.text_router)
            if new_outline:
                self.current_book['outline'] = new_outline
                flat_beats = []
                for c_idx, ch in enumerate(new_outline):
                    for b_idx, beat in enumerate(ch.get('beats', [])):
                        flat_beats.append({'ch': c_idx, 'beat': beat, 'title': ch.get('title', 'Chapter')})
                self.current_book['flat_beats'] = flat_beats

                self._outline_updating = True
                self.outline_tree.clear()
                for ch_idx, ch in enumerate(new_outline):
                    ch_item = QTreeWidgetItem([f'Chapter {ch_idx+1}: {ch.get("title", "")}', ''])
                    ch_item.setFlags(ch_item.flags() | Qt.ItemIsEditable)
                    for b_idx, beat in enumerate(ch.get('beats', [])):
                        beat_item = QTreeWidgetItem([f'  Beat {b_idx+1}', beat])
                        beat_item.setFlags(beat_item.flags() | Qt.ItemIsEditable)
                        ch_item.addChild(beat_item)
                    self.outline_tree.addTopLevelItem(ch_item)
                self.outline_tree.expandAll()
                self._outline_updating = False

                self.status_label.setText('Outline regenerated.')
                save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
            else:
                self.status_label.setText('Outline generation returned empty.')
        except Exception as e:
            self.status_label.setText(f'Outline regeneration failed: {e}')
            QMessageBox.critical(self, 'Regeneration Failed', str(e))

    def _export_book_json(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Book JSON', 'book.json', 'JSON Files (*.json)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.current_book, f, indent=2, ensure_ascii=False)

    def _on_page_selected(self, row: int):
        if not self.current_book or row < 0:
            self.page_text.clear()
            return
        pages = self.current_book.get('pages', [])
        if row < len(pages):
            page = pages[row]
            html = f'<h3>Page {row+1}</h3>'
            if page.get('img_url') and os.path.exists(page['img_url']):
                abs_path = os.path.abspath(page['img_url']).replace('\\', '/')
                html += f'<img src="file:///{abs_path}" width="300"><br>'
            html += f'<p>{page.get("text", "").replace(chr(10), "<br>")}</p>'
            self.page_text.setHtml(html)

    def _regenerate_current_page(self):
        if not self.current_book or not self.text_router:
            return
        row = self.pages_list.currentRow()
        if row < 0 or row >= len(self.current_book['pages']):
            QMessageBox.warning(self, 'No Selection', 'Select a page to regenerate.')
            return

        settings = self._get_current_settings()
        flat_beats = self.current_book.get('flat_beats', [])
        genre = self.current_book.get('metadata', {}).get('genre', settings.get('genre', ''))
        audience = self.current_book.get('metadata', {}).get('audience', settings.get('audience', ''))

        prompt = f'Regenerate page {row+1} of a {audience} {genre} book.'
        prompt += f' Theme: {settings.get("theme", "")}.'
        if row < len(flat_beats):
            fb = flat_beats[row]
            prompt += f' CHAPTER: {fb["title"]}. BEAT: {fb["beat"]}'
        prompt += f' LENGTH: {_page_length(audience)}'
        prompt += ' RULES: Consistent character names. Cause and effect. End on a small turn.'
        prompt += ' Output ONLY the page prose.'

        self.status_label.setText(f'Regenerating page {row+1}...')
        QApplication.processEvents()

        try:
            new_text = _generate_with_retry(prompt, self.text_router)
            new_text = new_text.strip().strip('*"\'')
            if new_text and len(new_text) >= 30:
                self.current_book['pages'][row]['text'] = new_text
                self._on_page_selected(row)
                self.pages_list.item(row).setText(f'Page {row+1}: {new_text[:80]}...')
                self.status_label.setText(f'Page {row+1} regenerated.')
                save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
            else:
                self.status_label.setText('Regeneration produced too short text.')
        except Exception as e:
            self.status_label.setText(f'Regeneration failed: {e}')
            QMessageBox.critical(self, 'Regeneration Failed', str(e))

    def _refresh_registry(self):
        if not self.current_book:
            return
        self.char_tree.clear()
        for char in self.current_book.get('characters', []):
            item = QTreeWidgetItem([
                char.get('name', 'Unknown'),
                char.get('role', ''),
                ', '.join(char.get('traits', [])),
                char.get('status', 'active')
            ])
            self.char_tree.addTopLevelItem(item)

    def _add_character(self):
        name, ok = QInputDialog.getText(self, 'Add Character', 'Name:')
        if ok and name:
            role, ok = QInputDialog.getText(self, 'Add Character', 'Role (protagonist/ally/antagonist/etc):')
            if ok:
                traits, ok = QInputDialog.getText(self, 'Add Character', 'Traits (comma-separated):')
                if ok:
                    desc, ok = QInputDialog.getMultiLineText(self, 'Add Character', 'Description:')
                    if ok:
                        char = {
                            'id': name.lower().replace(' ', '_'),
                            'name': name,
                            'role': role or 'supporting',
                            'traits': [t.strip() for t in (traits or '').split(',') if t.strip()],
                            'description': desc,
                        }
                        if self.current_book:
                            self.current_book['characters'].append(char)
                            self._refresh_registry()
                            save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})

    def _edit_character(self):
        items = self.char_tree.selectedItems()
        if not items:
            return
        item = items[0]
        idx = self.char_tree.indexOfTopLevelItem(item)
        chars = self.current_book.get('characters', [])
        if 0 <= idx < len(chars):
            char = chars[idx]
            name, ok = QInputDialog.getText(self, 'Edit Character', 'Name:', text=char.get('name', ''))
            if ok:
                role, ok = QInputDialog.getText(self, 'Edit Character', 'Role:', text=char.get('role', ''))
                if ok:
                    traits, ok = QInputDialog.getText(self, 'Edit Character', 'Traits:', text=', '.join(char.get('traits', [])))
                    if ok:
                        desc, ok = QInputDialog.getMultiLineText(self, 'Edit Character', 'Description:', text=char.get('description', ''))
                        if ok:
                            char['name'] = name
                            char['role'] = role
                            char['traits'] = [t.strip() for t in traits.split(',') if t.strip()]
                            char['description'] = desc
                            self._refresh_registry()
                            save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})

    def _delete_character(self):
        items = self.char_tree.selectedItems()
        if not items:
            return
        item = items[0]
        idx = self.char_tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(self.current_book.get('characters', [])):
            del self.current_book['characters'][idx]
            self._refresh_registry()
            save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})

    def _refresh_images_tab(self):
        # Clear grid
        while self.images_grid_layout.count():
            child = self.images_grid_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self.current_book:
            return

        # Cover
        if self.current_book.get('cover_url') and os.path.exists(self.current_book['cover_url']):
            cover_label = QLabel()
            pix = QPixmap(self.current_book['cover_url'])
            if not pix.isNull():
                cover_label.setPixmap(pix.scaledToWidth(300, Qt.SmoothTransformation))
            self.images_grid_layout.addWidget(QLabel('Cover:'))
            self.images_grid_layout.addWidget(cover_label)

        # Page images
        for i, page in enumerate(self.current_book.get('pages', [])):
            if page.get('img_url') and os.path.exists(page['img_url']):
                row_widget = QWidget()
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)

                info_label = QLabel(f'Page {i+1}:')
                img_label = QLabel()
                pix = QPixmap(page['img_url'])
                if not pix.isNull():
                    img_label.setPixmap(pix.scaledToWidth(200, Qt.SmoothTransformation))

                regen_btn = QPushButton('Regenerate')
                regen_btn.setMaximumWidth(100)
                page_idx = i
                regen_btn.clicked.connect(lambda checked, idx=page_idx: self._regenerate_single_image(idx))

                row_layout.addWidget(info_label)
                row_layout.addWidget(img_label)
                row_layout.addWidget(regen_btn)
                row_layout.addStretch()

                self.images_grid_layout.addWidget(row_widget)

        self.images_grid_layout.addStretch()

    def _regenerate_single_image(self, page_idx):
        if not self.current_book or not self.image_router:
            return
        pages = self.current_book.get('pages', [])
        if page_idx < 0 or page_idx >= len(pages):
            return

        page = pages[page_idx]
        settings = self._get_current_settings()
        style_phrase = settings.get('style_phrase', 'professional illustration')
        genre = self.current_book.get('metadata', {}).get('genre', '')

        art_prompt = f'{style_phrase}, {genre} book art: {page["text"][:120]}'
        self.status_label.setText(f'Regenerating image for page {page_idx+1}...')
        QApplication.processEvents()

        try:
            res, _ = self.image_router.generate(art_prompt)
            if res.ok:
                page['img_url'] = res.path
                self._refresh_images_tab()
                self.status_label.setText(f'Image for page {page_idx+1} regenerated.')
                save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
            else:
                self.status_label.setText(f'Image generation failed: {res.error}')
        except Exception as e:
            self.status_label.setText(f'Image generation failed: {e}')

    def _regenerate_cover(self):
        if not self.current_book or not self.image_router:
            return

        meta = self.current_book.get('metadata', {})
        settings = self._get_current_settings()
        style_phrase = settings.get('style_phrase', 'professional illustration')
        genre = meta.get('genre', '')
        theme = meta.get('theme', '')
        setting = meta.get('setting', '')
        title = meta.get('title', '')

        cover_prompt = f'{style_phrase}, {self._author_art_hint()}, {genre} book cover, KDP 2560x1600, professional: {theme} in {setting}. Title: {title}'

        self.status_label.setText('Regenerating cover...')
        QApplication.processEvents()

        try:
            res, _ = self.image_router.generate(cover_prompt)
            if res.ok:
                self.current_book['cover_url'] = res.path
                self._refresh_images_tab()
                self.status_label.setText('Cover regenerated.')
                save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
            else:
                self.status_label.setText(f'Cover generation failed: {res.error}')
        except Exception as e:
            self.status_label.setText(f'Cover generation failed: {e}')
            QMessageBox.critical(self, 'Regeneration Failed', str(e))

    def _regenerate_all_images(self):
        if not self.current_book or not self.image_router:
            return

        settings = self._get_current_settings()
        style_phrase = settings.get('style_phrase', 'professional illustration')
        genre = self.current_book.get('metadata', {}).get('genre', '')

        pages = self.current_book.get('pages', [])
        total = len(pages)
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        for i, page in enumerate(pages):
            self.progress_bar.setValue(i)
            self.status_label.setText(f'Regenerating image {i+1}/{total}...')
            QApplication.processEvents()
            art_prompt = f'{style_phrase}, {genre} book art: {page["text"][:120]}'
            try:
                res, _ = self.image_router.generate(art_prompt)
                if res.ok:
                    page['img_url'] = res.path
            except Exception:
                pass

        self._regenerate_cover()

        self.progress_bar.setVisible(False)
        self._refresh_images_tab()
        save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
        self.status_label.setText('All images regenerated.')

    def _restore_project(self):
        data = load_project_state()
        if not data:
            return

        book = data.get('book')
        settings = data.get('settings', {})

        if not book:
            return

        self.current_book = book

        self._outline_updating = True
        self.outline_tree.clear()
        for ch_idx, ch in enumerate(book.get('outline', [])):
            ch_item = QTreeWidgetItem([f'Chapter {ch_idx+1}: {ch.get("title", "")}', ''])
            ch_item.setFlags(ch_item.flags() | Qt.ItemIsEditable)
            for b_idx, beat in enumerate(ch.get('beats', [])):
                beat_item = QTreeWidgetItem([f'  Beat {b_idx+1}', beat])
                beat_item.setFlags(beat_item.flags() | Qt.ItemIsEditable)
                ch_item.addChild(beat_item)
            self.outline_tree.addTopLevelItem(ch_item)
        self.outline_tree.expandAll()
        self._outline_updating = False

        self.pages_list.clear()
        for i, page in enumerate(book.get('pages', [])):
            item = QListWidgetItem(f'Page {i+1}: {page["text"][:80]}...')
            item.setData(Qt.UserRole, i)
            self.pages_list.addItem(item)

        self._refresh_registry()
        self._refresh_images_tab()
        self._populate_finished_tab(book)

        if settings:
            self._apply_config(settings)

        self.status_label.setText('Project restored.')


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    app.setStyleSheet("""
        /* ── Global ── */
        QWidget {
            font-family: 'Segoe UI', 'SF Pro', 'Arial', sans-serif;
            font-size: 13px;
            color: #e0e0e0;
            background-color: #1e1e2e;
        }

        /* ── Tab Widget ── */
        QTabWidget::pane {
            border: 1px solid #313244;
            border-radius: 8px;
            background: #1e1e2e;
            top: -1px;
        }
        QTabBar::tab {
            background: #313244;
            color: #a6adc8;
            padding: 10px 22px;
            margin-right: 2px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            font-weight: 600;
            font-size: 12px;
            min-width: 120px;
        }
        QTabBar::tab:selected {
            background: #45475a;
            color: #cdd6f4;
            border-bottom: 2px solid #89b4fa;
        }
        QTabBar::tab:hover:!selected {
            background: #3b3b52;
            color: #cdd6f4;
        }

        /* ── Group Boxes ── */
        QGroupBox {
            font-weight: 700;
            font-size: 14px;
            color: #89b4fa;
            border: 1px solid #313244;
            border-radius: 10px;
            margin-top: 14px;
            padding: 18px 14px 14px 14px;
            background: #181825;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: #89b4fa;
        }

        /* ── Buttons ── */
        QPushButton {
            background: #313244;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: 600;
        }
        QPushButton:hover { background: #45475a; border-color: #585b70; }
        QPushButton:pressed { background: #1e1e2e; }
        QPushButton:disabled { background: #1e1e2e; color: #6c6f85; border-color: #313244; }
        QPushButton#generate_btn {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #89b4fa, stop:1 #74c7ec);
            color: #1e1e2e;
            border: none;
            padding: 10px 24px;
            font-size: 14px;
        }
        QPushButton#generate_btn:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #74c7ec, stop:1 #89b4fa); }
        QPushButton#cancel_btn {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f38ba8, stop:1 #eba0ac);
            color: #1e1e2e;
            border: none;
            padding: 10px 24px;
            font-size: 14px;
        }
        QPushButton#cancel_btn:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #eba0ac, stop:1 #f38ba8); }

        /* ── Inputs ── */
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
            background: #1e1e2e;
            color: #cdd6f4;
            border: 1px solid #45475a;
            border-radius: 6px;
            padding: 6px 10px;
            selection-background-color: #89b4fa;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
            border-color: #89b4fa;
        }
        QComboBox::drop-down { border: none; width: 24px; }
        QComboBox QAbstractItemView {
            background: #1e1e2e;
            color: #cdd6f4;
            selection-background-color: #45475a;
            border: 1px solid #313244;
        }
        QTextEdit, QPlainTextEdit { line-height: 1.5; }

        /* ── Progress Bar ── */
        QProgressBar {
            border: 1px solid #313244;
            border-radius: 6px;
            background: #1e1e2e;
            text-align: center;
            color: #cdd6f4;
            height: 20px;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #89b4fa, stop:1 #74c7ec);
            border-radius: 5px;
        }

        /* ── Scroll Bars ── */
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical {
            background: #1e1e2e;
            width: 10px;
            border-radius: 5px;
            margin: 2px;
        }
        QScrollBar::handle:vertical {
            background: #45475a;
            border-radius: 5px;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover { background: #585b70; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QScrollBar:horizontal {
            background: #1e1e2e;
            height: 10px;
            border-radius: 5px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal {
            background: #45475a;
            border-radius: 5px;
            min-width: 30px;
        }
        QScrollBar::handle:horizontal:hover { background: #585b70; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }

        /* ── Splitter ── */
        QSplitter::handle {
            background: #313244;
            width: 3px;
            border-radius: 2px;
        }
        QSplitter::handle:hover { background: #89b4fa; }

        /* ── Menu ── */
        QMenu {
            background: #313244;
            border: 1px solid #45475a;
            border-radius: 8px;
            padding: 6px;
            color: #cdd6f4;
        }
        QMenu::item {
            padding: 8px 24px;
            border-radius: 4px;
        }
        QMenu::item:selected { background: #45475a; }

        /* ── Message Box ── */
        QMessageBox { background: #1e1e2e; }
        QMessageBox QLabel { color: #cdd6f4; font-size: 13px; }
        QMessageBox QPushButton { min-width: 80px; }

        /* ── Tree/List ── */
        QTreeWidget, QListWidget {
            background: #1e1e2e;
            border: 1px solid #313244;
            border-radius: 6px;
            alternate-background-color: #181825;
        }
        QTreeWidget::item, QListWidget::item { padding: 6px; }
        QTreeWidget::item:selected, QListWidget::item:selected { background: #45475a; color: #cdd6f4; }

        /* ── Table ── */
        QTableWidget {
            background: #1e1e2e;
            alternate-background-color: #181825;
            gridline-color: #313244;
            color: #cdd6f4;
        }
        QHeaderView::section {
            background: #313244;
            color: #89b4fa;
            padding: 6px;
            border: 1px solid #45475a;
            font-weight: 600;
        }

        /* ── Text Browser ── */
        QTextBrowser {
            background: #181825;
            border: 1px solid #313244;
            border-radius: 6px;
            color: #cdd6f4;
        }
    """)

    window = BookGeneratorApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
