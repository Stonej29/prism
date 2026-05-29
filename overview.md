# Personal Research Interlinked System (PRISM) — Final Project Overview

## 1. Concept

The project is a **self-hosted personal research memory and idea engine**.

The main workflow is:

> You find an interesting link online, share it to a Telegram bot, and the system automatically archives it, summarizes it, evaluates it, connects it to your existing knowledge base, and saves it as an Obsidian-compatible Markdown note.

It is not just a bookmark manager. It is meant to become a growing personal knowledge system that helps you remember useful things, connect ideas, ask questions over your saved material, and generate new project/research ideas.

The system should be especially useful for topics like AI, robotics, computer vision, agents, efficient models, VLMs, open-source tools, GitHub projects, papers, and technical websites, but it should not be hardcoded only to those topics.

---

# 2. Core Goals

## Memory

The system should reliably store things you decide are worth saving:

* papers
* PDFs
* GitHub repositories
* websites
* technical blog posts
* demos
* project pages
* research announcements

Every saved item becomes a readable Markdown note.

## Understanding

For each link, the system should produce a structured note with:

* quick summary
* detailed summary
* key claims
* limitations and caveats
* technical details
* why it matters
* personal relevance
* quality/evaluation scores
* tags
* related notes
* possible project ideas
* source/archive information

The goal is that you can understand the item later without always reopening the original source.

## Connection

The system should connect each new item to your existing knowledge base.

It should use:

* Obsidian backlinks
* tags
* semantic search
* related-note detection
* concepts and clusters over time

The long-term vision is a connected map of ideas, like an AI-assisted Obsidian vault.

## Ideation

The system should generate project or research ideas based on your saved material.

For MVP, idea generation happens manually through Telegram with `/idea`.

Ideas should be:

* grounded in saved notes
* useful or interesting
* sometimes ambitious, but not fantasy
* practical enough to suggest a next step
* saved as Markdown
* rateable in Telegram

---

# 3. Main User Workflow

## Saving a link

You share a link to the Telegram bot.

If the message contains a URL and no command, the system treats it as a save request.

The backend then:

1. receives the URL
2. resolves the final URL
3. detects whether it is a PDF, GitHub repo, paper, or general webpage
4. fetches the content
5. archives the content
6. extracts text
7. checks for duplicates
8. retrieves related existing notes
9. calls an LLM to generate a structured note
10. saves the note as Markdown
11. embeds the note into LanceDB
12. stores metadata in SQLite
13. replies in Telegram with a short confirmation

Telegram confirmation should be compact:

```text
Saved: Efficient Vision Model

A lightweight computer vision model focused on fast inference for real-time perception. It may be relevant for robotics, edge AI, and efficient VLM pipelines.

Tags: #computer-vision #robotics #efficient-models

/more a7f3k9
```

If the link already exists:

```text
Already saved: Efficient Vision Model

A lightweight computer vision model focused on fast inference for real-time perception.

Tags: #computer-vision #robotics #efficient-models

/more a7f3k9
```

No duplicate note should be created.

---

# 4. Interface

## MVP interface

The MVP uses **Telegram only**.

Telegram is the right first interface because:

* it works well from iPhone
* link sharing is low friction
* it also works from desktop
* it supports commands
* it supports inline rating buttons
* no custom app or browser extension is needed

## Default behavior

A plain URL means:

> save and process this link.

No command should be required for the main use case.

## MVP commands

Core commands:

```text
/ask <question>
```

Ask a question over your saved notes only. No live web search in MVP.

```text
/idea
```

Generate one project/research idea from your vault.

```text
/idea <topic>
```

Generate one idea related to a topic.

```text
/more <id>
```

Show a medium-length readable version of a note or idea in Telegram.

```text
/recent
```

Show recently saved items.

```text
/tags
```

Show common or recent tags.

```text
/related <query or note_id>
```

Find related notes.

```text
/help
```

Show commands.

Later commands:

```text
/reprocess <id>
/update <url-or-id>
/reviewed <id>
/useful <id>
/project <id>
/ignore <id>
/daily_idea on
/weekly_idea on
```

---

# 5. Storage Design

## Source of truth

The source of truth is an **Obsidian-compatible Markdown vault**.

Databases are only indexes or metadata helpers.

This is important because the knowledge base remains:

* readable
* portable
* editable
* versionable
* AI-traversable
* usable even if the app breaks

## Recommended MVP folder structure

```text
research-vault/
  notes/
  concepts/
  projects/
  generated-ideas/
  profile/
  archive/
    pdfs/
    webpages/
    raw/
  system/
    prompts/
    logs/
    metadata/
```

## Storage roles

```text
Markdown vault = human-readable knowledge base
SQLite = metadata, duplicate checking, processing state, IDs
LanceDB = local vector search / semantic search
Archive folder = PDFs, cleaned webpage text, raw HTML if available
```

---

# 6. Note IDs and Filenames

Use both:

## Short ID

Used for Telegram commands.

Example:

```text
a7f3k9
```

## Readable filename

Used for Obsidian.

Example:

```text
2026-05-29-efficient-vision-model.md
```

Each note has both in frontmatter:

