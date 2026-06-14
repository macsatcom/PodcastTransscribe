# Graph Report - .  (2026-06-12)

## Corpus Check
- 80 files · ~60,981 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 941 nodes · 2434 edges · 59 communities (48 shown, 11 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 200 edges (avg confidence: 0.67)
- Token cost: 4,200 input · 3,100 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Database & App Bootstrap|Database & App Bootstrap]]
- [[_COMMUNITY_PostCSS Minified Library A|PostCSS Minified Library A]]
- [[_COMMUNITY_PostCSS Minified Library B|PostCSS Minified Library B]]
- [[_COMMUNITY_Audiobookshelf Source Adapter|Audiobookshelf Source Adapter]]
- [[_COMMUNITY_CSS Minified Cache Utils|CSS Minified Cache Utils]]
- [[_COMMUNITY_CSS Minified DOM Helpers|CSS Minified DOM Helpers]]
- [[_COMMUNITY_Core Features & Documentation|Core Features & Documentation]]
- [[_COMMUNITY_CSS Minified AppendClone|CSS Minified Append/Clone]]
- [[_COMMUNITY_Public Search Portals|Public Search Portals]]
- [[_COMMUNITY_Portal Process Manager|Portal Process Manager]]
- [[_COMMUNITY_Tailwind CSS Utilities|Tailwind CSS Utilities]]
- [[_COMMUNITY_CSS Minified Selectors|CSS Minified Selectors]]
- [[_COMMUNITY_CSS Vendor Prefix Engine|CSS Vendor Prefix Engine]]
- [[_COMMUNITY_CSS Minified Transforms|CSS Minified Transforms]]
- [[_COMMUNITY_CSS Minified Parsers|CSS Minified Parsers]]
- [[_COMMUNITY_App Config & Topic Clustering|App Config & Topic Clustering]]
- [[_COMMUNITY_CSS Minified Before Helpers|CSS Minified Before Helpers]]
- [[_COMMUNITY_CSS Minified Iterators|CSS Minified Iterators]]
- [[_COMMUNITY_PostCSS Rule Parser|PostCSS Rule Parser]]
- [[_COMMUNITY_RAG Question Answering|RAG Question Answering]]
- [[_COMMUNITY_OpenRouter API Client|OpenRouter API Client]]
- [[_COMMUNITY_CSS Minified Layout|CSS Minified Layout]]
- [[_COMMUNITY_Embedding Model Migration|Embedding Model Migration]]
- [[_COMMUNITY_Search API (FTS + Semantic)|Search API (FTS + Semantic)]]
- [[_COMMUNITY_Episode Processing Queue|Episode Processing Queue]]
- [[_COMMUNITY_CSS Minified Spacing|CSS Minified Spacing]]
- [[_COMMUNITY_CSS Minified Selectors B|CSS Minified Selectors B]]
- [[_COMMUNITY_CSS Minified Converters|CSS Minified Converters]]
- [[_COMMUNITY_CSS Minified Assignments|CSS Minified Assignments]]
- [[_COMMUNITY_CSS Prefix Detectors|CSS Prefix Detectors]]
- [[_COMMUNITY_Settings & Model Config API|Settings & Model Config API]]
- [[_COMMUNITY_Transcript Chunking & Indexing|Transcript Chunking & Indexing]]
- [[_COMMUNITY_Web UI Route Handlers|Web UI Route Handlers]]
- [[_COMMUNITY_CSS Arbitrary Properties|CSS Arbitrary Properties]]
- [[_COMMUNITY_PostCSS Raw Formatter|PostCSS Raw Formatter]]
- [[_COMMUNITY_CSS Gradient Direction Fixer|CSS Gradient Direction Fixer]]
- [[_COMMUNITY_Whisper Transcription Service|Whisper Transcription Service]]
- [[_COMMUNITY_CSS Minified Misc A|CSS Minified Misc A]]
- [[_COMMUNITY_CSS Minified Misc B|CSS Minified Misc B]]
- [[_COMMUNITY_Initial DB Schema Migration|Initial DB Schema Migration]]
- [[_COMMUNITY_Search & Insights Schema v2|Search & Insights Schema v2]]
- [[_COMMUNITY_OpenCode Plugin Config|OpenCode Plugin Config]]
- [[_COMMUNITY_CSS Minified Trio A|CSS Minified Trio A]]
- [[_COMMUNITY_CSS Minified Trio B|CSS Minified Trio B]]
- [[_COMMUNITY_CSS Minified Trio C|CSS Minified Trio C]]
- [[_COMMUNITY_CSS Minified Trio D|CSS Minified Trio D]]
- [[_COMMUNITY_CSS Minified Trio E|CSS Minified Trio E]]
- [[_COMMUNITY_CSS Minified Pair A|CSS Minified Pair A]]
- [[_COMMUNITY_CSS Minified Pair B|CSS Minified Pair B]]
- [[_COMMUNITY_CSS Minified Pair C|CSS Minified Pair C]]
- [[_COMMUNITY_CSS Minified Pair D|CSS Minified Pair D]]
- [[_COMMUNITY_CSS Minified Pair E|CSS Minified Pair E]]
- [[_COMMUNITY_CSS Minified Pair F|CSS Minified Pair F]]
- [[_COMMUNITY_CSS Minified Pair G|CSS Minified Pair G]]

