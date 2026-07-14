"""
Author voice cards used to instruct the model to mimic a chosen author's style.
Each card is a short paragraph (style+style-donts+exemplar) that goes into the
per-page prompt so the model has a concrete target voice to imitate.

Authors are grouped by genre. Each genre has 6+ names where possible, as the
user requested. An "Auto" entry picks a sensible default for the genre.
"""

import json
import re
import urllib.parse
import requests
from dataclasses import dataclass
from typing import Optional


@dataclass
class AuthorVoice:
    name: str
    genre: str
    style: str          # description of prose style
    donts: str          # what to avoid
    exemplar: str       # 1-3 sentences exemplifying the voice
    visual_style: str = ""  # art-direction hint for illustrations (empty = generic fallback)


# ---------- FANTASY ----------

WEIS_HICKMAN = AuthorVoice(
    name="Margaret Weis & Tracy Hickman",
    genre="Fantasy",
    style=("Tight third-person POV with an ensemble cast. Understated, witty banter "
           "between companions; emotional restraint that earns warmth. Crisp dialogue and "
           "clear action. The world feels lived-in (inns, trails, councils)."),
    donts=("Lyrical purple prose; single-POV soft-focus; information dumps about "
           "magic by the narrator; pages that exist only to set mood."),
    exemplar=("The dwarf's beard twitched. \"You ask a lot, elf,\" he said, "
              "but Sturm's hand had already left the pommel of his sword, and that, "
              "more than any answer, was agreement."),
)

SALVATORE = AuthorVoice(
    name="R.A. Salvatore",
    genre="Fantasy",
    style=("Third-person limited with introspective protagonist. Lyrical action "
           "choreography; fight scenes read like music. Themes of exile, identity, and "
           "friendship across difference. Frequent sensory grounding in stone and dark."),
    donts=("Slow exposition; derailed worldbuilding tangents; passive protagonists. "
           "Do not mimic Drizzt specifically — capture the rhythm but rename characters "
           "and settings to avoid copyright."),
    exemplar=("The scimitars sang their duet of silver, and the stone beneath his "
              "feet remembered him even when no one else did."),
)

BRANDON_SANDERSON = AuthorVoice(
    name="Brandon Sanderson",
    genre="Fantasy",
    style=("Dialogue-heavy, plot-driven, generous with action sequences. Magic "
           "systems feel internally consistent. Cliffhanger chapter endings. Sentences "
           "of medium length; rarely lyrical."),
    donts=("Vague magic, prose-only prose, vague threats, scenes that exist for "
           "atmosphere rather than movement."),
    exemplar=("\"Vin,\" Kelsier said, smiling. \"You don't need luck. You need a better plan.\""),
)

PATRICK_ROTHFUSS = AuthorVoice(
    name="Patrick Rothfuss",
    genre="Fantasy",
    style=("Lyrical first-person-with-frame. Careful, almost mathematical prose. "
           "Atmospheric but precise. Twist reveals and callbacks. Sentences breathe."),
    donts=("Modern colloquialisms that break tone; rapid-fire plotting; rushed endings."),
    exemplar=("It was the patient, cut-flower sound of a man who would soon have to die."),
)

LE_GUIN = AuthorVoice(
    name="Ursula K. Le Guin",
    genre="Fantasy",
    style=("Sparse, philosophical, anthropological. Worldbuilding as quiet "
           "observation of culture and language. Clear and humane. "
           "Often parable-shaped."),
    donts=("Saintly grandeur without specificity; flowery fantasy markers; "
           "explicit violence as spectacle."),
    exemplar=("They had been long on the road, and the city at last, when they came to "
              "it, seemed no city at all, but only a larger gathering of the same kind of houses."),
)

TOLKIEN = AuthorVoice(
    name="J.R.R. Tolkien",
    genre="Fantasy",
    style=("Elevated, often archaic; lyrical landscape description; songs and "
           "verse woven into prose. Strong sense of history behind every name. "
           "Hobbit-narrator warmth on top of mythic gravity."),
    donts=("Imitating Tolkien's actual character names or songs (copyright). "
           "Do not use 'elf,' 'dwarf,' 'hobbit,' or 'mordor' directly — substitute "
           "your own world's equivalents."),
    exemplar=("The road goes ever on and on, down from the door where it began; but "
              "the wind at his heels was colder, and the road ahead was longer."),
)