```yaml
id: "a7f3k9"
title: "Efficient Vision Model"
status: "unreviewed"
```

This gives you clean files in Obsidian and short IDs in Telegram.

---

# 7. Markdown Note Structure

Every saved link creates a general note. The system should not strongly separate papers, GitHub repos, and websites into completely different templates. The same core template applies to all source types.

Each note should include:

## Frontmatter

Metadata for Obsidian and the backend:

```yaml
id: ""
title: ""
type: "link"
source_url: ""
resolved_url: ""
date_saved: ""
date_processed: ""
source_kind: "website | pdf | github | paper | blog | unknown"
local_archive: ""
pdf_path: ""
content_hash: ""
status: "unreviewed"
tags: []
related_notes: []
usefulness_score: null
novelty_score: null
hype_risk: "low | medium | high | unknown"
implementation_relevance: "low | medium | high | unknown"
personal_relevance: "low | medium | high | unknown"
confidence: "low | medium | high"
```

## Required sections

Each note should contain:

1. **Quick Summary**
   1–5 sentences. This is the “glanceable” version.

2. **Detailed Summary**
   2–6 paragraphs. Enough detail to understand the item without immediately opening the original.

3. **Key Claims**
   Bullet points. If no claims are clear, say so.

4. **Limitations and Caveats**
   Bullet points. Include stated limitations and cautious inferred limitations.

5. **Why This Matters**
   Why the item may be technically or practically important.

6. **Personal Relevance**
   Why it matters to your work, interests, or possible projects.

7. **Technical Details**
   Methods, architecture, implementation, datasets, models, benchmarks, dependencies, or other relevant technical details.

8. **Evaluation**
   Usefulness, novelty, hype risk, implementation relevance, personal relevance.

9. **Related Notes**
   Obsidian backlinks with short explanations.

10. **Related Concepts**
    Concept links like `[[Computer Vision]]`, `[[Robotics]]`, `[[Efficient Models]]`.

11. **Possible Project Ideas**
    0–3 lightweight ideas.

12. **Open Questions**
    Things to check later.

13. **Source and Archive**
    Original URL, resolved URL, local archive, PDF path, dates.

---

# 8. Note Length Rules

Use this as the default:

```text
Quick Summary: 1–5 sentences
Detailed Summary: 2–6 paragraphs
Technical Details: concise bullet points where possible
Claims: bullet points
Limitations: bullet points
Related Notes: normally 3–7
Related Notes maximum: 10
Project Ideas: 0–3 lightweight ideas
```

The note should be layered:

* top = fast recognition
* middle = useful understanding
* bottom = technical detail, links, evaluation, and source info

---

# 9. Linking Rules

The system should avoid creating a messy graph.

## Normal behavior

* Add 3–7 related notes.
* Maximum 10 related notes.
* Only add meaningful links.
* Each related note should include a short reason.
* Weak semantic similarities should stay in LanceDB, not necessarily in Markdown.

Example:

```markdown
- [[Efficient Vision-Language Models]] — related because both focus on reducing model size while preserving multimodal performance.
```

## Relationship types

There are two types of relationship:

### Strong links

These become Obsidian backlinks.

### Soft semantic neighbors

These remain in LanceDB and can be used for search/retrieval, but do not clutter the Markdown file.

---

# 10. Evaluation System

The system should never reject links you send.

If you send it, it saves it.

But it should add its own evaluation.

## Usefulness

Scale 1–5.

How useful is this for your interests, work, or possible projects?

## Novelty

Scale 1–5.

How new or differentiated is this compared to your existing notes and related work?

## Hype Risk

Values:

```text
low
medium
high
unknown
```

How likely is the source to overstate its importance?

## Implementation Relevance

Values:

```text
low
medium
high
unknown
```

How useful is this for actually building something?

## Personal Relevance

Values:

```text
low
medium
high
unknown
```

How relevant is this to your profile and current interests?

---

# 11. Personal Profile

The system should maintain a personal profile file:

```text
research-vault/profile/me.md
```

This file tells the system what you care about.

It should include:

* current interests
* current work
* current projects
* long-term goals
* technical preferences
* what you usually care about
* what you care less about
* preferred output style

Initial interests:

* AI
* robotics
* computer vision
* vision-language models
* agents
* efficient models
* open-source tools
* practical research systems

The profile should be used during:

* summarization
* evaluation
* related-note selection
* `/ask`
* `/idea`

This makes the system personal instead of generic.

---

# 12. Ingestion Pipeline

## Pipeline for a new link

1. Receive Telegram message.
2. Extract URL.
3. Normalize URL.
4. Resolve redirects.
5. Detect source kind.
6. Check SQLite for existing URL.
7. Fetch content.
8. Archive content:

   * PDF: download PDF
   * webpage: save cleaned text/Markdown
   * raw HTML if easy
   * GitHub: save README/metadata snapshot
9. Extract text.
10. Create content hash.
11. Check SQLite for existing hash.
12. If duplicate, return existing summary.
13. Embed content or draft note.
14. Retrieve candidate related notes from LanceDB.
15. Load personal profile.
16. Call LLM to generate structured Markdown note.
17. Save Markdown note to `notes/`.
18. Write metadata to SQLite.
19. Embed final note into LanceDB.
20. Send compact Telegram confirmation.

