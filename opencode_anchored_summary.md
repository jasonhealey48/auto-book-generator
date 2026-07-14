## Objective
- Merge LibriScribe multi-agent backend into PyQt5 Auto Book Generator GUI; author voice + audience drive generation end-to-end; cursor-following hover help; author visual-style in images; "Analyze Author" runtime voice research; Graphic Novel genre (panel script → art → editor lettering composite); hybrid genres (combine 2-3 genres, e.g. Graphic Novel + Fantasy); fix Pollinations text-generation returning helpdesk/meta replies; **graphic-novel exports that refuse to ship a skeleton (engine validate + retry, image retry/raise, audience-aware image directives, chapter strip + page-number badge lettered into the art, visual doctrine for cross-page character/location consistency, Pollinations dropped when Google Nano Banana is active); image-routing settings pinned to global config (not overwritten by project file); auto-launch non-blocking (no startup modal dialog blocking the main window).**

## Important Details
- **Architecture**: `ProjectKnowledgeBase` canonical backend; legacy `book` dict canonical GUI/export; bridge = `BookEngine.to_legacy_book_json()`. TWO gen paths: (1) Engine path = `EngineGenerationWorker` → `BookEngine` (GUI default); (2) Legacy path = `GenerationWorker._run_generation` → `generate_full_book_json`. Both feed `_generate_images` (graphic → `_generate_graphic_novel`).
- **GUI startup** — `_load_config(silent=True)` is now called on construction (was previously non-silent, blocking on a `QMessageBox.information(...)` modal so the main window never appeared). The user-facing "Load Config" button still emits the modal confirmation by passing the default `silent=False`. Result: window pops up in ~15s instead of waiting indefinitely until the user clicks an invisible dialog.
- **Project restore pins image-routing keys** — `_restore_project` filters the project's `settings` dict before calling `_apply_config`. **Image-routing keys** (`image_provider`, `image_model`, `image_api_key`, `use_vertex_ai`, `vertex_project_id`, `vertex_location`, `text_provider`, `text_model`, `text_api_key`) are stripped — those stay sourced from `book_config.json`. **Content keys** (`theme`, `setting`, `genre`, `audience`, `author_voice`, `num_pages`, `include_images`, `image_freq`, `img_interval`, `color_style`, `style_phrase`, `review_preference`, `worldbuilding_needed`) still flow through. Verified in test: a project with stale `image_provider: "Pollinations (Free)"` no longer overwrites the global Banana.
- **Visual doctrine strengthened** (`_build_visual_doctrine`) — emits a structured per-character + per-location anchor: `• CHARACTERS: - Name: face + hair + clothing + props + role (keep this look across every page)` and an identical structure for LOCATIONS, preceded by a strong header ("VISUAL DOCTRINE — every page MUST match this exactly. Do not vary face, hair, clothing, palette, props, scene, or composition across the book. Re-use the same character illustration verbatim unless the scene explicitly demands a change."). No new schemas; pure text-only prompt engineering.
- **Pipeline order (engine path, `book_generator.py` `_run_generation`)**: concept → characters → worldbuilding (if enabled) → outline (informed by characters/world blocks) → chapters → `to_legacy_book_json` → [graphic-minimums gate raised if no real prose] → `_generate_images`. Characters/worldbuilding BEFORE outline (cast/world essential to outline).
- **Hybrid genres**: Genre UI is checkable `QListWidget` (`self.genre_list`); `selected_genres()` returns comma-joined string (e.g. `"Graphic Novel, Fantasy"`); stored in `settings['genre']` / `kb.genre`. `_is_graphic(genre)` is hybrid-aware (`"Graphic Novel" in comma-split list`).
- **Engine never exports a skeleton (Block 1)** — `book_engine.py`:
  - `_SCAFFOLD_LOGLINE = {"", "no logline available", "n/a"}`, `_SCAFFOLD_BEATS = {"the story continues with new developments.", "a new chapter in the unfolding story.", ...}`.
  - `_is_real_logline` / `_is_real_beat` detect placeholder text vs real narrative (≥20 chars non-scaffold).
  - `validate_real_content(kb, genre)` returns a list of issue strings (empty = OK); checked for: logline real, description real, chapters non-empty, every chapter summary non-scaffold, scene summaries non-scaffold, plus "graphic-novel must have characters" if `_is_graphic`.
  - `stage_with_retry(stage, fn, kb, genre)` runs a stage once, validates output; on scaffold issues retries **once**; still scaffold → raise `ContentGenerationError(stage, issues)`. The single-retry mode matches user decision (Q7).