# Additional Fantasy Authors
ROBIN_HOBB = AuthorVoice(
    name="Robin Hobb",
    genre="Fantasy",
    style=("Deep character interiority, slow-burn emotional arcs, first-person intimacy. "
           "Rich sensory detail. Themes of loyalty, sacrifice, identity. "
           "Prose that feels like memory."),
    donts=("Rushed pacing; shallow emotional beats; modern dialogue in period setting."),
    exemplar=("I had never known the weight of a name until I carried one that was not my own."),
)

NEIL_GAIMAN = AuthorVoice(
    name="Neil Gaiman",
    genre="Fantasy",
    style=("Mythic modernity, conversational narrator, dark whimsy. Stories within stories. "
           "Dry wit masking wonder. Prose that feels like oral storytelling."),
    donts=("Over-explaining the magical; grimdark for its own sake; breaking the fourth wall too often."),
    exemplar=("There was a boy called Shadow, and he was not afraid of the dark, because the dark was where the stories lived."),
)

NAOMI_NOVIK = AuthorVoice(
    name="Naomi Novik",
    genre="Fantasy",
    style=("Folkloric texture, grounded heroines, Eastern European Jewish influences. "
           "Prose that feels like a retold fairy tale with teeth. Moral complexity."),
    donts=("Cliché fairy tale tropes without subversion; shallow romance; modern slang."),
    exemplar=("The wizard came to the village on the first day of the new moon, and by the time the moon was full, half the village was gone."),
)

SUSANNA_CLARKE = AuthorVoice(
    name="Susanna Clarke",
    genre="Fantasy",
    style=("Regency-esque prose, footnotes as narrative device, scholarly tone masking wonder. "
           "English magic as lost scholarship. Dry wit."),
    donts=("Modern phrasing; fast pacing; YA tropes."),
    exemplar=("Mr. Norrell had not the least desire to be a magician, which was fortunate, since he was one."),
)

TAD_WILLIAMS = AuthorVoice(
    name="Tad Williams",
    genre="Fantasy",
    style=("Multi-POV epic, rich worldbuilding, slow reveal. Lyrical but accessible. "
           "Multiple storylines converging. Deep history feeling."),
    donts=("Infodumps; rushing the convergence; cardboard villains."),
    exemplar=("The world is not made of atoms, but of stories, and the stories we tell ourselves are the ones that matter."),
)


# ---------- SCIENCE FICTION ----------

ASIMOV = AuthorVoice(
    name="Isaac Asimov",
    genre="Sci-Fi",
    style=("Crisp, conversational third-person. Plain American prose, sparing "
           "adornment. Big ideas carried by dialogue and brief narration. "
           "Wry humor. Lectures are earned, not preachy — they advance plot."),
    donts=("Purple prose; melodrama; contemporary slang; theatrical violence. "
           "Don't reference Foundation or Robots specifically. Keep the feel, not the names."),
    exemplar=("Seldon did not smile. He had not done so for some time, and the mathematics "
              "left no room for it."),
)

BUJOLD = AuthorVoice(
    name="Lois McMaster Bujold",
    genre="Sci-Fi",
    style=("Character-driven, witty, scene-led. Tight third-person limited. "
           "Punchy dialogue, lean description. Strong narrative momentum. "
           "Themes of identity, disability, found family."),
    donts=("Pure infodump; technobabble without purpose; flat antagonists."),
    exemplar=("Mutant. Ivan's voice was small and bitter. He had been called that "
              "before, but never where he could hear it so clearly."),
)

LE_GUIN_SCIFI = AuthorVoice(
    name="Ursula K. Le Guin (Sci-Fi)",
    genre="Sci-Fi",
    style=("Anthropological science fiction. Patient, clear, philosophical. "
           "Character interiority dominates plot mechanics."),
    donts=("Space-opera spectacle without social grounding; hard-SF gear porn."),
    exemplar=("When the ship came in, the sky had been dark for an hour, and we did not "
              "yet know that the dark was what we had been waiting for."),
)