---

# 13. Archiving Rules

## PDFs

For PDFs:

* download and save PDF
* store local path in note
* extract text
* save original and resolved URL

## Websites

For websites:

* save original URL
* save resolved URL
* save cleaned Markdown/text snapshot
* save raw HTML if easy
* no screenshots
* no full webpage archiving in MVP

## GitHub

For GitHub repos:

* save URL
* fetch README
* fetch basic metadata if possible:

  * repo name
  * owner
  * description
  * stars
  * license
  * last updated
* optionally save raw metadata JSON
* do not clone full repo in MVP unless later needed

---

# 14. Duplicate Handling

## Exact duplicates

If original URL, resolved URL, or content hash already exists:

* do not create a new note
* return existing title
* return quick summary
* return tags
* include `/more <id>`

## Semantic similarity

If something is similar but not an exact duplicate:

* create a new note
* link to related notes
* mention overlap in the note if relevant

Future command:

```text
/update <url-or-id>
```

or:

```text
/reprocess <id>
```

This can update existing notes later, but it is not required for MVP.

---

# 15. `/more` Behavior

`/more <id>` returns a medium-length readable Telegram version.

It should not return the raw Markdown.

For saved notes, include:

* title
* quick summary
* shortened detailed summary
* key claims
* limitations/caveats
* evaluation
* related notes
* source URL or path

For ideas, include:

* idea title
* one-line idea
* description
* why it might be interesting
* related notes
* possible implementation
* risks/unknowns
* next step
* rating if already rated

The full Markdown remains in Obsidian/the vault.

---

# 16. `/ask` Behavior

`/ask` answers questions using only saved notes.

Example:

```text
/ask What have I saved about efficient VLMs for robotics?
```

The system should:

1. embed the question
2. search LanceDB
3. retrieve relevant Markdown notes
4. optionally keyword search too
5. call LLM with retrieved context
6. answer based on the vault

MVP rule:

> No live web search in `/ask`.

This keeps answers grounded in your own saved knowledge.

---

# 17. Idea Generation

## MVP behavior

`/idea` generates one idea at a time.

The idea should be:

* grounded in saved notes
* relevant to your profile
* somewhat creative
* usually not too huge
* practical enough to suggest a next step
* saved as Markdown
* previewed in Telegram
* rateable with 1–5 stars

Example:

```text
/idea robotics + efficient models
```

Telegram response:

```text
Idea: Lightweight VLM for Robot Scene Understanding

Combine a compact vision encoder with a small LLM to create a local scene-description module for robotics.

/more idea_b2k91p

Rate this idea:
⭐️1 ⭐️2 ⭐️3 ⭐️4 ⭐️5
```

## Idea note location

Generated ideas are saved to:

```text
research-vault/generated-ideas/
```

## Idea note structure

Each idea should contain:

* one-line idea
* description
* why it might be interesting
* related notes
* possible implementation
* risks and unknowns
* next step
* novelty score
* feasibility score
* personal relevance
* user rating fields

Frontmatter example:

```yaml
id: "idea_b2k91p"
title: "Lightweight VLM for Robot Scene Understanding"
date_generated: "2026-05-29"
source_notes: []
tags: []
status: "new"
novelty_score: null
feasibility_score: null
personal_relevance: "high"
user_rating: null
user_feedback: ""
rating_date: ""
```

---

# 18. Idea Ratings

Idea ratings are part of MVP.

After an idea is generated, Telegram should show rating buttons:

```text
⭐️1  ⭐️2  ⭐️3  ⭐️4  ⭐️5
```

When you rate an idea:

* save rating in SQLite
* update the idea Markdown frontmatter
* optionally send a confirmation

Example:

```text
Saved rating: 4/5
```

The system should later use ratings as feedback.

At first, no fine-tuning is needed. Just include examples of highly rated and poorly rated ideas in future idea-generation prompts.

Example future prompt context:

```text
The user previously rated these ideas highly:
- ...

The user rated these ideas poorly:
- ...

Generate a new idea that better matches the high-rated patterns and avoids the low-rated ones.
```

This allows the system to “learn” from your ratings in a simple, transparent way.

---

# 19. Technical Architecture

## Core stack

```text
Language: Python
Interface: Telegram bot
Knowledge base: Markdown/Obsidian vault
Metadata DB: SQLite
Vector DB: LanceDB
Archive: local filesystem
LLM: cloud API first, configurable
Embeddings: configurable
Server access: self-hosted server via Tailscale
```

## Python components

Likely components:

```text
python-telegram-bot
FastAPI or simple worker service
httpx / requests
BeautifulSoup / trafilatura / readability-lxml
PyMuPDF / pypdf
GitHub API client
SQLite
LanceDB
OpenAI-compatible LLM client
YAML/frontmatter utilities
```

## LLM architecture

Use **controlled API calls**, not an autonomous coding agent.

Python controls:

* fetching
* archiving
* parsing
* deduplication
* file writing
* database updates
* vector indexing
* Telegram responses