- **Image generation never leaves a page blank (Block 2)** — `book_generator.py:_generate_graphic_novel`:
  - 3-attempt loop per page (same prompt, then simplified) with `time.sleep(1.0)` between attempts; on all 3 failures raises `ImageGenerationFailed(idx+1, last_err)`.
  - Module-level `ImageGenerationFailed(RuntimeError)` carries a 1-based page index + message; engine's `stage_failed` signal surfaces it precisely.
  - **If graphic-novel page text is empty** (after skipping the existing "no text" path), the engine raises a `RuntimeError` in `_generate_graphic_novel` (Block 7 minimums gate in `_run_generation`).
- **Drop Pollinations when Vertex Banana is on (Block 3)** — `_drop_pollinations_when_banana_active(configs, banana_enabled)`:
  - Applied at both image-router build sites (`_probe_image_one` and `_apply_config`). When `image_provider` contains "Google", Pollinations is filtered out of `self.image_router.configs` entirely.
  - (Per user Q3 = "Disable Pollinations when banana is on".) When the user picks a non-Banana provider, Pollinations can rejoin.
- **Audience-aware visual art (Block 4)**:
  - 5-bucket tables matching the existing `AUDIENCES = ["Children", "Middle Grade", "Young Adult", "Adult", "All Ages"]`:
    - `AUDIENCE_VISUAL_GUIDANCE` — visual tone ceiling per bucket (e.g. Children = "soft peril ... no realistic blood";
      Adult = "frank violence: beheading, dismemberment when story demands"; etc.).
    - `AUDIENCE_VIOLENCE_FORBIDDEN` — bucket-specific FORBIDDEN clauses (Children: severed body parts, blood pools, modern firearms; YA: sexualized violence; etc.).
    - `AUTHOR_CHAPTER_HEADER` — controls whether the chapter strip is lettered: **Children=False**, the rest=True.
  - `_audience_image_directive(audience)` returns a single-line directive suitable for prompt injection; non-empty for the 5 named buckets, "" otherwise.
  - `_chapter_header_enabled(audience)` returns whether the chapter strip is drawn for that audience.
  - **All engine-path art-prompts** (image_freq=easy/every_n/every_chapter + cover + `_generate_graphic_novel` panel + cover) inject `{audience_directive}` between `author_art_hint` and `genre`.
- **Chapter strip + page badge IN the art (Block 5)** — `_letter_gn_image`:
  - Signature: `_letter_gn_image(img_path, script, *, draw_chapter_strip=False, chapter_label="", page_index=None, total_pages=None)`.
  - **Chapter strip** (top-left header on first page of each new chapter): transparent black bar (~7% H) with white text from `chapter_label[:90]`. Skipped entirely when `audience == "Children"` (via `_chapter_header_enabled`). When skipped, the narrator bar replaces it as the topmost element.
  - **Page-number badge** (bottom-right, always on): colored pill rendering `Page N / M`. Uses Windows Segoe UI / Arial / Consolas via `_load_pil_font(size)`; falls back to PIL default on non-Windows.
  - Existing narrator caption bar + speech-bubble ellipses preserved. Verified visually: smoke-rendered lettered PNG shows "Chapter 1: The Awakening" header + bubbles + "1 / 6" badge.
- **Visual doctrine for cross-page consistency (Block 6)** — `_build_visual_doctrine(book)`:
  - Pulls `book["characters"][:3]` and `book["locations"][:2]`; assembles `"VISUAL DOCTRINE — keep all character/location features IDENTICAL across every page: <name>: <phys_desc>; ...; Location <name>: <desc>; ..."`.
  - Stored in `EngineGenerationWorker._visual_doctrine` after `to_legacy_book_json`. Prepended to every art prompt with a "Maintain the canonical look above" cross-page directive. If structured data is empty, logs a progress message and the prompt degrades to style-only.
- **Graphic-novel content minimums (Block 7)** — `_collect_graphic_minimum_issues(book)`:
  - For graphic-novel genre, requires: ≥1 page; zero pages with empty text; zero pages whose text is a known scaffold (`"[scene content unavailable]"`, `"the story continues..."`, `"a new chapter..."`, etc.) or a 40-char-or-less **Scene** scaffold; ≥1 character.
  - Surfaced as `RuntimeError` from `_run_generation`. The engine-path NEVER exports a skeleton.