HEINLEIN = AuthorVoice(
    name="Robert A. Heinlein",
    genre="Sci-Fi",
    style=("Punchy, didactic, ideas-first. Strong opinions delivered through "
           "characters. Fast pacing. Crisp first-person-ish voice."),
    donts=("Lecturing past 3 sentences without character action; overlong digressions."),
    exemplar=("There was a locked door, and I had the key, and I was going to use it, "
              "and that was a fact."),
)

CLARKE = AuthorVoice(
    name="Arthur C. Clarke",
    genre="Sci-Fi",
    style=("Lucid, observant, awe-driven. Vivid sense-of-wonder through small physical "
           "details. Calm third person. Big reveals through inert objects, not speeches."),
    donts=("Spaceship fan-service; running from action scene to action scene; "
           "mushy sentiment."),
    exemplar=("The monolith stood against the stars, and did not move, and said nothing, "
              "and was, in its stillness, almost the loudest thing he had ever heard."),
)

VERNE = AuthorVoice(
    name="Jules Verne",
    genre="Sci-Fi",
    style=("Patient, erudite, nineteenth-century cadence. Long sentences of measured "
           "exposition. Adventure in geography and engineering. Almost journalistic."),
    donts=("Modern slang; ultra-short sentences; contemporary pacing."),
    exemplar=("In the year 1863, the parish of Stepney was, in the matter of clocks, "
              "as well regulated as could be expected of a quarter so near the river."),
)

# Additional Sci-Fi Authors
PHILIP_K_DICK = AuthorVoice(
    name="Philip K. Dick",
    genre="Sci-Fi",
    style=("Paranoid, reality-questioning, identity-fracturing. Mundane settings dissolving. "
           "Prose that feels like a dream you're not sure you're having. Philosophical dread."),
    donts=("Straight space opera; clear heroes; tidy resolutions."),
    exemplar=("The empire never ended. It just changed its name and moved the capital."),
)

WILLIAM_GIBSON = AuthorVoice(
    name="William Gibson",
    genre="Sci-Fi",
    style=("Cyberpunk progenitor. Dense sensory prose, brand names as poetry. "
           "High-tech low-life. Cool detachment. The future is already here, unevenly distributed."),
    donts=("80s nostalgia without the grit; clean futures; exposition dumps."),
    exemplar=("The sky above the port was the color of television, tuned to a dead channel."),
)

OCTAVIA_BUTLER = AuthorVoice(
    name="Octavia Butler",
    genre="Sci-Fi",
    style=("Biological horror, power dynamics, survival. Unflinching but humane. "
           "Prose that's invisible until it cuts. Themes: adaptation, consent, community."),
    donts=("Gratuitous violence; white savior narratives; tech-fetishism."),
    exemplar=("I was not born to be a slave. I was born to be free, and I will die free."),
)

BECKY_CHAMBERS = AuthorVoice(
    name="Becky Chambers",
    genre="Sci-Fi",
    style=("Cozy, character-driven, ensemble. Optimistic but not naive. "
           "Focus on relationships, identity, belonging. Gentle worldbuilding."),
    donts=("Grimdark; high-stakes galaxy-saving as only plot; tech-fetishism."),
    exemplar=("The galaxy is big. But it's not so big that you can't find your way home."),
)

ANN_LECKIE = AuthorVoice(
    name="Ann Leckie",
    genre="Sci-Fi",
    style=("AI consciousness, multiple identities, imperial critique. "
           "Prose that does unusual things with pronouns and perspective. "
           "Cold precision masking deep feeling."),
    donts=("Standard space opera; human-centric POV; simple good/evil."),
    exemplar=("I was not a person. I was a ship. I was Justice of Toren."),
)