The LLM handles:

* summarization
* claims extraction
* limitations extraction
* evaluation
* related-note selection
* idea generation
* answering questions from retrieved notes

This is safer, cheaper, easier to debug, and more predictable than running a full agent.

---

# 20. LLM Provider Strategy

Start with a cloud LLM for quality and simplicity.

The system should use a provider abstraction so models can be swapped.

It should support:

* OpenAI
* OpenRouter
* DeepSeek
* local OpenAI-compatible APIs later

Example config concept:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "..."
  api_key_env: "OPENAI_API_KEY"

embeddings:
  provider: "..."
  model: "..."
```

Local LLM support is not required first, but the architecture should not prevent it.

---

# 21. Review Workflow

Every note starts with:

```yaml
status: "unreviewed"
```

You can manually change this in Obsidian.

Later Telegram commands may support:

```text
/reviewed <id>
/useful <id>
/project <id>
/ignore <id>
```

But the MVP only needs the status field.

---

# 22. MVP Scope

## MVP name

**Link-to-Obsidian Research Inbox**

## MVP includes

* Telegram bot
* default link-saving behavior
* website fetching
* PDF downloading
* GitHub README fetching
* cleaned text/Markdown snapshots
* raw HTML if easy
* structured Markdown note generation
* Obsidian-compatible vault
* YAML frontmatter
* tags
* related notes
* personal profile
* evaluation scores
* SQLite metadata
* LanceDB semantic search
* duplicate detection
* `/ask`
* `/more`
* `/recent`
* `/tags`
* `/related`
* `/idea`
* idea Markdown files
* 1–5 star idea ratings

## MVP does not include

* custom web UI
* custom graph UI
* top lists
* browser extension
* native iOS app
* scheduled daily/weekly ideas
* live web search in `/ask`
* full autonomous agent behavior
* full benchmark tracking
* full webpage screenshots
* full website mirroring
* repo cloning/deep code analysis by default

---

# 23. Future Features

Possible later additions:

* browser extension
* iOS Shortcut integration
* custom web dashboard
* custom graph visualization
* scheduled daily/weekly ideas
* top lists/state-of-the-art trackers
* `/update` and `/reprocess`
* automatic concept pages
* project pages that evolve over time
* better source credibility checking
* GitHub repo structure analysis
* arXiv metadata support
* YouTube transcript support
* X/Twitter thread/link extraction
* full webpage snapshotting
* local LLM support
* better idea-learning loop
* multi-user support if it becomes useful to others

---

# 24. Build Plan

## Phase 1 — Basic skeleton

Goal: working Telegram bot and vault writing.

Build:

* Python project structure
* config file
* Telegram bot
* URL detection
* note ID generation
* Markdown writing
* simple SQLite metadata table

Result:

> You can send a link and get a placeholder Markdown note saved to the vault.

---

## Phase 2 — Content fetching and archiving

Goal: turn links into extracted text and archived files.

Build:

* URL resolver
* website text extraction
* PDF downloader
* PDF text extraction
* GitHub README fetcher
* cleaned text archive
* raw HTML save if easy
* content hashing
* duplicate detection

Result:

> Links are fetched, archived, deduplicated, and stored.

---

## Phase 3 — LLM note generation

Goal: generate useful structured notes.

Build:

* personal profile file
* LLM client abstraction
* prompt for structured note generation
* Markdown template
* YAML frontmatter writing
* compact Telegram confirmation

Result:

> Sending a link creates a real summarized Obsidian note.

---

## Phase 4 — LanceDB semantic search and linking

Goal: connect notes.

Build:

* embedding client
* LanceDB index
* note embedding
* semantic retrieval
* related-note candidate selection
* LLM-assisted related-note selection
* Obsidian backlinks

Result:

> New notes include meaningful related notes and can be semantically searched.

---

## Phase 5 — Telegram commands

Goal: make the system usable from Telegram.

Build:

* `/more`
* `/recent`
* `/tags`
* `/related`
* `/ask`

Result:

> You can browse and query your saved knowledge from Telegram.

---

## Phase 6 — Idea generation and ratings

Goal: add the idea engine.

Build:

* `/idea`
* idea Markdown template
* idea saving to `generated-ideas/`
* compact idea preview
* Telegram rating buttons
* rating persistence in SQLite
* rating updates in Markdown frontmatter
* future idea prompts use previous ratings

Result:

> The system can generate and improve project ideas from your saved knowledge.
# Personal Research Interlinked System (PRISM) — Final Project Overview

## 1. Concept

The project is a **self-hosted personal research memory and idea engine**.

The main workflow is:

> You find an interesting link online, share it to a Telegram bot, and the system automatically archives it, summarizes it, evaluates it, connects it to your existing knowledge base, and saves it as an Obsidian-compatible Markdown note.

It is not just a bookmark manager. It is meant to become a growing personal knowledge system that helps you remember useful things, connect ideas, ask questions over your saved material, and generate new project/research ideas.

The system should be especially useful for topics like AI, robotics, computer vision, agents, efficient models, VLMs, open-source tools, GitHub projects, papers, and technical websites, but it should not be hardcoded only to those topics.

---

# 2. Core Goals

## Memory

The system should reliably store things you decide are worth saving:

* papers
* PDFs
* GitHub repositories
* websites
* technical blog posts
* demos
* project pages
* research announcements

Every saved item becomes a readable Markdown note.

## Understanding

For each link, the system should produce a structured note with:

* quick summary
* detailed summary
* key claims
* limitations and caveats
* technical details
* why it matters
* personal relevance
* quality/evaluation scores
* tags
* related notes
* possible project ideas
* source/archive information

The goal is that you can understand the item later without always reopening the original source.

## Connection

The system should connect each new item to your existing knowledge base.

It should use:

* Obsidian backlinks
* tags
* semantic search
* related-note detection
* concepts and clusters over time

The long-term vision is a connected map of ideas, like an AI-assisted Obsidian vault.

## Ideation

The system should generate project or research ideas based on your saved material.

For MVP, idea generation happens manually through Telegram with `/idea`.

Ideas should be:

* grounded in saved notes
* useful or interesting
* sometimes ambitious, but not fantasy
* practical enough to suggest a next step
* saved as Markdown
* rateable in Telegram

---

# 3. Main User Workflow

## Saving a link

You share a link to the Telegram bot.

If the message contains a URL and no command, the system treats it as a save request.

The backend then:

1. receives the URL
2. resolves the final URL
3. detects whether it is a PDF, GitHub repo, paper, or general webpage
4. fetches the content
5. archives the content
6. extracts text
7. checks for duplicates
8. retrieves related existing notes
9. calls an LLM to generate a structured note
10. saves the note as Markdown
11. embeds the note into LanceDB
12. stores metadata in SQLite
13. replies in Telegram with a short confirmation

Telegram confirmation should be compact:

```text
Saved: Efficient Vision Model

