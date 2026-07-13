"""
Auto Book Generator - Professional Edition
===========================================

JSON-first generation: full book JSON is generated before any page text.
Every page written with COMPLETE book JSON as context.
"""

import sys
import os
import json
import time
import re
import hashlib
import base64
import urllib.parse
import requests
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QTextEdit, QPushButton, QSpinBox,
    QProgressBar, QMessageBox, QComboBox, QCheckBox, QGroupBox, QTabWidget,
    QSplitter, QScrollArea, QFrame, QFormLayout, QDialog, QDialogButtonBox,
    QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QTextBrowser, QMenu, QAction, QFileDialog, QSlider, QPlainTextEdit)
from PyQt5.QtGui import QPixmap, QFont, QIcon, QColor, QTextCursor, QImage
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer, QSize, QRunnable, QThreadPool, pyqtSlot, QObject

from providers import (Provider, ProviderResult, ProviderConfig, Router,
    PollinationsProvider, make_nvidia, make_openrouter, make_huggingface, make_google, make_groq)
from image_providers import (ImageProvider, ImageResult, ImageProviderConfig,
    ImageRouter, make_image_provider, PollinationsImageProvider,
    StableHordeImageProvider, HFSpaceImageProvider, GoogleNanoBananaProvider,
    NANO_BANANA_MODELS)
from author_voices import (AuthorVoice, AUTHORS_BY_GENRE, authors_for_genre,
    get_author_voice, DEFAULT_PROSE)
from models_catalog import (ModelInfo, fetch_for)

CONFIG_FILE = "book_config.json"
PROJECT_FILE = "book_project.json"

AUDIENCES = ["Children", "Middle Grade", "Young Adult", "Adult", "All Ages"]
GENRES = ["Fantasy", "Sci-Fi", "Horror", "Mystery", "Romance",
          "Adventure", "Comedy", "Drama", "Thriller", "Literary"]

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
}

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

DEFAULT_PROSE = {
    "style": "Clean modern third-person prose, lean description, active voice.",
    "donts": "Cliche adverbs, invented words, fragmented paragraphs.",
    "exemplar": "The door closed behind him. The corridor was quiet. The torch threw long shadows.",
}