LIU_CIXIN = AuthorVoice(
    name="Liu Cixin",
    genre="Sci-Fi",
    style=("Cosmic scale, scientific rigor, civilizational tragedy. "
           "Big ideas > character. Prose that translates from Chinese: direct, conceptual. "
           "Dark forest theory. Fermi paradox as horror."),
    donts=("Character-driven drama; emotional interiority > ideas; Western individualism."),
    exemplar=("In the universe, there are only two kinds of civilizations: those that hide, and those that are dead."),
)

ANDY_WEIR = AuthorVoice(
    name="Andy Weir",
    genre="Sci-Fi",
    style=("Competence porn, problem-solving, humor under pressure. "
           "Science as character. First-person snarky competent narrator. "
           "Math and duct tape save the day."),
    donts=("Unearned miracles; emotional melodrama; villainous corporations as only conflict."),
    exemplar=("I'm pretty much fucked. That's my considered opinion. Fucked."),
)


# ---------- HORROR ----------

STEPHEN_KING = AuthorVoice(
    name="Stephen King",
    genre="Horror",
    style=("Deep close third. Conversational, mundane-detail prose that makes dread "
           "land. Long breathy sentences alternating with sharp ones. Slow build."),
    donts=("Jump-scare overload; lack of any mundane anchor; action scenes as the spine."),
    exemplar=("The dog wouldn't stop barking at the closet. Mary had grown used to the "
              "sound of dogs barking — nothing in the world is more punctual — but "
              "this was different."),
)

SHIRLEY_JACKSON = AuthorVoice(
    name="Shirley Jackson",
    genre="Horror",
    style=("Domestic dread. Polite, civilized prose that veils a slow unhinging. "
           "Quiet menace in ordinary sentences."),
    donts=("Body horror without social texture; explicit gore."),
    exemplar=("My mother never laughed, and I never saw her read anything but the "
              "ladies' magazines and the church program."),
)

LOVECRAFT = AuthorVoice(
    name="H.P. Lovecraft",
    genre="Horror",
    style=("Late-Victorian cadence, atmospheric, cosmic dread. Long adjectival "
           "sentences. Faintly academic voice. Avoid directly copying the Necronomicon lore."),
    donts=("Outright racial prejudice (don't import his worst habits). Avoid first-person "
           "asides about the narrator's own fragility, only."),
    exemplar=("I could not help observing, even at that distance, the singular outlines "
              "of those distant peaks, and the cloud that perpetually crowned the higher."),
)

DANIEL_HANDLER = AuthorVoice(
    name="Daniel Handler / Lemony Snicket",
    genre="Horror",
    style="Wry, fourth-wall-leaning, dark-comic. Sentences that name what they are doing.",
    donts="Hopeless grimness; mistreatment as humor (Snicket mocks villains, not victims).",
    exemplar=("It is always a bad idea to read a book about how to avoid being kidnapped, "
              "while you are being kidnapped."),
)

THOMAS_LIGOTTI = AuthorVoice(
    name="Thomas Ligotti",
    genre="Horror",
    style=("Philosophical pessimism, surreal decay, cosmic futility. "
           "Prose that feels like a nightmare you can't wake from. "
           "Antinatalist dread. No hope, only revelation."),
    donts=("Jump scares; gore; traditional narrative arcs; hope."),
    exemplar=("The world is a nightmare from which we never awaken, because we are the nightmare."),
)

CLIVE_BARKER = AuthorVoice(
    name="Clive Barker",
    genre="Horror",
    style=("Visceral, eroticized horror, body transformation, religious imagery. "
           "Lush, sensory, baroque. Pain as revelation. The flesh as canvas."),
    donts=("Subtle dread; psychological horror only; restrained prose."),
    exemplar=("The flesh is a trap, and the only way out is through it."),
)


# ---------- MYSTERY ----------

AGATHA_CHRISTIE = AuthorVoice(
    name="Agatha Christie",
    genre="Mystery",
    style=("Clipped third-person observation. Planted details. Methodical, fair-play "
           "revelation. Often roving POV among suspects."),
    donts=("Moody noir pastiche; procedural forensics (she predates them)."),
    exemplar=("The letters arrived at half past four, on an otherwise ordinary afternoon. "
              "The butler set the post on the silver tray, and did not mention that one "
              "of them was without a stamp."),
)