A lightweight computer vision model focused on fast inference for real-time perception. It may be relevant for robotics, edge AI, and efficient VLM pipelines.

Tags: #computer-vision #robotics #efficient-models

/more a7f3k9
```

If the link already exists:

```text
Already saved: Efficient Vision Model

A lightweight computer vision model focused on fast inference for real-time perception.

Tags: #computer-vision #robotics #efficient-models

/more a7f3k9
```

No duplicate note should be created.

---

# 4. Interface

## MVP interface

The MVP uses **Telegram only**.

Telegram is the right first interface because:

* it works well from iPhone
* link sharing is low friction
* it also works from desktop
* it supports commands
* it supports inline rating buttons
* no custom app or browser extension is needed

## Default behavior

A plain URL means:

> save and process this link.

No command should be required for the main use case.

## MVP commands

Core commands:

```text
/ask <question>
```

Ask a question over your saved notes only. No live web search in MVP.

```text
/idea
```

Generate one project/research idea from your vault.

```text
/idea <topic>
```

Generate one idea related to a topic.

```text
/more <id>
```

Show a medium-length readable version of a note or idea in Telegram.

```text
/recent
```

Show recently saved items.

```text
/tags
```

Show common or recent tags.

```text
/related <query or note_id>
```

Find related notes.

```text
/help
```

Show commands.

Later commands:

```text
/reprocess <id>
/update <url-or-id>
/reviewed <id>
/useful <id>
/project <id>
/ignore <id>
/daily_idea on
/weekly_idea on
```

---

# 5. Storage Design

## Source of truth

The source of truth is an **Obsidian-compatible Markdown vault**.

Databases are only indexes or metadata helpers.

This is important because the knowledge base remains:

* readable
* portable
* editable
* versionable
* AI-traversable
* usable even if the app breaks

## Recommended MVP folder structure

```text
research-vault/
  notes/
  concepts/
  projects/
  generated-ideas/
  profile/
  archive/
    pdfs/
    webpages/
    raw/
  system/
    prompts/
    logs/
    metadata/