- **Hybrid-detection**: `_is_graphic(genre)` is in `book_generator.py`, `book_engine.py`, `libriscribe/agents/outliner.py`, `chapter_writer.py`.
- **GENRE_GUIDANCE**: `_genre_guidance(genre)` joins guidance for every selected genre. `get_author_voice(name, genre)` tolerates joined genre.
- **Graphic image ordering (legacy)**: `_generate_graphic_novel` skips empty-text pages and uses `_parse_panel_script_text` if `[Panel`/`VISUAL:` present.
- **Voice adaptation**: `voice_directive()` binds author style to audience age range; audience constraints take priority.
- **Image providers**: Pollinations `flux`+`enhance=true`+1024 + shared `IMAGE_QUALITY_SUFFIX`/`IMAGE_NEGATIVE`; applied to StableHorde + NanoBanana. `AuthorVoice.visual_style` injected via `_author_art_hint()` → art prompts.
- **`research_author_voice(name, llm_fn)`**: GUI `author_search` + `analyze_author_btn` + `AuthorResearchWorker` wired. `llm_fn` = `BookGeneratorApp._llm_text(prompt, system="")` → returns `res.text` (NOT ProviderResult). Hardened: coerces `out` to str + passes a system prompt. NOTE: there are TWO `_llm_text` — engine (~L429) returns string from `client.generate_content`; app (~L1319) returns `res.text` from `router.complete`.
- **PIL** v12.3; `_letter_gn_image` now draws chapter strip, narrator caption bar, speech bubbles, page badge.
- **Pollinations text bug**: `f8ff9bb` — `_pollinations_generate` sends a system message; `LLMClient._is_degenerate` (staticmethod) + guard in `generate_content` raises on helpdesk/meta replies. NOTE: keep `_is_degenerate` and `generate_content` BOTH 4-indented inside `class LLMClient` — a 0-indent module-level helper before a 4-indent method nests the method invisibly.
- **Vertex/GCP**: `aiplatform.googleapis.com` enabled on project `gen-lang-client-0397607711` (state=ENABLED); ADC = `jasonhealey48@gmail.com`. GUI configured: `image_provider=Google Nano Banana`, `use_vertex_ai=True`, `vertex_project_id=gen-lang-client-0397607711`, region `us-central1`, model `gemini-3.1-flash-image` (Nano Banana 2 default).
- **Git**: `https://github.com/jasonhealey48/auto-book-generator`, git at `C:\Program Files\Git\cmd\git.exe`.

## Work State
### Completed
- All 6 agents voice-injected; `voice_lead` fixed; `BookEngine.create_project` populates author/tone/audience; `to_legacy_book_json` carries `author_voice` + splits graphic chapters on `"[Panel"`.
- 6 children voices + `Children` bucket; `AuthorVoice.visual_style` + 6 children + DEFAULT_PROSE; `_author_art_hint()`.
- Hover help box; Analyze Author UI + `research_author_voice` wired.
- Hybrid genres: multi-select QListWidget; `_is_graphic` hybrid-aware in 4 files; `_genre_guidance` joins; dedupe GENRES.
- Graphic image ordering: skip empty-text pages; reuse panel script via `_parse_panel_script_text`.
- Pollinations text fix (`f8ff9bb`, pushed): system msg + `_is_degenerate` guard.
- Analyze Author fix (`abdba90`, pushed): `_llm_text` returns `res.text`; hardened `research_author_voice`.
- **Block 1 (engine scaffold refuses)** — `_SCAFFOLD_LOGLINE`/`_SCAFFOLD_BEATS`/`validate_real_content`/`stage_with_retry`/`ContentGenerationError` in `book_engine.py`. `book_generator.py:_run_generation` graphic gate via `_collect_graphic_minimum_issues`.
- **Block 2 (image retries + raise)** — `_generate_graphic_novel` retries 3x then `raise ImageGenerationFailed(idx+1, msg)`. `ImageGenerationFailed(RuntimeError)` defined at module scope.
- **Block 3 (drop Pollinations when Banana on)** — `_drop_pollinations_when_banana_active` invoked in both image-router build sites.
- **Block 4 (audience-aware art)** — `AUDIENCE_VISUAL_GUIDANCE`, `AUDIENCE_VIOLENCE_FORBIDDEN`, `AUTHOR_CHAPTER_HEADER`, `_audience_image_directive`, `_chapter_header_enabled`; audience directive injected into all engine-path art prompts (image_freq branches + cover + `_generate_graphic_novel` panel + cover).
- **Block 5 (chapter strip + page badge)** — `_letter_gn_image` extended with `draw_chapter_strip`/`chapter_label`/`page_index`/`total_pages`; chapter strip gated by `_chapter_header_enabled` (Children=False); page-number badge always on; `_load_pil_font` honors Windows Segoe UI/Arial/Consolas. Smoke-tested visually.
- **Block 6 (visual doctrine)** — `_build_visual_doctrine` assembles a 2–6 sentence doctrine from `book["characters"]`/`book["locations"]`; stored in `EngineGenerationWorker._visual_doctrine`; prepended to art prompts with "canonical look" reinforcement.
- **Block 7 (graphic content minimums)** — `_collect_graphic_minimum_issues` rejects scaffolding pages + empty characters in graphic-novel genre.
- **Block 8 (regression)** — 17/17 `unittest` pass; both files compile clean.
- **Block 9 (anchor)** — this file updated.
- **v7 fix (project-restore pin)** — `_restore_project` filters `image_provider`/`image_model`/`image_api_key`/`use_vertex_ai`/`vertex_project_id`/`vertex_location`/`text_provider`/`text_model`/`text_api_key` from the project's settings before calling `_apply_config`. Content keys still flow through. Verified: stale `image_provider: "Pollinations (Free)"` in `book_project.json` never overwrites the global Banana choice.
- **v7 visual-doctrine strengthening** — `_build_visual_doctrine` emits a structured per-character + per-location anchor with a strong header line. Pure text-only; no schemas added.
- **v7 GUI-startup non-blocking** — `_load_config(silent=True)` is now called from construction; the modal `QMessageBox.information("Loaded", ...)` no longer fires on auto-load. User-click "Load Config" still emits the confirmation. Verified: window up after ~15 seconds instead of blocked indefinitely.
- **Commits on origin/main**: `1b2f5dd`, `428123b`, `2608c4e`, `fa907a2`, `f8ff9bb`, `abdba90`, `765bfd1`, `8290605` — all pushed.
- **Verification**: `py_compile` clean on `book_generator.py` + `book_engine.py`; 17/17 `python -m unittest`; smoke test of audience/doctrine/Pollinations-drop/lettering all green; GUI window up at "Auto Book Generator" with PID 10736 hwnd 3738134.

