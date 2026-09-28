<p align="center"><img src="assets/icon/png/concept-trail-128.png" width="104" alt="Concept Trail"></p>

# Concept Trail

**English** · [Türkçe](README.tr.md) · **[Introduction: what it solves, with a worked example](docs/INTRODUCTION.md)**

*A thinking workspace for software ideas: it asks the open questions before you build, researches who already built it, and never writes into your notes without your approval.*

**Install on Windows** (paste into PowerShell, no admin rights needed):

```powershell
irm https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.ps1 | iex
```

**Install on macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.sh | bash
```

When a software idea first comes to mind it is still vague, full of open questions we cannot yet see the shape of — and that is exactly when we start building. Later we run into those open ends, and because we never thought them through, a critical problem forces us to restructure the project, sometimes the whole system.

**Concept Trail is a tool made to remove that problem.** You write your idea in a note; the assistant asks questions that narrow the idea from broad to specific, talks your answers through, researches who has already built what — and the note always stays yours.

---

## How it works

### The note is watched while you write
When you **pause for 15 seconds** or **paste something**, the assistant quietly reads your note and finds what is missing or still open. It never interrupts your writing: its questions wait in the panel on the right instead of popping up cards. Live watch is switched on and off from the status bar, and `Ctrl+Enter` asks at any moment.

**How many questions to ask is the model's call.** It is told how you are keeping up — how many questions wait, how long the oldest has waited, how many you settled lately — and paces itself: while there is much to talk through and you keep answering, it keeps asking; when unanswered questions pile up, it asks only what matters. In a chat it decides the same way when an answer is clear enough. There is no fixed cap; the code only keeps a fuse against a model gone wrong.

### Questions go from broad to narrow: the decision ladder
A software note climbs four rungs, and the assistant only asks about the open decisions of the rung it is on:

| Rung | Decisions |
|---|---|
| **Scope** | goal · user · platform · runtime |
| **Architecture** | main parts · data · communication · external dependencies |
| **Components** | responsibilities · interfaces · failure |
| **Details** | technology · edge cases · verification · deployment |

It never asks about a decision the note already states (it records it in the note's own words); your answer becomes the value of that decision and the next questions build on it. When all fifteen decisions are made, the note is announced as having reached the **product phase**. Every decision on the roadmap card is a chip: if the model got one wrong, you can mark it or take it back.

### A chat for every question
Answer a question with one line in the panel, or open a chat for it. Anything unclear is talked through there; when the assistant reaches a conclusion it **asks for your approval** before adding it to the note. If you don't like it, nothing is added and the chat goes on. A new question born from an answer hangs under its parent question, and the chat knows the earlier conversation of that branch.

### The model's suggestions, seen through different lenses
Each round, in turn, the eyes of an **Architect, Product, Security & Operations** and **Developer** critique the note and may suggest a concrete argument worth adding or a risk that was missed ("Since the family will share it, every receipt should be tagged with whose expense it is"). Suggestions never enter the note without approval either, and generic advice does not count as a suggestion.

### Correct the course
Following only the model's questions can pull the idea away from where you want it. **Correct course** lets you steer freely: the assistant compares your correction with the project's goal and the decisions already made, shows the new course in a short summary and lists what it would change — decisions whose value your correction states are updated, decisions it affects are asked again, conflicting questions are closed. Nothing happens until you approve; untick any item you don't want.

### The idea tree: a constellation
The note is a bright star in the middle; its questions, suggestions and chats branch out from it ray by ray. **Questions waiting for an answer glow**, with light flowing along their strings; resolved ones settle into a calm light. The strings are real ropes: pick up a star and drag it and it pulls the others along; let go and it swings back into place. Pan the sky and whatever hangs in it lags behind and sways. Text only appears when you hover over a star. Click a star and its card grows out of it; the path from the note to that star lights up while the rest of the sky dims. Clicking empty space shrinks the card back into its star. **N** (or "Next question") flies to the next question waiting for an answer. Behind it all, a sky that is never quite still: drifting clouds of gas, the Milky Way, layers of stars at different depths, a bright star flaring now and then, shooting stars — and it follows the theme: a clear night, a forest night with fireflies, a dusk with embers over a warm horizon, a sepia star chart, a polar night with an aurora, plain black for high contrast. Zooming never shakes the tree; panning only sways it as the pan sets off and stops. When a note first opens, the stars light up from the centre outwards and the strings draw themselves out.

### Master prompt
One button (**Ctrl Shift M**, "Master prompt" in the title bar): the note, the roadmap decisions, the questions you answered, the suggestions you approved and rejected, and the research become instructions a coding agent (such as Claude Code or Codex) can follow to build the app end to end **without asking a single question**: product summary, scope, tech stack (with versions), architecture, data model, API contracts, screens, errors and edge cases, security, folder structure, milestones, tests and acceptance criteria, setup. Whatever the note leaves open, the model decides itself and lists under **Assumptions** with its reasons; the dialog shows those decisions first. If a line still ends in a question mark or puts a decision off, a second short call settles it. The button lights up when the note reaches the product phase, but it works at any time. In any of five languages; copy it, save it as a new note or download it as .md. The last one is kept with the note. It has its own job in the model settings ("Master prompt"; if left empty, the research judgements' model).

### Research: has this idea been built already?
After a short summary of your idea, GitHub and the web are searched for who has built it before — along several paths (topics, keywords, popularity, READMEs, "alternatives", "Show HN"); what is found is ranked by how many independent paths found it. Libraries for the parts of the idea are searched separately. Suitable pages and READMEs are opened and read (pages drawn with JavaScript through a browser layer).

**Competitor analysis:** the closest projects are examined up close — activity, licence, recent issues (why their users complain), README and website. The model compares them with your idea: a table of which parts of your idea each project has, partly has or lacks; what each project shares with your idea, what it lacks, its weak point and the lesson to take from it; **points that set your idea apart** and **arguments for improving it**. If the assistant notices a topic in your note that others may have solved, it can suggest the research itself.

Findings you choose are added to the note only with your approval. No result ever claims your idea is "original": not showing up in a search is not proof of absence.

---

## Languages
The interface comes in five languages — English, Deutsch, Español, Français and Türkçe — chosen from the globe button in the title bar. **The assistant's language** can be set separately: questions, suggestions, chat answers and text for the note are written in it (by default the same as the interface). The master prompt can be written in any of the five as well. Your notes and chats are never translated.

## Themes
The theme button in the title bar offers seven themes — Paper, Forest night, **Constellation** (the same night sky as the idea tree), Sunset, Parchment (a preview that reads like a printed page), Glacier and High contrast. Hovering over a theme shows the whole app in it; a click chooses it, and the change fades in smoothly.

---

## Model-independent
The assistant is not tied to one model. Any OpenAI-compatible endpoint works: **OpenRouter** (by default a cheap, fast model such as `openai/gpt-4o-mini`), another cloud API, or a **local llama.cpp / ik_llama** server. The work is split into roles — *analysis* (note watch, research), *chat*, *summary*, *research judgements*, *master prompt* — and each role is bound to a chain of providers in the settings; if the first is down, the next one takes over.

Chosen by measurement: across the same five scenarios GPT-4o-mini found 14 of the 14 decisions stated in the notes and invented none, at about 2 s and $0.0002 a round. Local models that think at length get a thinking budget; the parsers also hold up with models that answer without thinking.

**Spending guard:** OpenRouter reports the real cost of every request; daily dollar, request and token limits can be changed in the settings (default: $0.50 a day).

## Privacy
- The app only runs on `127.0.0.1`; other websites cannot send requests through your browser.
- A note with `private: true` (or `gizli: true`) in its frontmatter is never sent to remote models and never researched.
- The assistant **never writes to your note on its own**; every addition and edit is a suggestion.
- API keys live in the operating system's settings folder (`%APPDATA%\ConceptTrail`), not next to your notes.

---

## Installation

### One command
**Windows** (paste into PowerShell; no admin rights needed):

```powershell
irm https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.ps1 | iex
```

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/Haci-brt/concept-trail/main/install.sh | bash
```