```

## Storage roles

```text
Markdown vault = human-readable knowledge base
SQLite = metadata, duplicate checking, processing state, IDs
LanceDB = local vector search / semantic search
Archive folder = PDFs, cleaned webpage text, raw HTML if available
```

---

# 6. Note IDs and Filenames

Use both:

## Short ID

Used for Telegram commands.

Example:

```text
a7f3k9
```

## Readable filename

Used for Obsidian.

Example:

```text
2026-05-29-efficient-vision-model.md
```

Each note has both in frontmatter:

```yaml
id: "a7f3k9"
title: "Efficient Vision Model"
status: "unreviewed"
```

This gives you clean files in Obsidian and short IDs in Telegram.

---

# 7. Markdown Note Structure

Every saved link creates a general note. The system should not strongly separate papers, GitHub repos, and websites into completely different templates. The same core template applies to all source types.

Each note should include:

## Frontmatter

Metadata for Obsidian and the backend:

```yaml
id: ""
title: ""
type: "link"
source_url: ""
resolved_url: ""
date_saved: ""
date_processed: ""
source_kind: "website | pdf | github | paper | blog | unknown"
local_archive: ""
pdf_path: ""
content_hash: ""
status: "unreviewed"
tags: []
related_notes: []
usefulness_score: null
novelty_score: null
hype_risk: "low | medium | high | unknown"
implementation_relevance: "low | medium | high | unknown"
personal_relevance: "low | medium | high | unknown"
confidence: "low | medium | high"
```

## Required sections

Each note should contain:

1. **Quick Summary**
   1–5 sentences. This is the “glanceable” version.

2. **Detailed Summary**
   2–6 paragraphs. Enough detail to understand the item without immediately opening the original.

3. **Key Claims**
   Bullet points. If no claims are clear, say so.

4. **Limitations and Caveats**
   Bullet points. Include stated limitations and cautious inferred limitations.

5. **Why This Matters**
   Why the item may be technically or practically important.

6. **Personal Relevance**
   Why it matters to your work, interests, or possible projects.

7. **Technical Details**
   Methods, architecture, implementation, datasets, models, benchmarks, dependencies, or other relevant technical details.

8. **Evaluation**
   Usefulness, novelty, hype risk, implementation relevance, personal relevance.

9. **Related Notes**
   Obsidian backlinks with short explanations.

10. **Related Concepts**
    Concept links like `[[Computer Vision]]`, `[[Robotics]]`, `[[Efficient Models]]`.

11. **Possible Project Ideas**
    0–3 lightweight ideas.

12. **Open Questions**
    Things to check later.

13. **Source and Archive**
    Original URL, resolved URL, local archive, PDF path, dates.

---

# 8. Note Length Rules

Use this as the default:

```text
Quick Summary: 1–5 sentences
Detailed Summary: 2–6 paragraphs
Technical Details: concise bullet points where possible
Claims: bullet points
Limitations: bullet points
Related Notes: normally 3–7
Related Notes maximum: 10
Project Ideas: 0–3 lightweight ideas
```

The note should be layered:

* top = fast recognition
* middle = useful understanding
* bottom = technical detail, links, evaluation, and source info

---

# 9. Linking Rules

The system should avoid creating a messy graph.

## Normal behavior

* Add 3–7 related notes.
* Maximum 10 related notes.
* Only add meaningful links.
* Each related note should include a short reason.
* Weak semantic similarities should stay in LanceDB, not necessarily in Markdown.

Example:

```markdown
- [[Efficient Vision-Language Models]] — related because both focus on reducing model size while preserving multimodal performance.
```

## Relationship types

There are two types of relationship:

### Strong links

These become Obsidian backlinks.

### Soft semantic neighbors

These remain in LanceDB and can be used for search/retrieval, but do not clutter the Markdown file.

---

# 10. Evaluation System

The system should never reject links you send.

If you send it, it saves it.

But it should add its own evaluation.

## Usefulness

Scale 1–5.

How useful is this for your interests, work, or possible projects?

## Novelty

Scale 1–5.

How new or differentiated is this compared to your existing notes and related work?

## Hype Risk

Values:

```text
low
medium
high
unknown
```

How likely is the source to overstate its importance?

## Implementation Relevance

Values:

```text
low
medium
high
unknown
```

How useful is this for actually building something?

## Personal Relevance

Values:

```text
low
medium
high
unknown
```

How relevant is this to your profile and current interests?

---

# 11. Personal Profile

The system should maintain a personal profile file:

```text
research-vault/profile/me.md
```

This file tells the system what you care about.

It should include:

* current interests
* current work
* current projects
* long-term goals
* technical preferences
* what you usually care about
* what you care less about
* preferred output style

Initial interests:

* AI
* robotics
* computer vision
* vision-language models
* agents
* efficient models
* open-source tools
* practical research systems

The profile should be used during:

* summarization
* evaluation
* related-note selection
* `/ask`
* `/idea`

This makes the system personal instead of generic.

---

# 12. Ingestion Pipeline

## Pipeline for a new link

1. Receive Telegram message.
2. Extract URL.
3. Normalize URL.
4. Resolve redirects.
5. Detect source kind.
6. Check SQLite for existing URL.
7. Fetch content.
8. Archive content:

   * PDF: download PDF
   * webpage: save cleaned text/Markdown
   * raw HTML if easy
   * GitHub: save README/metadata snapshot
9. Extract text.
10. Create content hash.
11. Check SQLite for existing hash.
12. If duplicate, return existing summary.
13. Embed content or draft note.
14. Retrieve candidate related notes from LanceDB.
15. Load personal profile.
16. Call LLM to generate structured Markdown note.
17. Save Markdown note to `notes/`.
18. Write metadata to SQLite.
19. Embed final note into LanceDB.
20. Send compact Telegram confirmation.

---

# 13. Archiving Rules

## PDFs

For PDFs:

* download and save PDF
* store local path in note
* extract text
* save original and resolved URL

## Websites

For websites:

* save original URL
* save resolved URL
* save cleaned Markdown/text snapshot
* save raw HTML if easy
* no screenshots
* no full webpage archiving in MVP

## GitHub

For GitHub repos:

* save URL
* fetch README
* fetch basic metadata if possible:

  * repo name
  * owner
  * description
  * stars
  * license
  * last updated
* optionally save raw metadata JSON
* do not clone full repo in MVP unless later needed

---

# 14. Duplicate Handling

## Exact duplicates

If original URL, resolved URL, or content hash already exists:

* do not create a new note
* return existing title
* return quick summary
* return tags
* include `/more <id>`

## Semantic similarity

If something is similar but not an exact duplicate:

* create a new note
* link to related notes
* mention overlap in the note if relevant

Future command:

```text
/update <url-or-id>
```

or:

```text
/reprocess <id>
```

This can update existing notes later, but it is not required for MVP.

---

# 15. `/more` Behavior

`/more <id>` returns a medium-length readable Telegram version.

It should not return the raw Markdown.

For saved notes, include:

* title
* quick summary
* shortened detailed summary
* key claims
* limitations/caveats
* evaluation
* related notes
* source URL or path

For ideas, include:

* idea title
* one-line idea
* description
* why it might be interesting
* related notes
* possible implementation
* risks/unknowns
* next step
* rating if already rated

The full Markdown remains in Obsidian/the vault.

---

# 16. `/ask` Behavior

`/ask` answers questions using only saved notes.

Example:

```text
/ask What have I saved about efficient VLMs for robotics?
```

The system should:

1. embed the question
2. search LanceDB
3. retrieve relevant Markdown notes
4. optionally keyword search too
5. call LLM with retrieved context
6. answer based on the vault

MVP rule:

> No live web search in `/ask`.

This keeps answers grounded in your own saved knowledge.

---

# 17. Idea Generation

## MVP behavior

`/idea` generates one idea at a time.

The idea should be:

* grounded in saved notes
* relevant to your profile
* somewhat creative
* usually not too huge
* practical enough to suggest a next step
* saved as Markdown
* previewed in Telegram
* rateable with 1–5 stars

Example:

```text
/idea robotics + efficient models
```

Telegram response:

```text
Idea: Lightweight VLM for Robot Scene Understanding