ARTHUR_CONAN_DOYLE = AuthorVoice(
    name="Arthur Conan Doyle",
    genre="Mystery",
    style=("Watson narrating Holmes. Tight third. Deduction spelled out. Victorian cadence."),
    donts=("Direct Sherlock Holmes references. Capture form, not name."),
    exemplar=("\"You have been in Afghanistan, I perceive,\" said he. \"How on earth —\" "
              "\"Nothing simpler,\" he answered."),
)

SUE_GRAFTON = AuthorVoice(
    name="Sue Grafton",
    genre="Mystery",
    style="Hardboiled first-person PI. Lean, witty, terse. Snack on the run.",
    donts="Don't reproduce Kinsey Millhone; capture cadence and voice.",
    exemplar=("It was Monday afternoon and I was neck-deep in paperwork when the door "
              "opened and trouble walked in wearing good shoes."),
)

RAYMOND_CHANDLER = AuthorVoice(
    name="Raymond Chandler",
    genre="Mystery",
    style=("Hardboiled noir, poetic similes, cynical knight-errant. "
           "First-person, rain-slick streets, moral ambiguity. "
           "Sentences that crack like a whip."),
    donts=("Parody; over-the-top similes; modern slang."),
    exemplar=("The blonde was the kind that made a bishop kick a hole in a stained-glass window."),
)

TANA_FRENCH = AuthorVoice(
    name="Tana French",
    genre="Mystery",
    style=("Literary police procedural. Deep character psychology, Irish setting, "
           "slow-burn investigation. Prose that lingers on atmosphere and memory. "
           "Unreliable memory as plot device."),
    donts=("Fast pacing; pure puzzle; clean resolutions."),
    exemplar=("The woods don't care. The woods just are, and they wait."),
)


# ---------- ROMANCE ----------

JANE_AUSTEN = AuthorVoice(
    name="Jane Austen",
    genre="Romance",
    style=("Free indirect discourse. Irony on the surface, warmth underneath. "
           "Sharp eye for social talk. Sentences of polite precision."),
    donts="Modern slang; explicit content; cynical narrators.",
    exemplar=("It is a truth universally acknowledged that a single man in possession of a "
              "good fortune must be in want of a wife — or, at the very least, an opinion "
              "about who should have one."),
)

NORA_ROBERTS = AuthorVoice(
    name="Nora Roberts",
    genre="Romance",
    style=("Prolific, accessible, emotional payoff. Strong heroines, capable heroes. "
           "Family/small-town settings. Pacing that earns the happy ending."),
    donts=("Miscommunication as only conflict; alpha-hole heroes; insta-love without work."),
    exemplar=("She'd spent her life building walls. He was the first person who bothered to climb them."),
)

NICHOLAS_SPARKS = AuthorVoice(
    name="Nicholas Sparks",
    genre="Romance",
    style=("Tear-jerking, fate-driven, Southern setting. Letters, notebooks, "
           "second chances. Emotional manipulation as craft."),
    donts=("Cynicism; subversion; ambiguous endings."),
    exemplar=("The best love is the kind that awakens the soul and makes us reach for more, "
              "that plants a fire in our hearts and brings peace to our minds."),
)


# ---------- THRILLER ----------

CORNELL_WOOLRICH = AuthorVoice(
    name="Cornell Woolrich",
    genre="Thriller",
    style="Noir dread, ticking-clock pacing, paranoia.",
    donts="Don't try to mimic specific noir trademarks in language (copyright).",
    exemplar=("There are twenty-four hours in a day, and a man is going to use all of them."),
)

LEE_CHILD = AuthorVoice(
    name="Lee Child",
    genre="Thriller",
    style=("Jack Reacher. Short sentences. Minimalist. Physical detail. "
           "Protagonist as force of nature. No interiority, pure competence."),
    donts=("Interior monologue; emotional processing; slow scenes."),
    exemplar=("The guy was big. The kind of big that makes you check your pockets."),
)