The command downloads the app (to `%LOCALAPPDATA%\Programs\ConceptTrail` on Windows, `~/.local/share/concept-trail` elsewhere), sets up its own Python environment, puts **a Concept Trail shortcut with the app icon on the desktop and in the Start menu**, and opens the app. It needs Python 3.10+; on Windows it offers to install it with winget if it is missing. Your notes live in **Documents\Concept Trail**. To update, run the same command again — the code is replaced, your notes and the environment are kept. To uninstall, delete the app folder and the shortcuts; your notes stay where they are.

> Tested on Windows. The macOS and Linux script follows the same steps but has not been tried on those platforms yet; the Windows-specific parts of web search and the desktop card may not work there.

### By hand (for development)

```bash
pip install -r requirements.txt
python main.py              # desktop window + always-on-top assistant card
python main.py --browser    # in your default browser
python main.py --server     # server only
python scripts/make_shortcut.py   # desktop and Start menu shortcut with the app icon
```

On first start a short wizard connects the assistant to a model: **OpenRouter** with a key (recommended; a link takes you to the key page), a model **already running on this computer** (Ollama, LM Studio and llama.cpp are found on their usual ports), or **any other OpenAI-compatible service**. It makes one real call before saving anything, so a wrong key or model name is said in plain words right there. Put aside, it waits behind the model button in the title bar; Settings → Models has it too, next to the full provider editor. Notes live in `./notes` by default (change it with `--vault`).

The research tools are built into the app and need nothing else installed:
- **GitHub** (`server/github.py`): public repositories only, respects GitHub's rate limits, caches results for an hour. A token is optional (entered in the settings); with one, searches run 2 s apart, without one 6 s apart.
- **Web search** (`server/websearch.py`): drives a Chromium-family browser already on your computer — Opera, Edge (which every Windows has), Chrome, Brave or Chromium, the first one found — with a fresh empty profile, never yours; on Windows its window is hidden, elsewhere it runs headless. With no browser at all it searches without one, through DuckDuckGo's page for browsers without JavaScript. To pick a browser, point `CT_BROWSER` at its executable. It can be switched off in the research panel.
- **Page reading** (`server/fetch.py`): pages drawn with JavaScript need `playwright install chromium`.

## Layout
```
server/       FastAPI server: assistant, decision ladder, research, providers, budget
core/         model client: prompts, parsers, thinking budget
web/          interface (ES modules, no build step); web/locales holds the translations
desktop/      PyQt6 desktop shell and the assistant card (HUD)
assets/icon/  app icon: the concept-trail.png master; build_icons.py makes every size and the .ico
scripts/      make_shortcut.py: desktop / Start menu shortcut
docs/         the introduction, with a worked example (INTRODUCTION.md, TANITIM.md)
install.ps1   one-command install for Windows; install.sh for macOS / Linux
tests/        pytest; tests/manual_research_benchmark.py measures live research
```

```bash
python -m pytest tests
```