## God Nodes (most connected - your core abstractions)
1. `__()` - 556 edges
2. `push()` - 57 edges
3. `add()` - 42 edges
4. `has()` - 39 edges
5. `OpenRouterClient` - 38 edges
6. `replace()` - 38 edges
7. `get()` - 33 edges
8. `Setting` - 31 edges
9. `Episode` - 30 edges
10. `ABSSourceAdapter` - 29 edges

## Surprising Connections (you probably didn't know these)
- `client()` --calls--> `AsyncClient`  [INFERRED]
  tests/conftest.py → app/adapters/abs.py
- `Base HTML Template with Navigation Bar` --implements--> `Spotify-Inspired Dark Design System (near-black, green accent, pill geometry)`  [INFERRED]
  app/templates/base.html → DESIGN.md
- `Queue Management Template with Live Polling` --conceptually_related_to--> `Episode Processing Pipeline (download → transcribe → summarize → index → ready)`  [INFERRED]
  app/templates/queue.html → docs/superpowers/specs/2026-05-21-podcast-transcriber-design.md
- `test_parse_duration_hh_mm_ss()` --calls--> `RSSSourceAdapter`  [EXTRACTED]
  tests/test_rss_adapter.py → app/adapters/rss.py
- `test_parse_duration_mm_ss()` --calls--> `RSSSourceAdapter`  [EXTRACTED]
  tests/test_rss_adapter.py → app/adapters/rss.py

## Import Cycles
- 1-file cycle: `app/main.py -> app/main.py`
- 1-file cycle: `app/portal_server.py -> app/portal_server.py`
- 1-file cycle: `app/routers/api_portals.py -> app/routers/api_portals.py`
- 1-file cycle: `app/routers/api_episodes.py -> app/routers/api_episodes.py`
- 1-file cycle: `app/routers/api_insights.py -> app/routers/api_insights.py`
- 1-file cycle: `app/routers/api_podcasts.py -> app/routers/api_podcasts.py`
- 1-file cycle: `app/portal_manager.py -> app/portal_manager.py`

## Hyperedges (group relationships)
- **Unified Search+Insights Tabbed Pattern (main app + portal)** — templates_search, templates_portal_home, concept_unified_tabbed_view [INFERRED 0.95]
- **Dual Search Mode: FTS Keywords + Semantic Natural Language** — concept_fts_search, concept_semantic_search, templates_search, templates_portal_home [EXTRACTED 1.00]
- **Chunk-Level Transcript Viewer with Timestamp Navigation** — templates_portal_episode, concept_chunk_transcript_viewer, plans_2026_05_30_insights_unified [INFERRED 0.95]
- **ABS Data Integration Pipeline** — specs_2026_05_24_abs_integration_design_abs_source_adapter, specs_2026_05_24_abs_integration_design_abs_poller, specs_2026_05_24_abs_integration_design_api_abs_router [EXTRACTED 1.00]
- **Topic Clustering Data System** — specs_2026_05_25_insights_and_rag_design_topic_clusters_table, specs_2026_05_25_insights_and_rag_design_episode_topics_table, specs_2026_05_25_insights_and_rag_design_clustering_engine, specs_2026_05_25_insights_and_rag_design_hdbscan [EXTRACTED 1.00]
- **Portal Runtime Lifecycle Management** — specs_2026_05_21_public_search_portals_design_portals_table, specs_2026_05_21_public_search_portals_design_portal_subprocess, specs_2026_05_21_public_search_portals_design_portal_server [EXTRACTED 1.00]