### Active
- (none; Book app ready for image generation).

### Blocked
- (none).

## Next Move
1. Live Graphic Novel + Fantasy smoke test (3 chapters, Adult audience, R.A. Salvatore author) → confirm full prose, real panel dialogue, every page lettered with chapter strip + page badge, image filenames prefixed `nano_` (Vertex Banana) not `poll_`.
2. Optional: turn rector the `_letter_gn_image` narrator-bar to render UNDER the chapter strip instead of right after it (already implemented; verify visually on first live generation).

## Relevant Files
- `C:/Users/jason/OneDrive/Desktop/bgee/book_generator.py` — GUI; engine path `_run_generation`; `EngineGenerationWorker._audience_for`, `_visual_doctrine`, `_author_art_hint`, `_load_pil_font`, `_letter_gn_image` (Block 5), `_generate_graphic_novel` (Blocks 2/4/5/6); module-level `_audience_image_directive`/`_chapter_header_enabled`/`AUDIENCE_VISUAL_GUIDANCE`/`AUDIENCE_VIOLENCE_FORBIDDEN`/`AUTHOR_CHAPTER_HEADER`; `_build_visual_doctrine`/`_drop_pollinations_when_banana_active`/`_collect_graphic_minimum_issues`; `ImageGenerationFailed` class; `_load_config(silent=...)`, `_restore_project` filtered-settings restore (v7).
- `C:/Users/jason/OneDrive/Desktop/bgee/book_engine.py` — Bridge; `_SCAFFOLD_LOGLINE`/`_SCAFFOLD_BEATS`/`_is_real_logline`/`_is_real_beat`/`validate_real_content`/`stage_with_retry`/`ContentGenerationError`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/utils/llm_client.py` — `f8ff9bb` Pollinations fix: system msg + `_is_degenerate` (staticmethod) + guard in `generate_content`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/voice.py` — `voice_directive`, `derive_tone`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/utils/voice_prefix.py` — `voice_lead`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/utils/prompts_context.py` — `OUTLINE_PROMPT`/`GRAPHIC_OUTLINE_PROMPT` (characters_block/worldbuilding_block); `GRAPHIC_SCENE_PROMPT`, `CHARACTER_PROMPT`, `WORLDBUILDING_PROMPT`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/agents/outliner.py` — `_is_graphic`; `_characters_block`/`_worldbuilding_block`; graphic branch; `_panels_to_scenes`.
- `C:/Users/jason/OneDrive/Desktop/bgee/libriscribe/src/libriscribe/agents/chapter_writer.py` — `_is_graphic`; graphic branch.
- `C:/Users/jason/OneDrive/Desktop/bgee/author_voices.py` — children voices, `visual_style`, `research_author_voice`, `DEFAULT_PROSE`, `get_author_voice` (tolerant of joined genre).
- `C:/Users/jason/OneDrive/Desktop/bgee/image_providers.py` — `IMAGE_QUALITY_SUFFIX`, `IMAGE_NEGATIVE`, Pollinations flux/enhance/1024, `GoogleNanoBananaProvider` (Vertex AI path), `NANO_BANANA_MODELS` includes "Nano Banana Lite".
- `C:/Users/jason/OneDrive/Desktop/bgee/book_config.json` — `image_provider=Google Nano Banana`, `use_vertex_ai=True`, `vertex_project_id=gen-lang-client-0397607711`, `vertex_location=us-central1`, model `gemini-3.1-flash-image` (Nano Banana 2).