Combine a compact vision encoder with a small LLM to create a local scene-description module for robotics.

/more idea_b2k91p

Rate this idea:
⭐️1 ⭐️2 ⭐️3 ⭐️4 ⭐️5
```

## Idea note location

Generated ideas are saved to:

```text
research-vault/generated-ideas/
```

## Idea note structure

Each idea should contain:

* one-line idea
* description
* why it might be interesting
* related notes
* possible implementation
* risks and unknowns
* next step
* novelty score
* feasibility score
* personal relevance
* user rating fields

Frontmatter example:

```yaml
id: "idea_b2k91p"
title: "Lightweight VLM for Robot Scene Understanding"
date_generated: "2026-05-29"
source_notes: []
tags: []
status: "new"
novelty_score: null
feasibility_score: null
personal_relevance: "high"
user_rating: null
user_feedback: ""
rating_date: ""
```

---

# 18. Idea Ratings

Idea ratings are part of MVP.

After an idea is generated, Telegram should show rating buttons:

```text
⭐️1  ⭐️2  ⭐️3  ⭐️4  ⭐️5
```

When you rate an idea:

* save rating in SQLite
* update the idea Markdown frontmatter
* optionally send a confirmation

Example:

```text
Saved rating: 4/5
```

The system should later use ratings as feedback.

At first, no fine-tuning is needed. Just include examples of highly rated and poorly rated ideas in future idea-generation prompts.

Example future prompt context:

```text
The user previously rated these ideas highly:
- ...

The user rated these ideas poorly:
- ...

Generate a new idea that better matches the high-rated patterns and avoids the low-rated ones.
```

This allows the system to “learn” from your ratings in a simple, transparent way.

---

# 19. Technical Architecture

## Core stack

```text
Language: Python
Interface: Telegram bot
Knowledge base: Markdown/Obsidian vault
Metadata DB: SQLite
Vector DB: LanceDB
Archive: local filesystem
LLM: cloud API first, configurable
Embeddings: configurable
Server access: self-hosted server via Tailscale
```

## Python components

Likely components:

```text
python-telegram-bot
FastAPI or simple worker service
httpx / requests
BeautifulSoup / trafilatura / readability-lxml
PyMuPDF / pypdf
GitHub API client
SQLite
LanceDB
OpenAI-compatible LLM client
YAML/frontmatter utilities
```

## LLM architecture

Use **controlled API calls**, not an autonomous coding agent.

Python controls:

* fetching
* archiving
* parsing
* deduplication
* file writing
* database updates
* vector indexing
* Telegram responses

The LLM handles:

* summarization
* claims extraction
* limitations extraction
* evaluation
* related-note selection
* idea generation
* answering questions from retrieved notes

This is safer, cheaper, easier to debug, and more predictable than running a full agent.

---

# 20. LLM Provider Strategy

Start with a cloud LLM for quality and simplicity.

The system should use a provider abstraction so models can be swapped.

It should support:

* OpenAI
* OpenRouter
* DeepSeek
* local OpenAI-compatible APIs later

Example config concept:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "..."
  api_key_env: "OPENAI_API_KEY"

embeddings:
  provider: "..."
  model: "..."
```

Local LLM support is not required first, but the architecture should not prevent it.

---

# 21. Review Workflow

Every note starts with:

```yaml
status: "unreviewed"
```