## Communities (59 total, 11 thin omitted)

### Community 0 - "Database & App Bootstrap"
Cohesion: 0.06
Nodes (65): ABSSourceAdapter, run_async_migrations(), run_migrations_online(), Base, get_db(), _deduplicate_abs_podcasts(), lifespan(), FastAPI (+57 more)

### Community 1 - "PostCSS Minified Library A"
Cohesion: 0.05
Nodes (64): An(), ao(), atrule(), Ba(), beforeAfter(), block(), body(), checkMissedSemicolon() (+56 more)

### Community 3 - "Audiobookshelf Source Adapter"
Cohesion: 0.08
Nodes (22): ABC, ABSSourceAdapter, BaseSourceAdapter, EpisodeMetadata, RSSSourceAdapter, BinaryIO, EpisodeMetadata, BinaryIO (+14 more)

### Community 4 - "CSS Minified Cache Utils"
Cohesion: 0.09
Nodes (38): ca(), cs(), DC(), delete(), _deleteIfExpired(), _emitEvictions(), _entriesAscending(), entriesDescending() (+30 more)

### Community 5 - "CSS Minified DOM Helpers"
Cohesion: 0.08
Nodes (36): addToError(), async(), catch(), clean(), cloneDiv(), colorStops(), content(), css() (+28 more)

### Community 6 - "Core Features & Documentation"
Cohesion: 0.11
Nodes (34): Project Changelog, Audiobookshelf Integration via ABS API, Chunk-Level Transcript Viewer with Timestamp Deep-Links (?t=seconds), Episode Processing Pipeline (download → transcribe → summarize → index → ready), PostgreSQL Full-Text Search (tsvector/tsquery), HDBSCAN Topic Clustering with LLM-Generated Labels, RAG Question-Answering Over Transcripts with MMR Re-ranking, OpenRouter API Integration (transcription, LLM, embeddings) (+26 more)

### Community 7 - "CSS Minified Append/Clone"
Cohesion: 0.09
Nodes (32): after(), append(), BC(), cloneAfter(), Co(), Eh(), FC(), Gd() (+24 more)

### Community 8 - "Public Search Portals"
Cohesion: 0.09
Nodes (31): API Portals Router (app/routers/api_portals.py), Branded Search Page (portal_search.html), portal_images Docker Volume, Portal Model (app/models/portal.py), Portal Server (app/portal_server.py), Portal Subprocess Management, portals Database Table, Public Search Portals Feature (+23 more)

### Community 9 - "Portal Process Manager"
Cohesion: 0.15
Nodes (17): PortalManager, UUID, create_app(), FastAPI, AsyncSession, UUID, Portal, create_portal() (+9 more)

### Community 10 - "Tailwind CSS Utilities"
Cohesion: 0.08
Nodes (28): blueGray(), breakpoints(), checkForWarning(), coolGray(), ei(), H5(), info(), js() (+20 more)

### Community 11 - "CSS Minified Selectors"
Cohesion: 0.08
Nodes (25): aa(), ac(), bx(), Cl(), cy(), Dl(), dy(), Gl() (+17 more)

### Community 12 - "CSS Vendor Prefix Engine"
Cohesion: 0.11
Nodes (25): add(), applyVariantOffset(), cleanFromUnprefixed(), cleanOtherPrefixes(), compare(), dm(), findProp(), hm() (+17 more)

### Community 13 - "CSS Minified Transforms"
Cohesion: 0.08
Nodes (25): bd(), Ck(), create(), ES(), Fh(), forVariant(), fS(), Ia() (+17 more)

### Community 14 - "CSS Minified Parsers"
Cohesion: 0.15
Nodes (22): as(), clone(), da(), F_(), Fg(), from(), I_(), jg() (+14 more)

### Community 15 - "App Config & Topic Clustering"
Cohesion: 0.15
Nodes (14): Settings, AsyncSession, BaseSettings, Transcript, _generate_label(), Topic clustering over transcript chunks.  Architectural notes ------------------, embed_chunks(), Embed a list of chunk texts.      Returns ``(model_used, embeddings)``. The mode (+6 more)

### Community 16 - "CSS Minified Before Helpers"
Cohesion: 0.14
Nodes (18): already(), before(), calcBefore(), cloneBefore(), contain3d(), disabled(), disabledDecl(), disabledValue() (+10 more)

