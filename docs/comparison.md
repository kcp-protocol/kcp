---
title: KCP vs Prior Art — Detailed Comparison
description: How KCP compares to Semantic Web (RDF/SPARQL), Model Context Protocol (MCP), Knowledge Graphs, Git, and other knowledge management technologies.
tags: [kcp, comparison, semantic-web, mcp, knowledge-graphs, git, rdf, sparql, ipfs, prior-art]
updated: "2026-03-20"
---

# KCP vs Prior Art — Detailed Comparison

## Overview

This document compares KCP with existing technologies that partially address knowledge management, context sharing, or data governance.

---

## 1. Semantic Web (RDF / OWL / SPARQL)

**What it is:** W3C standards for structured linked data on the web. Proposed by Tim Berners-Lee in 2001.

**What it does well:**
- ✅ Formal ontologies (OWL) for machine-readable semantics
- ✅ SPARQL for querying linked data
- ✅ JSON-LD for embedding structured data in web pages
- ✅ Schema.org for shared vocabulary

**Why it doesn't solve the KCP problem:**
- ❌ **Static data focus:** Designed for curated datasets, not dynamic AI-generated insights
- ❌ **No lineage:** Cannot trace data source → query → insight → decision
- ❌ **No multi-tenant governance:** No concept of organizational context (team, BU)
- ❌ **No auto-ingest:** Requires manual RDF authoring (high friction)
- ❌ **Adoption failure:** SPARQL endpoints never became mainstream (<0.1% of web)
- ❌ **Complexity barrier:** Requires ontology expertise that most developers lack

**Relationship to KCP:** KCP can use JSON-LD for metadata interop but operates at a different level — governing AI-generated knowledge, not curating static datasets.

---

## 2. Model Context Protocol (MCP)

**What it is:** Anthropic's protocol (2024) for sharing context between AI tools and agents.

**What it does well:**
- ✅ Standardized tool definitions for AI agents
- ✅ Real-time context sharing between tools
- ✅ Growing ecosystem (Claude, Cursor, IDEs)

**Why it doesn't solve the KCP problem:**
- ❌ **Session-scoped:** Context disappears when session ends
- ❌ **No persistence:** No mechanism to store outputs permanently
- ❌ **No discovery:** Cannot search for "who did similar analysis before?"
- ❌ **No lineage:** No provenance tracking
- ❌ **No governance:** No multi-tenant access control
- ❌ **Tool-focused:** Shares tool capabilities, not knowledge outputs

**Relationship to KCP:** MCP and KCP are **complementary**. MCP handles real-time tool-to-AI context. KCP handles persistent knowledge governance. An AI agent might use MCP to access tools and KCP to publish results.

```
AI Agent → MCP (real-time context) → Tool
AI Agent → KCP (persistent knowledge) → Knowledge Store
```

---

## 3. Knowledge Graphs (Google KG, Wikidata, Neo4j)

**What they do well:**
- ✅ Rich entity relationships
- ✅ Graph traversal for multi-hop queries
- ✅ Visualization of connections

**Why they don't solve the KCP problem:**
- ❌ **Entity-focused, not insight-focused:** Models entities (people, places, things), not analytical insights
- ❌ **No lineage tracking:** Knows "Company X has 500 employees" but not "this insight came from query Y on database Z"
- ❌ **No multi-tenant governance:** Open or single-org, no tiered access
- ❌ **Manual curation:** Requires human effort to maintain
- ❌ **No auto-ingest from AI:** No standard for AI agents to publish

---

## 4. Git / GitHub

**What it does well:**
- ✅ Version control with full history
- ✅ Content-addressed storage (SHA-1/SHA-256)
- ✅ Distributed (every clone is a full copy)
- ✅ Branch/merge for collaboration

**Why it doesn't solve the KCP problem:**
- ❌ **Code-focused:** Optimized for text diffs, not knowledge artifacts (HTML, JSON, images)
- ❌ **No semantic search:** Can grep text but not "find similar analyses"
- ❌ **No multi-tenant governance:** Public or private, no team-level tiers
- ❌ **No lineage:** Tracks file changes, not data source → insight chains
- ❌ **No auto-ingest:** Requires manual commit workflow
- ❌ **Poor for large files:** Binary artifacts bloat repos

---

## 5. Data Catalogs (DataHub, Amundsen, OpenMetadata)

**What they do well:**
- ✅ Dataset discovery and documentation
- ✅ Column-level lineage
- ✅ Data quality monitoring
- ✅ Governance and access policies

**Why they don't solve the KCP problem:**
- ❌ **Dataset-level only:** Catalogs datasets and tables, not analytical insights
- ❌ **No AI output governance:** Not designed for reports, visualizations, recommendations
- ❌ **Centralized architecture:** Single server, not federated
- ❌ **No semantic search:** Metadata search only, no vector similarity
- ❌ **No cross-org federation:** Single organization scope

---

## 6. Wiki / Confluence / Notion

**What they do well:**
- ✅ Document storage and organization
- ✅ Collaboration and comments
- ✅ Search (basic keyword)

**Why they don't solve the KCP problem:**
- ❌ **Manual curation:** Someone has to write/paste content manually
- ❌ **No auto-ingest:** No API for AI agents to publish automatically
- ❌ **No lineage:** No provenance tracking
- ❌ **No semantic search:** Keyword only, no vector similarity
- ❌ **Centralized:** Single vendor, no federation
- ❌ **No multi-format:** Primarily text, poor support for HTML reports, visualizations

---

## 7. RAG Systems (LangChain, LlamaIndex)

**What they do well:**
- ✅ Retrieval-Augmented Generation from documents
- ✅ Vector search for semantic similarity
- ✅ Integration with LLMs

**Why they don't solve the KCP problem:**
- ❌ **Consumption-focused:** Designed for reading existing docs, not publishing new insights
- ❌ **No governance:** No multi-tenant access control
- ❌ **No lineage:** Retrieves context but doesn't track provenance
- ❌ **Single-system:** Not a protocol; tied to specific framework
- ❌ **No federation:** Local vector store, no cross-org discovery

---

## Summary Matrix

| Feature | Semantic Web | MCP | KG | Git | Data Catalog | Wiki | RAG | **KCP** |
|---------|:-----------:|:---:|:--:|:---:|:------------:|:----:|:---:|:-------:|
| AI output governance | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Auto-ingest | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Lineage tracking | ❌ | ❌ | ❌ | Partial | Partial | ❌ | ❌ | ✅ |
| Semantic discovery | Partial | ❌ | Partial | ❌ | ❌ | ❌ | ✅ | ✅ |
| Multi-tenant governance | ❌ | ❌ | ❌ | ❌ | Partial | ❌ | ❌ | ✅ |
| P2P federation | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Content-addressed | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Digital signatures | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |
| Open protocol | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ |

**KCP is the first protocol to combine all these capabilities into a single, open standard.**

---

**Feedback:** https://github.com/tgosoul2019/kcp/issues