You can manually change this in Obsidian.

Later Telegram commands may support:

```text
/reviewed <id>
/useful <id>
/project <id>
/ignore <id>
```

But the MVP only needs the status field.

---

# 22. MVP Scope

## MVP name

**Link-to-Obsidian Research Inbox**

## MVP includes

* Telegram bot
* default link-saving behavior
* website fetching
* PDF downloading
* GitHub README fetching
* cleaned text/Markdown snapshots
* raw HTML if easy
* structured Markdown note generation
* Obsidian-compatible vault
* YAML frontmatter
* tags
* related notes
* personal profile
* evaluation scores
* SQLite metadata
* LanceDB semantic search
* duplicate detection
* `/ask`
* `/more`
* `/recent`
* `/tags`
* `/related`
* `/idea`
* idea Markdown files
* 1–5 star idea ratings

## MVP does not include

* custom web UI
* custom graph UI
* top lists
* browser extension
* native iOS app
* scheduled daily/weekly ideas
* live web search in `/ask`
* full autonomous agent behavior
* full benchmark tracking
* full webpage screenshots
* full website mirroring
* repo cloning/deep code analysis by default

---

# 23. Future Features

Possible later additions:

* browser extension
* iOS Shortcut integration
* custom web dashboard
* custom graph visualization
* scheduled daily/weekly ideas
* top lists/state-of-the-art trackers
* `/update` and `/reprocess`
* automatic concept pages
* project pages that evolve over time
* better source credibility checking
* GitHub repo structure analysis
* arXiv metadata support
* YouTube transcript support
* X/Twitter thread/link extraction
* full webpage snapshotting
* local LLM support
* better idea-learning loop
* multi-user support if it becomes useful to others

---

# 24. Build Plan

## Phase 1 — Basic skeleton

Goal: working Telegram bot and vault writing.

Build:

* Python project structure
* config file
* Telegram bot
* URL detection
* note ID generation
* Markdown writing
* simple SQLite metadata table

Result:

> You can send a link and get a placeholder Markdown note saved to the vault.

---

## Phase 2 — Content fetching and archiving

Goal: turn links into extracted text and archived files.

Build:

* URL resolver
* website text extraction
* PDF downloader
* PDF text extraction
* GitHub README fetcher
* cleaned text archive
* raw HTML save if easy
* content hashing
* duplicate detection

Result:

> Links are fetched, archived, deduplicated, and stored.

---

## Phase 3 — LLM note generation

Goal: generate useful structured notes.

Build:

* personal profile file
* LLM client abstraction
* prompt for structured note generation
* Markdown template
* YAML frontmatter writing
* compact Telegram confirmation

Result:

> Sending a link creates a real summarized Obsidian note.

---

## Phase 4 — LanceDB semantic search and linking

Goal: connect notes.

Build:

* embedding client
* LanceDB index
* note embedding
* semantic retrieval
* related-note candidate selection
* LLM-assisted related-note selection
* Obsidian backlinks

Result:

> New notes include meaningful related notes and can be semantically searched.

---

## Phase 5 — Telegram commands

Goal: make the system usable from Telegram.

Build:

* `/more`
* `/recent`
* `/tags`
* `/related`
* `/ask`

Result:

> You can browse and query your saved knowledge from Telegram.

---

## Phase 6 — Idea generation and ratings

Goal: add the idea engine.

Build:

* `/idea`
* idea Markdown template
* idea saving to `generated-ideas/`
* compact idea preview
* Telegram rating buttons
* rating persistence in SQLite
* rating updates in Markdown frontmatter
* future idea prompts use previous ratings

Result:

> The system can generate and improve project ideas from your saved knowledge.

---

# 25. Design Principles

## Low friction first

Saving a link should be effortless.

The default action is:

> send link → system saves and processes it

## Markdown as source of truth

Markdown files remain the core knowledge base.

SQLite and LanceDB are helpers.

## Archive first, intelligence second

The system should always preserve the original source/content first, then analyze it.

## Human agency

The system does not reject saved links.

It may score, warn, or evaluate, but it always saves what you send unless it is an exact duplicate.

## Controlled intelligence

Use LLMs in bounded steps, not as uncontrolled agents.

## Personal context matters

The system should use your profile and previous notes to judge relevance.

## Expand later, but keep MVP useful

The MVP should already be useful as a personal research inbox, but it should be designed so it can grow into a richer research graph and idea engine.

---

# 25. Design Principles

## Low friction first

Saving a link should be effortless.

The default action is:

> send link → system saves and processes it

## Markdown as source of truth

Markdown files remain the core knowledge base.

SQLite and LanceDB are helpers.

## Archive first, intelligence second

The system should always preserve the original source/content first, then analyze it.

## Human agency

The system does not reject saved links.

It may score, warn, or evaluate, but it always saves what you send unless it is an exact duplicate.

## Controlled intelligence

Use LLMs in bounded steps, not as uncontrolled agents.

## Personal context matters

The system should use your profile and previous notes to judge relevance.

## Expand later, but keep MVP useful

The MVP should already be useful as a personal research inbox, but it should be designed so it can grow into a richer research graph and idea engine.