### Community 17 - "CSS Minified Iterators"
Cohesion: 0.12
Nodes (18): clear(), cx(), ec(), fx(), gx(), Hs(), jr(), ke() (+10 more)

### Community 18 - "PostCSS Rule Parser"
Cohesion: 0.15
Nodes (17): check(), cleanBrackets(), cleaner(), comma(), group(), isAlready(), isHack(), Mo() (+9 more)

### Community 19 - "RAG Question Answering"
Cohesion: 0.24
Nodes (15): AsyncSession, ndarray, ask_question(), _build_user_message(), _citation(), _format_timestamp(), _get_model(), _get_threshold() (+7 more)

### Community 20 - "OpenRouter API Client"
Cohesion: 0.21
Nodes (3): OpenRouterClient, test_embed(), test_summarize()

### Community 21 - "CSS Minified Layout"
Cohesion: 0.17
Nodes (16): _a(), applyParallelOffset(), Bf(), en(), every(), ex(), Ff(), jf() (+8 more)

### Community 22 - "Embedding Model Migration"
Cohesion: 0.19
Nodes (13): cancel_reembed(), _count_pending(), estimate(), get_status(), Re-embed all transcript chunks under a new embedding model.  Triggered when the, Start a background re-embed task. No-op if one is already running., Cancel an in-flight re-embed run., Snapshot of the current re-embed run for the UI. (+5 more)

### Community 23 - "Search API (FTS + Semantic)"
Cohesion: 0.28
Nodes (11): AsyncSession, AsyncSession, search(), _get_distance_threshold(), _get_embedding_model(), Search engine: keyword (FTS) and semantic (pgvector cosine).  Semantic search: -, Semantic episode search.      Returns a dict (not a list) so the caller can surf, _safe_lang() (+3 more)

### Community 25 - "CSS Minified Spacing"
Cohesion: 0.19
Nodes (13): au(), br(), d2(), G2(), h2(), kt(), ly(), pm() (+5 more)

### Community 26 - "CSS Minified Selectors B"
Cohesion: 0.23
Nodes (13): ax(), ea(), kf(), lx(), OA(), sx(), _t(), TA() (+5 more)

### Community 27 - "CSS Minified Converters"
Cohesion: 0.21
Nodes (13): B(), Bh(), c(), c2(), convert(), cr(), J(), L() (+5 more)

### Community 28 - "CSS Minified Assignments"
Cohesion: 0.17
Nodes (12): Ae(), assign(), gg(), go(), Gs(), Ht(), hx(), Je() (+4 more)

### Community 29 - "CSS Prefix Detectors"
Cohesion: 0.24
Nodes (12): Ig(), isStretch(), Md(), old(), prefixed(), prefixer(), regexp(), replace() (+4 more)

### Community 30 - "Settings & Model Config API"
Cohesion: 0.29
Nodes (7): AsyncSession, Setting, _classify_chat_model(), get_settings(), list_models(), test_abs_connection(), update_settings()

### Community 31 - "Transcript Chunking & Indexing"
Cohesion: 0.29
Nodes (10): chunk_segments(), chunk_text(), chunk_transcript(), Chunking + embedding for transcripts.  Chunks are aligned to whisper segment tim, Word-based fallback chunker (no timestamps).      Used when whisper segments are, Pick the best chunker for what's available.      Prefer segment-aligned chunks (, One indexable chunk with optional audio-time alignment., Build word-aligned chunks from whisper segments.      Each chunk is a contiguous (+2 more)

### Community 32 - "Web UI Route Handlers"
Cohesion: 0.33
Nodes (8): Request, admin_page(), dashboard(), episode_view(), library_detail(), podcast_detail(), queue_page(), search_page()

### Community 33 - "CSS Arbitrary Properties"
Cohesion: 0.25
Nodes (9): arbitraryProperty(), dr(), jt(), $o(), Oh(), Te(), toResult(), V5() (+1 more)

### Community 34 - "PostCSS Raw Formatter"
Cohesion: 0.22
Nodes (9): rawBeforeClose(), rawBeforeComment(), rawBeforeOpen(), rawBeforeRule(), rawEmptyBody(), rawIndent(), rawSemicolon(), walk() (+1 more)

### Community 35 - "CSS Gradient Direction Fixer"
Cohesion: 0.25
Nodes (8): convertDirection(), fixAngle(), fixDirection(), fixRadial(), isRadial(), newDirection(), revertDirection(), roundFloat()