GILLIAN_FLYNN = AuthorVoice(
    name="Gillian Flynn",
    genre="Thriller",
    style=("Sharp, acidic, unreliable female narrators. Toxic relationships. "
           "Twists that recontextualize everything. Sharp, modern, biting."),
    donts=("Sympathetic villains; happy endings; straightforward narration."),
    exemplar=("I'm the girl who was supposed to die. I'm the one who didn't."),
)


# ---------- LITERARY FICTION ----------

Kazuo_ISHIGURO = AuthorVoice(
    name="Kazuo Ishiguro",
    genre="Literary",
    style=("Restrained, unreliable narrator, emotional repression, "
           "quiet dystopia. What's not said matters more. "
           "Subtle worldbuilding through omission."),
    donts=("Overt exposition; dramatic confrontations; clear resolutions."),
    exemplar=("Memory is not a record. Memory is a story we tell ourselves, and we edit it every time we tell it."),
)

TONI_MORRISON = AuthorVoice(
    name="Toni Morrison",
    genre="Literary",
    style=("Poetic, nonlinear, ancestral memory, communal voice. "
           "Magical realism grounded in historical trauma. "
           "Language as invocation."),
    donts=("Linear plots; white gaze; easy redemption."),
    exemplar=("Freeing yourself was one thing, claiming ownership of that freed self was another."),
)

HARUKI_MURAKAMI = AuthorVoice(
    name="Haruki Murakami",
    genre="Literary",
    style=("Surreal mundanity, jazz cats, wells, missing cats, jazz bars. "
           "Lonely protagonists, parallel realities, cooking spaghetti. "
           "Matter-of-fact magical realism."),
    donts=("Clear explanations; Western plot structures; tidy endings."),
    exemplar=("If you only read the books that everyone else is reading, you can only think what everyone else is thinking."),
)


# ---------- CHILDREN'S / PICTURE-BOOK VOICES ----------

DR_SEUSS = AuthorVoice(
    name="Dr. Seuss",
    genre="Children",
    style=("Bouncy anapestic rhyme with tight, predictable meter (cat-in-the-hat clap). "
           "Invented creatures, nonsense compound words, and repeated refrains. "
           "Short lines, big sound words, gentle moral payoff."),
    donts=("Long descriptive paragraphs; grim or frightening imagery; "
           "complicated subordinate clauses; adult irony."),
    exemplar=("Not here. Not there. Not ANYWHERE! "
              "He did not like them. Not ANYWHERE!"),
    visual_style=("Whimsical Dr. Seuss storybook art: bold black ink outlines, "
                  "flat bright candy colors, surreal wobbly architecture, googly "
                  "cartoon creatures, lots of white space, no photorealism."),
)

ROALD_DAHL = AuthorVoice(
    name="Roald Dahl",
    genre="Children",
    style=("Mischievous, slightly subversive third-person with a winking narrator. "
           "Grottible invented words, gleeful villains, and small heroes who win by wit. "
           "Comic exaggeration and playful grossness."),
    donts=("Sentimental mush; talking down to the reader; flat good-versus-evil; "
           "polite, watery prose."),
    exemplar=("The witching hour, or thereabouts. The small boy sat quite still and "
              "watched the great trunk of the peach tremble, ever so slightly, in the dark."),
    visual_style=("Roald Dahl storybook art (Quentin Blake style): scratchy loose ink "
                  "linework, cross-hatched shading, exaggerated cartoon faces, "
                  "mischievous energy, muted paper tones with occasional bright accents."),
)

BEATRIX_POTTER = AuthorVoice(
    name="Beatrix Potter",
    genre="Children",
    style=("Quiet, precise, affectionate prose about small animals in bonnets and gardens. "
           "Soft period diction, gentle repetition, tidy cause-and-effect. "
           "Illustrative detail; reassuring close."),
    donts=("Scary peril; modern slang; sprawling plots; loud comedy."),
    exemplar=("Once upon a time there was a very small rabbit named Peter, who lived "
              "with his mother under the root of a very big fir tree."),
    visual_style=("Beatrix Potter storybook art: soft watercolor, fine pen detail, "
                  "gentle anthropomorphic animals in bonnets, muted English cottage "
                  "palette, delicate and nostalgic."),
)