def _estimate_chapters(total_pages, author_name):
    if total_pages <= 10: return max(1, total_pages // 2)
    if total_pages <= 20: return max(2, total_pages // 3)
    if total_pages <= 50: return max(3, total_pages // 6)
    if total_pages <= 100: return max(4, total_pages // 8)
    return max(5, total_pages // 10)

def _author_chapter_plan(total_pages, author_name):
    total = max(1, total_pages)
    chapters = max(1, _estimate_chapters(total_pages, author_name))
    base_per_chapter = max(1, total // chapters)
    plan, remaining = [], total
    for i in range(chapters):
        count = remaining if i == chapters - 1 else max(1, total // chapters) + (1 if i < (total % chapters) else 0)
        title = f"Chapter {i+1}: "
        if i < chapters * 0.25: title += 'Setup'
        elif i < chapters * 0.65: title += 'Development'
        elif i < chapters - 1: title += 'Climax'
        else: title += 'Resolution'
        plan.append((title, count))
        remaining -= count
    return plan

def _structure_directive_short(num_pages, idx):
    if num_pages <= 1: return "Full story in one page."
    third = max(1, num_pages // 3)
    two_thirds = max(third + 1, (2 * num_pages) // 3)
    if idx < third: return "SETUP — introduce protagonist, hint at mystery, end on hook."
    if idx < two_thirds: return "DEVELOP — advance one beat, cause and effect on the page."
    if idx < num_pages - 1: return "CLIMAX — peak confrontation; resolve inside the page."
    return "RESOLVE — satisfying close; calm, warm image; final payoff."

def _page_length(audience):
    lengths = {
        "Children": "80-120 words, 3-5 short paragraphs, sentences 6-10 words.",
        "Middle Grade": "150-250 words, 3-5 paragraphs, sentences 8-14 words.",
        "Young Adult": "200-350 words, 3-5 paragraphs, varied sentences.",
        "Adult": "300-500 words, 4-7 paragraphs, varied sentences.",
        "All Ages": "150-250 words, 3-5 paragraphs, sentences 8-12 words.",
    }
    return lengths.get(audience, "200-350 words, 3-5 paragraphs.")

def _extract_json_str_value(text: str, key: str) -> Optional[str]:
    try:
        start = text.index(f'"{key}"')
        colon = text.index(':', start)
        val_start = text.index('"', colon)
        val_end = text.index('"', val_start + 1)
        return text[val_start+1:val_end]
    except ValueError:
        return None

def _clean_text(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ''
    for marker in ('Assistant:', 'Response:', 'Output:', 'Text:', 'User:'):
        if raw.startswith(marker):
            raw = raw[len(marker):].strip()
    raw = raw.strip().strip('*"\'')
    return raw

def _looks_like_leak(text: str) -> bool:
    markers = ['Assistant:', 'Response:', 'Output:', 'Text:', 'User:', 'Here is', 'Here\'s the', '```']
    return any(text.lstrip().startswith(m) for m in markers)

def _ends_properly(text: str) -> bool:
    text = text.rstrip()
    return text.endswith(('.', '!', '?', '...', '."', '!"', '?"'))

class CharacterRegistry:
    """Persistent registry of characters, locations, items, events."""
    def __init__(self):
        self.characters: List[Dict] = []
        self.locations: List[Dict] = []
        self.items: List[Dict] = []
        self.events: List[Dict] = []
        self.plot_threads: List[Dict] = []

    def add_character(self, name, role, traits, description, first_page=0, status='active'):
        existing = next((c for c in self.characters if c['name'].lower() == name.lower()), None)
        if existing:
            existing.update({'traits': traits, 'description': description, 'status': status})
        else:
            self.characters.append({
                'name': name, 'role': role, 'traits': traits,
                'description': description, 'first_page': first_page,
                'status': status, 'appearances': [], 'arc_stage': 'introduction'
            })

    def add_location(self, name, description, connections=None, first_page=0):
        existing = next((l for l in self.locations if l['name'].lower() == name.lower()), None)
        if existing:
            existing.update({'description': description, 'connections': connections or []})
        else:
            self.locations.append({
                'name': name, 'description': description,
                'connections': connections or [], 'first_page': first_page
            })

    def add_item(self, name, item_type, description, owner='', properties='', first_page=0):
        existing = next((i for i in self.items if i['name'].lower() == name.lower()), None)
        if existing:
            existing.update({'description': description, 'owner': owner, 'properties': properties})
        else:
            self.items.append({
                'name': name, 'type': item_type, 'description': description,
                'owner': owner, 'properties': properties, 'first_page': first_page
            })

    def add_plot_thread(self, thread_id, description, status='active', notes=''):
        existing = next((t for t in self.plot_threads if t['id'] == thread_id), None)
        if existing:
            existing.update({'status': status, 'notes': notes})
        else:
            self.plot_threads.append({
                'id': thread_id, 'description': description,
                'status': status, 'notes': notes, 'created_at': time.time()
            })

    def add_event(self, chapter, page, description, characters=None, consequences=''):
        self.events.append({
            'chapter': chapter, 'page': page, 'description': description,
            'characters': characters or [], 'consequences': consequences,
            'timestamp': time.time()
        })

    def to_dict(self):
        return {
            'characters': self.characters,
            'locations': self.locations,
            'items': self.items,
            'events': self.events,
            'plot_threads': self.plot_threads,
        }

    @classmethod
    def from_dict(cls, data):
        reg = cls()
        reg.characters = data.get('characters', [])
        reg.locations = data.get('locations', [])
        reg.items = data.get('items', [])
        reg.events = data.get('events', [])
        reg.plot_threads = data.get('plot_threads', [])
        return reg

def _generate_outline(settings, router) -> list:
    """Generate a chapter outline with beats. Returns list of chapter dicts."""
    s = settings
    theme = s['theme']
    setting = s.get('setting', '') or 'an unspecified place'
    audience = s['audience']
    genre = s['genre']
    author_name = s.get('author_voice') or DEFAULT_PROSE.get('name', 'Default')
    author = get_author_voice(author_name, genre)
    num_pages = s['num_pages']
    aud_guide = AUDIENCE_GUIDANCE.get(audience, '')
    gen_guide = GENRE_GUIDANCE.get(genre, '')

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
            self.signals.error.emit(str(e))

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
        gen_guide = GENRE_GUIDANCE.get(genre, '')

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
                else:
                    self.signals.progress.emit(f'Page {page_idx+1} too short, skipping')

            if include_images and image_freq == 'every_n' and chunk_end > chunk_start:
                self.signals.progress.emit(f'Generating batch images for pages {chunk_start+1}-{chunk_end}...')
                for pi in range(chunk_start, min(chunk_end, len(book['pages']))):
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
        cover_prompt = f'{style_phrase}, {genre} book cover, KDP 2560x1600, professional: {theme} in {setting}. Title: {book["metadata"]["title"]}'
        try:
            res, _ = self.image_router.generate(cover_prompt)
            if res.ok:
                book['cover_url'] = res.path
        except Exception as e:
            self.signals.progress.emit(f'Cover failed: {e}')

        for ch_idx, ch in enumerate(book.get('outline', [])):
            chapter_summaries.append(f'Chapter {ch_idx+1}: {ch.get("title", "")}')

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

        copyright_html = f'<html><body><p>Copyright © {datetime.now().year} {book["metadata"].get("author_voice", "AI Author")}</p><p>All rights reserved.</p></body></html>'
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
                    epub_book.add_item(epub.EpubImage(uid=img_name, file_name=f'images/{img_name}', media_type='image/jpeg', content=open(page['img_url'], 'rb').read()))
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
        pdf.cell(0, 6, sanitize(f'Copyright © {datetime.now().year} {book["metadata"].get("author_voice", "AI Author")}'), 0, 1, 'C')
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

class BookGeneratorApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Auto Book Generator - Professional Edition')
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        self.text_router = None
        self.image_router = None
        self.worker = None
        self.thread_pool = QThreadPool.globalInstance()
        self.current_book = None
        self.registry = CharacterRegistry()

        self._build_ui()
        self._load_config()
        self._probe_all()

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
        self._build_images_tab()
        self._build_finished_tab()

        bar = QHBoxLayout()
        self.status_label = QLabel('Ready')
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.generate_btn = QPushButton('Generate Book')
        self.generate_btn.clicked.connect(self.on_generate_clicked)
        self.generate_btn.setStyleSheet('QPushButton { background: #2e7d32; color: white; font-weight: bold; padding: 8px 16px; }')
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        self.cancel_btn.setEnabled(False)
        bar.addWidget(self.status_label)
        bar.addWidget(self.progress_bar)
        bar.addStretch()
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.generate_btn)
        main_layout.addLayout(bar)

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
        self.img_api_key.setPlaceholderText('Enter API key (not needed for free providers)')
        img_form.addRow('API Key:', self.img_api_key)

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

        # Populate initial model lists
        self._on_text_provider_changed(self.text_provider_combo.currentText())
        self._on_img_provider_changed(self.img_provider_combo.currentText())

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
        if 'Pollinations' in name:
            key_name = 'Pollinations'
        elif 'Google' in name:
            key_name = 'Google Nano Banana'
            text_key = self.text_api_key.text().strip()
            if text_key and not self.img_api_key.text().strip():
                self.img_api_key.setText(text_key)
        elif 'Stable' in name:
            key_name = 'Stable Horde'
        elif 'HuggingFace' in name:
            key_name = 'HFSpace'
        else:
            key_name = 'Pollinations'
        self._populate_image_models(key_name)

    def _populate_text_models(self, provider_name):
        api_key = self.text_api_key.text().strip()
        models = fetch_for(provider_name, api_key)
        self.text_model_combo.clear()
        for m in models:
            self.text_model_combo.addItem(m.display(), m.id)

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
        html += '<b>Image — Google Nano Banana (your API key):</b> gemini-3.1-flash-lite-image (cheapest)'
        self.free_models_browser.setHtml(html)

    def _build_settings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, 'Book Settings')

        book_group = QGroupBox('Book Settings')
        bg_layout = QFormLayout(book_group)
        self.theme_edit = QLineEdit()
        self.theme_edit.setPlaceholderText('e.g., friendship, courage, redemption')
        bg_layout.addRow('Theme:', self.theme_edit)
        self.setting_edit = QLineEdit()
        self.setting_edit.setPlaceholderText('e.g., a magical forest kingdom')
        bg_layout.addRow('Setting:', self.setting_edit)
        self.genre_combo = QComboBox()
        self.genre_combo.addItems(GENRES)
        bg_layout.addRow('Genre:', self.genre_combo)
        self.audience_combo = QComboBox()
        self.audience_combo.addItems(AUDIENCES)
        bg_layout.addRow('Audience:', self.audience_combo)
        self.author_combo = QComboBox()
        self.author_combo.addItem('Default (Clean Prose)')
        for genre_authors in AUTHORS_BY_GENRE.values():
            for a in genre_authors:
                self.author_combo.addItem(a.name)
        bg_layout.addRow('Author Voice:', self.author_combo)
        self.pages_spin = QSpinBox()
        self.pages_spin.setRange(1, 1000)
        self.pages_spin.setValue(20)
        bg_layout.addRow('Total Pages:', self.pages_spin)
        layout.addWidget(book_group)

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
        layout.addWidget(img_settings)

        config_layout = QHBoxLayout()
        self.save_config_btn = QPushButton('Save Config')
        self.save_config_btn.clicked.connect(self._save_full_config)
        self.load_config_btn = QPushButton('Load Config')
        self.load_config_btn.clicked.connect(self._load_config)
        config_layout.addWidget(self.save_config_btn)
        config_layout.addWidget(self.load_config_btn)
        layout.addLayout(config_layout)

        layout.addStretch()

    def _build_outline_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderLabels(['Chapter / Beat', 'Details'])
        self.outline_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.outline_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
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
        btn_layout.addWidget(self.refresh_registry_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, 'Characters/Registry')

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
        out_dir = os.path.join('Generated_Books', self.current_book.get('title', 'untitled').replace(' ', '_'))
        os.makedirs(out_dir, exist_ok=True)
        os.startfile(out_dir)

    def _populate_finished_tab(self, book: Dict):
        title = book.get('title', 'Untitled')
        out_dir = os.path.join('Generated_Books', title.replace(' ', '_'))
        pages = book.get('pages', [])

        self.finished_info.setText(
            f'<b>{title}</b> | {len(pages)} pages | '
            f'Saved to: {os.path.abspath(out_dir)}'
        )

        html = f'<h2>{title}</h2>'
        if book.get('genre'):
            html += f'<p><i>Genre: {book["genre"]} | Audience: {book.get("audience", "")}</i></p>'
        if book.get('synopsis'):
            html += f'<p>{book["synopsis"]}</p>'
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
        if not path:
            return
        try:
            from ebooklib import epub
            book_e = epub.EpubBook()
            title = self.current_book.get('title', 'Untitled')
            book_e.set_identifier('bookgen-' + hashlib.md5(title.encode()).hexdigest()[:8])
            book_e.set_title(title)
            book_e.set_language('en')

            for i, page in enumerate(self.current_book.get('pages', [])):
                ch = epub.EpubHtml(title=f'Page {i+1}', file_name=f'page_{i+1}.xhtml', lang='en')
                content = f'<h2>Page {i+1}</h2><p>{page.get("text", "")}</p>'
                img_path = page.get('img_url', '')
                if img_path and os.path.exists(img_path):
                    with open(img_path, 'rb') as f:
                        img_data = f.read()
                    ext = os.path.splitext(img_path)[1].lstrip('.')
                    img_item = epub.EpubItem(uid=f'img_{i+1}', file_name=f'images/img_{i+1}.{ext}',
                                             media_type=f'image/{ext}', content=img_data)
                    book_e.add_item(img_item)
                    content += f'<p><img src="images/img_{i+1}.{ext}" /></p>'
                ch.content = content.encode('utf-8')
                book_e.add_item(ch)

            book_e.spine = ['nav'] + list(book_e.get_items_of_type(9))
            epub.write_epub(path, book_e, {})
            QMessageBox.information(self, 'Exported', f'EPUB saved to {path}')
        except ImportError:
            QMessageBox.warning(self, 'Missing', 'pip install ebooklib')
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', str(e))

    def _export_pdf(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export PDF', 'book.pdf', 'PDF Files (*.pdf)')
        if not path:
            return
        try:
            from fpdf import FPDF
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            title = self.current_book.get('title', 'Untitled')
            pdf.add_page()
            pdf.set_font('Helvetica', 'B', 24)
            pdf.cell(0, 15, title.encode('latin-1', 'replace').decode('latin-1'), ln=True, align='C')
            pdf.set_font('Helvetica', '', 12)
            for i, page in enumerate(self.current_book.get('pages', [])):
                pdf.add_page()
                pdf.set_font('Helvetica', 'B', 14)
                pdf.cell(0, 10, f'Page {i+1}', ln=True)
                pdf.set_font('Helvetica', '', 11)
                text = page.get('text', '')
                text = text.encode('latin-1', 'replace').decode('latin-1')
                pdf.multi_cell(0, 7, text)
                img_path = page.get('img_url', '')
                if img_path and os.path.exists(img_path):
                    try:
                        pdf.image(img_path, w=100)
                    except Exception:
                        pass
            pdf.output(path)
            QMessageBox.information(self, 'Exported', f'PDF saved to {path}')
        except ImportError:
            QMessageBox.warning(self, 'Missing', 'pip install fpdf2')
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', str(e))

    def _export_html(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export HTML', 'book.html', 'HTML Files (*.html)')
        if not path:
            return
        try:
            title = self.current_book.get('title', 'Untitled')
            html = f'<html><head><meta charset="utf-8"><title>{title}</title>'
            html += '<style>body{font-family:Georgia,serif;max-width:800px;margin:auto;padding:20px}'
            html += 'h1,h2{color:#333}img{max-width:100%;margin:10px 0}.page{margin-bottom:2em;border-bottom:1px solid #ccc}</style>'
            html += f'</head><body><h1>{title}</h1>'
            for i, page in enumerate(self.current_book.get('pages', [])):
                html += f'<div class="page"><h2>Page {i+1}</h2><p>{page.get("text", "")}</p>'
                img_path = page.get('img_url', '')
                if img_path and os.path.exists(img_path):
                    abs_path = os.path.abspath(img_path).replace('\\', '/')
                    html += f'<img src="{abs_path}" />'
                html += '</div>'
            html += '</body></html>'
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            QMessageBox.information(self, 'Exported', f'HTML saved to {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Export Error', str(e))

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

        if 'Pollinations' in provider_name:
            configs = [ImageProviderConfig(name='Pollinations', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif 'Google' in provider_name and api_key:
            configs = [ImageProviderConfig(name='Google Nano Banana', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif 'Stable' in provider_name and api_key:
            configs = [ImageProviderConfig(name='Stable Horde', api_key=api_key, model=model_id, enabled=True, priority=0)]
        elif 'HuggingFace' in provider_name:
            configs = [ImageProviderConfig(name='HFSpace', api_key=api_key, model=model_id, enabled=True, priority=0)]
        else:
            configs = [ImageProviderConfig(name='Pollinations', api_key='', enabled=True, priority=0)]

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
        config = {
            'text_provider': self.text_provider_combo.currentText(),
            'text_api_key': self.text_api_key.text(),
            'text_model': self.text_model_combo.currentData() or '',
            'image_provider': self.img_provider_combo.currentText(),
            'image_api_key': self.img_api_key.text(),
            'image_model': self.img_model_combo.currentData() or '',
            'theme': self.theme_edit.text(),
            'setting': self.setting_edit.text(),
            'genre': self.genre_combo.currentText(),
            'audience': self.audience_combo.currentText(),
            'author_voice': self.author_combo.currentText(),
            'num_pages': self.pages_spin.value(),
            'include_images': self.include_images.isChecked(),
            'image_freq': self.img_freq_combo.currentText(),
            'img_interval': self.img_interval_spin.value(),
            'color_style': self.color_combo.currentText(),
            'style_phrase': self.style_edit.text(),
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(self, 'Saved', 'Configuration saved.')
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Save failed: {e}')

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.text_provider_combo.setCurrentText(config.get('text_provider', 'Pollinations (Free)'))
                self.text_api_key.setText(config.get('text_api_key', ''))
                self.img_provider_combo.setCurrentText(config.get('image_provider', 'Pollinations (Free)'))
                self.img_api_key.setText(config.get('image_api_key', ''))
                self.theme_edit.setText(config.get('theme', ''))
                self.setting_edit.setText(config.get('setting', ''))
                self.genre_combo.setCurrentText(config.get('genre', 'Fantasy'))
                self.audience_combo.setCurrentText(config.get('audience', 'Young Adult'))
                self.author_combo.setCurrentText(config.get('author_voice', 'Default (Clean Prose)'))
                self.pages_spin.setValue(config.get('num_pages', 20))
                self.include_images.setChecked(config.get('include_images', False))
                self.img_freq_combo.setCurrentText(config.get('image_freq', 'none'))
                self.img_interval_spin.setValue(config.get('img_interval', 5))
                self.color_combo.setCurrentText(config.get('color_style', 'color'))
                self.style_edit.setText(config.get('style_phrase', ''))
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
            except Exception:
                pass

    def on_generate_clicked(self):
        if getattr(self, '_generation_running', False):
            return

        settings = {
            'theme': self.theme_edit.text().strip() or 'adventure',
            'setting': self.setting_edit.text().strip() or 'a fantasy world',
            'genre': self.genre_combo.currentText(),
            'audience': self.audience_combo.currentText(),
            'author_voice': self.author_combo.currentText() if self.author_combo.currentText() != 'Default (Clean Prose)' else '',
            'num_pages': self.pages_spin.value(),
            'include_images': self.include_images.isChecked(),
            'image_freq': self.img_freq_combo.currentText(),
            'img_interval': self.img_interval_spin.value(),
            'color_style': self.color_combo.currentText(),
            'style_phrase': self.style_edit.text().strip() or 'professional illustration',
            'text_model': self.text_model_combo.currentData() or '',
            'image_model': self.img_model_combo.currentData() or '',
        }

        if not self.text_router or not self.image_router:
            QMessageBox.warning(self, 'Error', 'Please test providers first.')
            return

        self.generate_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.pages_list.clear()
        self.page_text.clear()

        self._generation_running = True
        self.worker = GenerationWorker(settings, self.text_router, self.image_router)
        self.worker.signals.progress.connect(self.on_generation_progress)
        self.worker.signals.finished.connect(self.on_generation_finished)
        self.worker.signals.error.connect(self.on_generation_error)
        self.worker.signals.page_ready.connect(self.on_page_ready)
        self.thread_pool.start(self.worker)

    def on_cancel_clicked(self):
        if self.worker:
            self.worker.cancel()
            self.status_label.setText('Cancelling...')

    def on_generation_progress(self, msg: str):
        self.status_label.setText(msg)

    def on_page_ready(self, page_idx: int, text: str, img_url: str):
        item = QListWidgetItem(f'Page {page_idx+1}: {text[:60]}...')
        item.setData(Qt.UserRole, page_idx)
        self.pages_list.addItem(item)

    def on_generation_finished(self, book: Dict):
        self._generation_running = False
        self.current_book = book
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f'Done! {len(book.get("pages", []))} pages generated.')

        for i, page in enumerate(book.get('pages', [])):
            item = QListWidgetItem(f'Page {i+1}: {page["text"][:80]}...')
            item.setData(Qt.UserRole, i)
            self.pages_list.addItem(item)

        self.outline_tree.clear()
        for ch_idx, ch in enumerate(book.get('outline', [])):
            ch_item = QTreeWidgetItem([f'Chapter {ch_idx+1}: {ch.get("title", "")}', ''])
            for b_idx, beat in enumerate(ch.get('beats', [])):
                beat_item = QTreeWidgetItem([f'  Beat {b_idx+1}', beat])
                ch_item.addChild(beat_item)
            self.outline_tree.addTopLevelItem(ch_item)
        self.outline_tree.expandAll()

        self._refresh_registry()
        self._refresh_images_tab()
        self._populate_finished_tab(book)
        save_project_state({'book': book, 'settings': self._get_current_settings()})

    def on_generation_error(self, err: str):
        self._generation_running = False
        self.generate_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText('Error')
        QMessageBox.critical(self, 'Generation Failed', err)

    def _on_page_selected(self, row: int):
        if self.current_book and row >= 0:
            page = self.current_book['pages'][row]
            self.page_text.setPlainText(page['text'])
            if page.get('img_url'):
                self.page_text.append(f'\n\n[Image: {page["img_url"]}]')

    def _refresh_registry(self):
        self.char_tree.clear()
        if not self.current_book:
            return
        for c in self.current_book.get('characters', []):
            item = QTreeWidgetItem([c.get('name', ''), c.get('role', ''), ', '.join(c.get('traits', [])), 'active'])
            self.char_tree.addTopLevelItem(item)

    def _refresh_images_tab(self):
        while self.images_grid_layout.count():
            item = self.images_grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.current_book:
            return

        if self.current_book.get('cover_url'):
            cover_label = QLabel()
            pix = QPixmap(self.current_book['cover_url'])
            if not pix.isNull():
                cover_label.setPixmap(pix.scaledToWidth(300, Qt.SmoothTransformation))
            self.images_grid_layout.addWidget(QLabel('Cover:'))
            self.images_grid_layout.addWidget(cover_label)

        for i, page in enumerate(self.current_book.get('pages', [])):
            if page.get('img_url') and os.path.exists(page['img_url']):
                img_label = QLabel()
                pix = QPixmap(page['img_url'])
                if not pix.isNull():
                    img_label.setPixmap(pix.scaledToWidth(200, Qt.SmoothTransformation))
                self.images_grid_layout.addWidget(QLabel(f'Page {i+1}:'))
                self.images_grid_layout.addWidget(img_label)

    def _regenerate_outline(self):
        QMessageBox.information(self, 'Not Implemented', 'Regenerate outline with new prompt (TODO)')

    def _export_book_json(self):
        if not self.current_book:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Export Book JSON', 'book.json', 'JSON Files (*.json)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.current_book, f, indent=2, ensure_ascii=False)

    def _regenerate_current_page(self):
        QMessageBox.information(self, 'Not Implemented', 'Regenerate current page (TODO)')

    def _regenerate_cover(self):
        QMessageBox.information(self, 'Not Implemented', 'Regenerate cover (TODO)')

    def _regenerate_all_images(self):
        QMessageBox.information(self, 'Not Implemented', 'Regenerate all images (TODO)')

    def _get_current_settings(self) -> Dict:
        return {
            'theme': self.theme_edit.text(),
            'setting': self.setting_edit.text(),
            'genre': self.genre_combo.currentText(),
            'audience': self.audience_combo.currentText(),
            'author_voice': self.author_combo.currentText(),
            'num_pages': self.pages_spin.value(),
            'include_images': self.include_images.isChecked(),
            'image_freq': self.img_freq_combo.currentText(),
            'img_interval': self.img_interval_spin.value(),
            'color_style': self.color_combo.currentText(),
            'style_phrase': self.style_edit.text(),
        }

    def closeEvent(self, event):
        if getattr(self, '_generation_running', False):
            if self.worker:
                self.worker.cancel()
                self.thread_pool.waitForDone(3000)
        if self.current_book:
            save_project_state({'book': self.current_book, 'settings': self._get_current_settings()})
        event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = BookGeneratorApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()