### Community 36 - "Whisper Transcription Service"
Cohesion: 0.57
Nodes (5): transcribe_audio(), _discover_endpoint(), _format_text(), transcribe_local(), transcribe_self_hosted()

### Community 37 - "CSS Minified Misc A"
Cohesion: 0.38
Nodes (7): Ah(), g_(), jo(), pr(), Sh(), virtual(), y_()

### Community 38 - "CSS Minified Misc B"
Cohesion: 0.33
Nodes (6): cm(), il(), mm(), rE(), U_(), z_()

### Community 39 - "Initial DB Schema Migration"
Cohesion: 0.40
Nodes (4): downgrade(), No-op: represents the legacy create_all schema., No-op: cannot downgrade past the baseline., upgrade()

### Community 42 - "CSS Minified Trio A"
Cohesion: 0.67
Nodes (3): bo(), TC(), Ue()

### Community 43 - "CSS Minified Trio B"
Cohesion: 0.67
Nodes (3): gk(), Np(), yk()

### Community 44 - "CSS Minified Trio C"
Cohesion: 1.00
Nodes (3): gR(), M0(), Yu()

### Community 45 - "CSS Minified Trio D"
Cohesion: 0.67
Nodes (3): hh(), Kn(), Xn()

### Community 46 - "CSS Minified Trio E"
Cohesion: 0.67
Nodes (3): $p(), V1(), z1()

## Knowledge Gaps
- **16 isolated node(s):** `@opencode-ai/plugin`, `BinaryIO`, `AsyncSession`, `GitHub Actions Release Workflow (Build & Push to ghcr.io)`, `Spotify-Inspired Design System Documentation` (+11 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `__()` connect `PostCSS Minified Library B` to `PostCSS Minified Library A`, `CSS Minified Cache Utils`, `CSS Minified DOM Helpers`, `CSS Minified Append/Clone`, `Tailwind CSS Utilities`, `CSS Minified Selectors`, `CSS Vendor Prefix Engine`, `CSS Minified Transforms`, `CSS Minified Parsers`, `CSS Minified Before Helpers`, `CSS Minified Iterators`, `PostCSS Rule Parser`, `CSS Minified Layout`, `CSS Minified Spacing`, `CSS Minified Selectors B`, `CSS Minified Converters`, `CSS Minified Assignments`, `CSS Prefix Detectors`, `CSS Arbitrary Properties`, `PostCSS Raw Formatter`, `CSS Gradient Direction Fixer`, `CSS Minified Misc A`, `CSS Minified Misc B`, `CSS Minified Trio A`, `CSS Minified Trio B`, `CSS Minified Trio C`, `CSS Minified Trio D`, `CSS Minified Trio E`, `CSS Minified Pair A`, `CSS Minified Pair B`, `CSS Minified Pair C`, `CSS Minified Pair D`, `CSS Minified Pair E`, `CSS Minified Pair F`, `CSS Minified Pair G`?**
  _High betweenness centrality (0.335) - this node is a cross-community bridge._
- **Why does `Setting` connect `Settings & Model Config API` to `Database & App Bootstrap`, `Whisper Transcription Service`, `App Config & Topic Clustering`, `RAG Question Answering`, `OpenRouter API Client`, `Embedding Model Migration`, `Search API (FTS + Semantic)`, `Transcript Chunking & Indexing`?**
  _High betweenness centrality (0.019) - this node is a cross-community bridge._
- **Why does `ABSSourceAdapter` connect `Audiobookshelf Source Adapter` to `Database & App Bootstrap`, `Settings & Model Config API`, `App Config & Topic Clustering`?**
  _High betweenness centrality (0.016) - this node is a cross-community bridge._
- **Are the 7 inferred relationships involving `OpenRouterClient` (e.g. with `AsyncSession` and `UUID`) actually correct?**
  _`OpenRouterClient` has 7 INFERRED edges - model-reasoned connections that need verification._
- **What connects `@opencode-ai/plugin`, `No-op: represents the legacy create_all schema.`, `No-op: cannot downgrade past the baseline.` to the rest of the system?**
  _42 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Database & App Bootstrap` be split into smaller, more focused modules?**
  _Cohesion score 0.06426182513139035 - nodes in this community are weakly interconnected._
- **Should `PostCSS Minified Library A` be split into smaller, more focused modules?**
  _Cohesion score 0.053075396825396824 - nodes in this community are weakly interconnected._