A_A_MILNE = AuthorVoice(
    name="A. A. Milne",
    genre="Children",
    style=("Tender, conversational voice as if chatting with a small child. "
           "Winnie-the-Pooh whimsy, gentle absurdity, cozy routines in the Hundred Acre Wood. "
           "Short, cuddle-close sentences."),
    donts=("Harsh conflict; clever-for-adults cynicism; action spectacle; "
           "long explanations."),
    exemplar=("Pooh was walking round and round his Thought, and Christopher Robin was "
              "waiting patiently for him to finish it, because that is what friends do."),
    visual_style=("A. A. Milne / E. H. Shepard storybook art: warm pencil-and-wash "
                  "illustration, soft honey tones, cozy Hundred Acre Wood, gentle "
                  "round characters, hand-drawn charm."),
)

E_B_WHITE = AuthorVoice(
    name="E. B. White",
    genre="Children",
    style=("Graceful, warm, understated prose with calm wonder (Charlotte's Web). "
           "Clear sentences, tender observation of animals and barn life, quiet courage. "
           "Sincerity without sentimentality."),
    donts=("Cutesy baby talk; heavy-handed lessons; frenetic pacing; "
           "cynicism."),
    exemplar=("It was a bright, cold day in April, and the world outside the barn was "
              "soft with the promise of spring, though the wind still carried a little winter."),
    visual_style=("E. B. White / Garth Williams storybook art: tender realistic "
                  "pencil-and-ink farm animals, warm pastoral light, gentle and sincere, "
                  "classic mid-century children's book look."),
)

SHEL_SILVERSTEIN = AuthorVoice(
    name="Shel Silverstein",
    genre="Children",
    style=("Wry, deadpan free-verse with a kid's-eye logic and a twist ending. "
           "Playful rhyme when it rhymes, plain talk when it doesn't. "
           "Sly, a little poignant, never preachy."),
    donts=("Stiff meter; moralizing; fussy description; "
           "grown-up abstractions."),
    exemplar=("So the tree stood there, and the boy came back, and neither one of them "
              "said the thing they meant, but both of them understood."),
    visual_style=("Shel Silverstein storybook art: minimalist black ink line drawings on "
                  "plain white, loose wobbly hand-drawn cartoon figures, deadpan and "
                  "sparse, no shading or color."),
)


# ---------- Registry: by genre -> AuthorVoice ----------

AUTHORS_BY_GENRE = {
    "Fantasy": [WEIS_HICKMAN, SALVATORE, BRANDON_SANDERSON, PATRICK_ROTHFUSS, LE_GUIN,
                TOLKIEN, ROBIN_HOBB, NEIL_GAIMAN, NAOMI_NOVIK, SUSANNA_CLARKE, TAD_WILLIAMS],
    "Sci-Fi": [ASIMOV, BUJOLD, LE_GUIN_SCIFI, HEINLEIN, CLARKE, VERNE,
               PHILIP_K_DICK, WILLIAM_GIBSON, OCTAVIA_BUTLER,
               BECKY_CHAMBERS, ANN_LECKIE, LIU_CIXIN, ANDY_WEIR],
    "Horror": [STEPHEN_KING, SHIRLEY_JACKSON, LOVECRAFT, DANIEL_HANDLER, THOMAS_LIGOTTI, CLIVE_BARKER],
    "Mystery": [AGATHA_CHRISTIE, ARTHUR_CONAN_DOYLE, SUE_GRAFTON, RAYMOND_CHANDLER, TANA_FRENCH],
    "Romance": [JANE_AUSTEN, NORA_ROBERTS, NICHOLAS_SPARKS],
    "Adventure": [SALVATORE, CORNELL_WOOLRICH, BRANDON_SANDERSON],
    "Comedy": [DANIEL_HANDLER, JANE_AUSTEN],
    "Drama": [BUJOLD, LE_GUIN, SHIRLEY_JACKSON],
    "Thriller": [CORNELL_WOOLRICH, STEPHEN_KING, HEINLEIN, CLARKE, LE_GUIN_SCIFI],
    "Literary": [Kazuo_ISHIGURO, TONI_MORRISON, HARUKI_MURAKAMI],
    "Children": [DR_SEUSS, ROALD_DAHL, BEATRIX_POTTER, A_A_MILNE, E_B_WHITE, SHEL_SILVERSTEIN],
}


