"""
BookEngine — bridge between LibriScribe multi-agent backend and PyQt5 GUI.

Emits Qt signals for all progress/status updates so the GUI can connect
without importing any LibriScribe internals.
"""

import sys
import os
import json
import time
import logging
from pathlib import Path
from typing import Dict, Optional, Any

from PyQt5.QtCore import QObject, pyqtSignal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "libriscribe", "src"))

from libriscribe.agents.project_manager import ProjectManagerAgent
from libriscribe.knowledge_base import (
    ProjectKnowledgeBase, Character, Chapter, Scene, Worldbuilding
)
from libriscribe.utils.llm_client import LLMClient
from libriscribe.utils.model_routing import SUPPORTED_PROVIDERS
from libriscribe.settings import Settings
from libriscribe.workflow_state import inspect_project_progress, ProjectProgress
from libriscribe.voice import derive_tone
from author_voices import get_author_voice

logger = logging.getLogger(__name__)


PROVIDER_DISPLAY_NAMES = {
    "pollinations": "Pollinations",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA NIM",
    "huggingface": "HuggingFace",
    "google_ai_studio": "Google Gemini",
    "groq": "Groq",
    "openai": "OpenAI",
    "claude": "Claude",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
}


class BookEngine(QObject):
    """Multi-agent book generation engine backed by LibriScribe."""

    stage_started = pyqtSignal(str, str)
    stage_completed = pyqtSignal(str)
    stage_failed = pyqtSignal(str, str)
    progress = pyqtSignal(str)
    chapter_ready = pyqtSignal(int, str)
    book_ready = pyqtSignal(dict)
    cost_update = pyqtSignal(float)
    concept_ready = pyqtSignal(dict)
    outline_ready = pyqtSignal(str)
    characters_ready = pyqtSignal(dict)
    worldbuilding_ready = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pm: Optional[ProjectManagerAgent] = None
        self._kb: Optional[ProjectKnowledgeBase] = None
        self._project_dir: Optional[Path] = None
        self._settings: Dict[str, Any] = {}
        self._cancelled = False

    @property
    def is_configured(self) -> bool:
        return self._pm is not None and self._pm.llm_client is not None

    @property
    def project_dir(self) -> Optional[Path]:
        return self._project_dir

    def configure(self, provider: str, api_key: str = "", model: str = "",
                  extra_settings: Optional[Dict] = None):
        """Configure the engine with a text provider."""
        self.progress.emit(f"Configuring {PROVIDER_DISPLAY_NAMES.get(provider, provider)}...")

        if not self._pm:
            self._pm = ProjectManagerAgent(llm_client=None)

        key_attr = (
            "google_ai_studio_api_key"
            if provider == "google_ai_studio"
            else f"{provider}_api_key"
        )
        if api_key:
            os.environ[key_attr.upper()] = api_key
        if model:
            model_attr = f"{provider}_model"
            os.environ[model_attr.upper()] = model

        self._pm.initialize_llm_client(provider, model if model else None)

        if model and self._pm.llm_client:
            self._pm.llm_client.set_model(model)

        self.progress.emit(f"Configured: {PROVIDER_DISPLAY_NAMES.get(provider, provider)} / {model or 'default'}")

    def configure_from_gui(self, settings: Dict[str, Any]):
        """Configure from GUI settings dict (from _get_current_settings)."""
        provider = settings.get("text_provider", "pollinations")
        api_key = settings.get("text_api_key", "")
        model = settings.get("text_model", "")
        self.configure(provider, api_key, model)
        self._settings = settings

    def create_project(self, project_name: str, book_settings: Dict[str, Any]):
        """Initialize a new project."""
        self.progress.emit("Creating project...")

        genre = book_settings.get("genre", "Fantasy")
        audience = book_settings.get("audience", "Adult")
        author_name = book_settings.get("author_voice", "")
        theme = book_settings.get("theme", "")
        setting = book_settings.get("setting", "")
        description = book_settings.get("description", "") or f"{theme}. {setting}"
        num_pages = book_settings.get("num_pages", 12)
        title = book_settings.get("title", "Untitled")

        author = get_author_voice(author_name, genre)

        review_preference = str(book_settings.get("review_preference", "AI")).strip()
        if review_preference.lower().startswith("human"):
            review_preference = "Human"
        else:
            review_preference = "AI"

        self._kb = ProjectKnowledgeBase(
            project_name=project_name,
            title=title,
            genre=genre,
            category="Fiction",
            description=description,
            num_characters=3,
            worldbuilding_needed=book_settings.get("worldbuilding_needed", False),
            review_preference=review_preference,
            book_length=self._estimate_book_length(num_pages),
            num_chapters=self._estimate_chapters(num_pages),
            target_audience=audience,
            tone=derive_tone(audience),
            author_voice=author.name,
            author_style=author.style,
            author_donts=author.donts,
            author_exemplar=author.exemplar,
        )

        if self._pm:
            self._pm.initialize_project_with_data(self._kb)
            self._project_dir = self._pm.project_dir

        self.progress.emit(f"Project '{project_name}' created")
        return self._kb

    def _estimate_book_length(self, num_pages: int) -> str:
        if num_pages <= 5:
            return "Short Story (1-3 chapters)"
        elif num_pages <= 20:
            return "Novella (5-8 chapters)"
        elif num_pages <= 50:
            return "Novel (15+ chapters)"
        else:
            return "Full Book (Non-Fiction)"

    def _estimate_chapters(self, num_pages: int) -> int:
        if num_pages <= 5:
            return max(1, num_pages)
        elif num_pages <= 20:
            return max(3, num_pages // 3)
        else:
            return max(5, num_pages // 4)

    def generate_concept(self):
        """Generate book concept using ConceptGeneratorAgent."""
        if not self._pm or not self._kb:
            self.stage_failed.emit("concept", "Project not initialized")
            return

        self._cancelled = False
        self.stage_started.emit("concept", "Generating concept...")
        try:
            self._pm.generate_concept()
            self._pm.checkpoint()
            self.stage_completed.emit("concept")

            result = {
                "title": self._kb.title,
                "logline": self._kb.logline,
                "description": self._kb.description,
            }
            self.concept_ready.emit(result)
        except Exception as e:
            self.stage_failed.emit("concept", str(e))

    def generate_outline(self):
        """Generate outline using OutlinerAgent."""
        if not self._pm or not self._kb:
            self.stage_failed.emit("outline", "Project not initialized")
            return

        self._cancelled = False
        self.stage_started.emit("outline", "Generating outline...")
        try:
            self._pm.generate_outline()
            self._pm.checkpoint()
            self.stage_completed.emit("outline")
            self.outline_ready.emit(self._kb.outline)
        except Exception as e:
            self.stage_failed.emit("outline", str(e))

    def generate_characters(self):
        """Generate character profiles using CharacterGeneratorAgent."""
        if not self._pm or not self._kb:
            self.stage_failed.emit("characters", "Project not initialized")
            return

        self._cancelled = False
        self.stage_started.emit("characters", "Generating characters...")
        try:
            self._pm.generate_characters()
            self._pm.checkpoint()
            self.stage_completed.emit("characters")

            chars = {}
            for name, char in self._kb.characters.items():
                chars[name] = {
                    "name": char.name,
                    "role": char.role,
                    "age": char.age,
                    "physical_description": char.physical_description,
                    "personality_traits": char.personality_traits,
                    "background": char.background,
                    "motivations": char.motivations,
                }
            self.characters_ready.emit(chars)
        except Exception as e:
            self.stage_failed.emit("characters", str(e))

    def generate_worldbuilding(self):
        """Generate worldbuilding details using WorldbuildingAgent."""
        if not self._pm or not self._kb:
            self.stage_failed.emit("worldbuilding", "Project not initialized")
            return

        self._cancelled = False
        self.stage_started.emit("worldbuilding", "Generating worldbuilding...")
        try:
            self._pm.generate_worldbuilding()
            self._pm.checkpoint()
            self.stage_completed.emit("worldbuilding")

            if self._kb.worldbuilding:
                wb = self._kb.worldbuilding.model_dump()
                wb = {k: v for k, v in wb.items() if v}
                self.worldbuilding_ready.emit(wb)
        except Exception as e:
            self.stage_failed.emit("worldbuilding", str(e))

    def write_chapter(self, chapter_number: int):
        """Write a single chapter (with review + edit + style editing)."""
        if not self._pm or not self._kb:
            self.stage_failed.emit("chapter", f"Chapter {chapter_number}: not initialized")
            return

        self._cancelled = False
        chapter = self._kb.get_chapter(chapter_number)
        title = chapter.title if chapter else f"Chapter {chapter_number}"
        self.stage_started.emit("chapter", f"Writing Chapter {chapter_number}: {title}")

        try:
            self._pm.write_and_review_chapter(chapter_number)
            self._pm.checkpoint()
            self.stage_completed.emit("chapter")

            chapter_path = self._project_dir / f"chapter_{chapter_number}.md"
            if chapter_path.exists():
                content = chapter_path.read_text(encoding="utf-8")
                self.chapter_ready.emit(chapter_number, content)
        except Exception as e:
            self.stage_failed.emit("chapter", str(e))

    def write_all_chapters(self, total_chapters: int):
        """Write all chapters sequentially."""
        for i in range(1, total_chapters + 1):
            if self._cancelled:
                self.progress.emit("Generation cancelled")
                return
            self.write_chapter(i)

    def write_chapters_in_background(self, total_chapters: int):
        """Write chapters in background thread (called from QRunnable)."""
        self.write_all_chapters(total_chapters)

    def cancel(self):
        """Cancel ongoing generation."""
        self._cancelled = True
        self.progress.emit("Cancelling...")

    def resume(self):
        """Resume from last checkpoint."""
        if not self._pm or not self._kb or not self._project_dir:
            self.stage_failed.emit("resume", "No project to resume")
            return

        self.progress.emit("Inspecting project progress...")
        progress = inspect_project_progress(self._project_dir, self._kb)

        if progress.next_step == "complete":
            self.progress.emit("Project already complete!")
            return

        self.progress.emit(f"Resuming from: {progress.next_step}")

        if not progress.concept_complete:
            self.generate_concept()

        if not progress.outline_complete:
            self.generate_outline()

        if progress.characters_required and not progress.characters_complete:
            self.generate_characters()

        if progress.worldbuilding_required and not progress.worldbuilding_complete:
            self.generate_worldbuilding()

        if progress.missing_chapters:
            for ch_num in progress.missing_chapters:
                if self._cancelled:
                    return
                self.write_chapter(ch_num)

    def get_chapter_content(self, chapter_number: int) -> str:
        """Read chapter content from disk."""
        if not self._project_dir:
            return ""
        chapter_path = self._project_dir / f"chapter_{chapter_number}.md"
        if chapter_path.exists():
            return chapter_path.read_text(encoding="utf-8")
        return ""

    def get_outline_text(self) -> str:
        """Get outline as text."""
        if self._kb and self._kb.outline:
            return self._kb.outline
        return ""

    def get_characters_dict(self) -> Dict:
        """Get characters as dict."""
        if not self._kb:
            return {}
        return {
            name: {
                "name": char.name,
                "role": char.role,
                "age": char.age,
                "physical_description": char.physical_description,
                "personality_traits": char.personality_traits,
                "background": char.background,
                "motivations": char.motivations,
                "relationships": char.relationships,
            }
            for name, char in self._kb.characters.items()
        }

    def get_worldbuilding_dict(self) -> Dict:
        """Get worldbuilding as dict."""
        if self._kb and self._kb.worldbuilding:
            wb = self._kb.worldbuilding.model_dump()
            return {k: v for k, v in wb.items() if v}
        return {}

    def save_project(self):
        """Save project state."""
        if self._pm:
            self._pm.save_project_data()

    def load_project(self, project_name: str):
        """Load an existing project."""
        if not self._pm:
            self._pm = ProjectManagerAgent(llm_client=None)

        try:
            self._pm.load_project_data(project_name)
            self._kb = self._pm.project_knowledge_base
            self._project_dir = self._pm.project_dir
            self.progress.emit(f"Loaded project: {project_name}")
        except Exception as e:
            self.stage_failed.emit("load", str(e))

    def export_manuscript(self, output_path: str, output_format: str = "markdown"):
        """Export book to markdown or PDF."""
        if not self._pm or not self._project_dir:
            self.stage_failed.emit("export", "No project loaded")
            return

        self.stage_started.emit("export", f"Exporting to {output_format}...")
        try:
            self._pm.format_book(output_path)
            self.stage_completed.emit("export")
            self.progress.emit(f"Exported to: {output_path}")
        except Exception as e:
            self.stage_failed.emit("export", str(e))

    def to_legacy_book_json(self) -> Dict:
        """Convert LibriScribe's ProjectKnowledgeBase to our legacy book JSON format."""
        if not self._kb:
            return {}

        chapters = []
        for ch_num in sorted(self._kb.chapters.keys()):
            ch = self._kb.chapters[ch_num]
            beats = []
            for scene in ch.scenes:
                beats.append(scene.summary)
            chapters.append({
                "title": ch.title,
                "beats": beats or [ch.summary],
            })

        characters = []
        for name, char in self._kb.characters.items():
            characters.append({
                "id": name.lower().replace(" ", "_"),
                "name": char.name,
                "role": char.role,
                "traits": [t.strip() for t in char.personality_traits.split(",") if t.strip()] if char.personality_traits else [],
                "description": char.background or char.physical_description,
            })

        pages = []
        flat_beats = []

        for ch_num in sorted(self._kb.chapters.keys()):
            ch = self._kb.chapters[ch_num]
            chapter_path = None
            if self._project_dir:
                chapter_path = self._project_dir / f"chapter_{ch_num}.md"
            chapter_text = ""
            if chapter_path and chapter_path.exists():
                chapter_text = chapter_path.read_text(encoding="utf-8").strip()

            if chapter_text:
                is_graphic = self._kb.genre == "Graphic Novel"
                if is_graphic and "[Panel" in chapter_text:
                    scene_texts = [seg.strip() for seg in chapter_text.split("[Panel") if seg.strip()]
                else:
                    scene_texts = [seg.strip() for seg in chapter_text.split("**Scene ") if seg.strip()]
                if scene_texts:
                    for idx, segment in enumerate(scene_texts):
                        text = segment if idx == 0 and chapter_text.startswith("**Scene ") else (
                            f"**Scene {segment}" if not segment.startswith("**Scene ") else segment
                        )
                        beat_text = ch.scenes[idx].summary if idx < len(ch.scenes) else ch.summary
                        flat_beats.append({"ch": ch_num - 1, "beat": beat_text, "title": ch.title})
                        pages.append({
                            "text": text.strip(),
                            "img_url": None,
                            "chapter": ch.title,
                        })
                else:
                    flat_beats.append({"ch": ch_num - 1, "beat": ch.summary, "title": ch.title})
                    pages.append({
                        "text": chapter_text,
                        "img_url": None,
                        "chapter": ch.title,
                    })
            else:
                for idx, scene in enumerate(ch.scenes):
                    flat_beats.append({"ch": ch_num - 1, "beat": scene.summary, "title": ch.title})
                    pages.append({
                        "text": scene.summary,
                        "img_url": None,
                        "chapter": ch.title,
                    })

        book_json = {
            "metadata": {
                "title": self._kb.title,
                "blurb": self._kb.description,
                "audience": self._kb.target_audience,
                "genre": self._kb.genre,
                "author_voice": getattr(self._kb, "author_voice", "") or "",
                "theme": self._kb.logline,
                "setting": "",
                "total_pages": sum(len(ch.scenes) for ch in self._kb.chapters.values()) or 12,
                "target_words": sum(len(ch.scenes) for ch in self._kb.chapters.values()) * 250 or 3000,
            },
            "characters": characters,
            "locations": [],
            "items": [],
            "plot_threads": [],
            "key_questions": [],
            "chapter_summaries": [],
            "outline": chapters,
            "flat_beats": flat_beats,
            "pages": pages,
            "cover_url": None,
            "images": [],
        }

        if self._kb.worldbuilding:
            wb = self._kb.worldbuilding.model_dump()
            for key, val in wb.items():
                if val:
                    book_json["locations"].append({"name": key, "description": val})

        return book_json