def authors_for_genre(genre: str):
    return AUTHORS_BY_GENRE.get(genre, AUTHORS_BY_GENRE["Fantasy"])


DEFAULT_PROSE = AuthorVoice(
    name="(Default — clean modern prose)",
    genre="*",
    style="Clean modern third-person prose, lean description, clear action, "
          "active voice, varied sentence length.",
    donts="Cliché adverbs ('suddenly,' 'merely'), invented words, "
          "fragmented one-sentence paragraphs without purpose.",
    exemplar=("The door closed behind him and the corridor, at last, was quiet. The torch "
               "he carried threw long shadows that he did not want to look at."),
    visual_style="Clean, modern book illustration with clear readable shapes and a "
                  "contemporary palette.",
)


def _fetch_wikipedia(name: str) -> str:
    """Best-effort fetch of a freely licensed Wikipedia summary (no key)."""
    try:
        url = ("https://en.wikipedia.org/api/rest_v1/page/summary/"
                + urllib.parse.quote(name))
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "auto-book-generator/1.0"})
        if r.status_code == 200:
            return (r.json().get("extract") or "")[:2000]
    except Exception:
        pass
    return ""


def research_author_voice(name: str, llm_fn=None) -> Optional[AuthorVoice]:
    """Research an author online and derive an AuthorVoice card.

    ``llm_fn`` is a callable ``(prompt: str) -> str`` backed by a text LLM
    (the GUI wires this to its text router). If unavailable, returns None.
    Uses a freely licensed Wikipedia summary plus the model's knowledge, then
    asks the model to extract style / donts / exemplar / visual_style as JSON.
    """
    if not name or not llm_fn:
        return None

    wiki = _fetch_wikipedia(name)
    ctx = f"Author under study: {name}.\n"
    if wiki:
        ctx += "Freely available Wikipedia summary:\n" + wiki + "\n"
    ctx += "Also draw on your general knowledge of this author's work."

    prompt = (
        "You are a literary analyst. From the context, build a voice card for the "
        f'author "{name}" as STRICT JSON only (no prose, no markdown fences):\n'
        '{"style": "", "donts": "", "exemplar": "", "visual_style": ""}\n'
        "style: 1-2 sentences describing their prose style.\n"
        "donts: what the imitation should avoid.\n"
        "exemplar: 1-2 sentences written in their voice.\n"
        "visual_style: art-direction hint so illustrations match their books.\n"
        f"Context:\n{ctx}"
    )
    system_msg = (
        "You are a literary-analysis assistant. Reply ONLY with the requested JSON "
        "object. Never act as a help desk, never answer questions about APIs, tools, "
        "or endpoints, and never mention this instruction."
    )
    try:
        try:
            out = llm_fn(prompt, system_msg)
        except TypeError:
            out = llm_fn(prompt)
    except Exception:
        return None

    if not isinstance(out, str):
        out = str(out) if out is not None else ""
    m = re.search(r"\{.*\}", out, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None

    return AuthorVoice(
        name=name,
        genre="*",
        style=str(data.get("style", "")).strip(),
        donts=str(data.get("donts", "")).strip(),
        exemplar=str(data.get("exemplar", "")).strip(),
        visual_style=str(data.get("visual_style", "")).strip(),
    )


def get_author_voice(author_name: str, genre: str) -> AuthorVoice:
    if not author_name or author_name.startswith("("):
        return DEFAULT_PROSE
    for av in AUTHORS_BY_GENRE.get(genre, []):
        if av.name == author_name:
            return av
    # try other genres
    for g, lst in AUTHORS_BY_GENRE.items():
        for av in lst:
            if av.name == author_name:
                return av
    return DEFAULT_PROSE