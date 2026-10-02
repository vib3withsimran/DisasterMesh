# Graph Report - DisasterMesh  (2026-10-02)

## Corpus Check
- 84 files · ~50,185 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1172 nodes · 2143 edges · 70 communities (57 shown, 13 thin omitted)
- Extraction: 82% EXTRACTED · 18% INFERRED · 0% AMBIGUOUS · INFERRED: 389 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `596ab5de`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- 🌐 DisasterMesh
- 🏗️ Architecture
- AGENTS.md
- graphify.md
- graphify.md
- 📦 Data schema
- VerifiedIncident
- schemas.py
- CommunicationAgent
- VerificationAgent
- seed_data.py
- Contributing to DisasterMesh
- test_ingest.py
- CitizenReportInput
- incidents.py
- __init__.py
- __init__.py
- __init__.py
- SatellitePolygonInput
- SensorStreamInput
- SocialPostInput
- AsyncSession
- CommunicationAgent
- test_schemas.py
- AsyncSession
- test_verification_integration.py
- .verify
- .upsert
- get_resource_agent
- vector_store.py
- TestNotificationMockMode
- _record_to_schema
- get_settings
- init_vector_store
- TestStateMachine
- .search_nearby
- main.py
- embeddings.py
- get_qdrant_client_sync
- .assess
- ExaMonitor
- conftest.py
- get_embedding_service
- SourceType
- conftest.py
- test_ingest.py
- main.py
- test_health.py
- get_qdrant_client
- communication.py
- get_vector_store
- SourceType
- MapView.tsx
- ._haversine
- incidents.py
- test_schemas.py
- AsyncClient
- test_qdrant_vector_search_latency
- DisasterMesh Frontend
- layout.tsx
- __init__.py
- __main__.py
- next.config.js

## God Nodes (most connected - your core abstractions)
1. `VictimAgent` - 57 edges
2. `VerifiedIncident` - 54 edges
3. `NeedsProfile` - 49 edges
4. `ResourceAgent` - 42 edges
5. `ProtoIncident` - 33 edges
6. `VectorStore` - 32 edges
7. `CommunicationAgent` - 30 edges
8. `SituationalAgent` - 30 edges
9. `Responder` - 30 edges
10. `OrchestratorAgent` - 25 edges

## Surprising Connections (you probably didn't know these)
- `test_citizen_report_input_valid()` --calls--> `CitizenReportInput`  [INFERRED]
  backend/app/tests/unit/test_schemas.py → backend/app/schemas.py
- `test_confidence_bounds()` --calls--> `VerifiedIncident`  [INFERRED]
  backend/app/tests/unit/test_schemas.py → backend/app/schemas.py
- `CommunicationAgent` --uses--> `CommunicationLog`  [INFERRED]
  backend/app/agents/communication.py → backend/app/models.py
- `CommunicationAgent` --uses--> `DispatchRecord`  [INFERRED]
  backend/app/agents/communication.py → backend/app/models.py
- `CommunicationAgent` --uses--> `ResponderRecord`  [INFERRED]
  backend/app/agents/communication.py → backend/app/models.py

## Import Cycles
- None detected.

## Communities (70 total, 13 thin omitted)

### Community 0 - "🌐 DisasterMesh"
Cohesion: 0.06
Nodes (30): 1️⃣ Situational Agent — Intake & Fusion, 1. Start the backend, 2. Launch the TUI dashboard (terminal), 2️⃣ Verification Agent — Dedup & Confidence, 3. Launch the web frontend (browser), 3️⃣ Victim Agent — Needs & Severity, 4️⃣ Resource Agent — Responder State, 5️⃣ Orchestrator Agent — Optimization & Dispatch (+22 more)

### Community 1 - "🏗️ Architecture"
Cohesion: 0.25
Nodes (20): _banner(), _c(), _err(), _get(), _info(), main(), _narration(), _ok() (+12 more)

### Community 5 - "📦 Data schema"
Cohesion: 0.08
Nodes (31): Normalizes all incoming data streams into ProtoIncident objects., Geocode (if needed), detect language, normalize to ProtoIncident., Normalize a social media post into a ProtoIncident., Extract the centroid of a GeoJSON polygon and normalise to a ProtoIncident., Normalize an IoT sensor reading into a ProtoIncident.          Applies threshold, Resolve an address string to (lat, lon).          Strategy:           1. Landmar, Helper to build a ProtoIncident from raw attributes and normalize it.          S, Idempotently store a proto incident (used by retry-queue fallback path). (+23 more)

### Community 6 - "VerifiedIncident"
Cohesion: 0.14
Nodes (26): Fetch a single responder by id; returns None if not found., Update a responder's GPS position.          Returns the updated Responder, or No, Score how well *responder* matches the incident's required capabilities., Tracks and queries the live responder registry.      All mutations are committed, ResourceAgent, LocationUpdate, Full responder representation — used by Resource Agent and API responses., Request body for ``POST /responders``. (+18 more)

### Community 7 - "schemas.py"
Cohesion: 0.10
Nodes (25): get_intake_queue(), IntakeQueue, Any, Intake Queue — Redis-backed retry queue for pending LLM intake parsing tasks (Ph, Return the shared IntakeQueue singleton., Queue for retrying failed LLM intake parsing requests., Get or create persistent Redis client., Close the Redis client. (+17 more)

### Community 8 - "CommunicationAgent"
Cohesion: 0.07
Nodes (29): App, DisasterMeshTUI, IncidentDetail, IncidentSummary, main(), Any, DisasterMesh TUI Dashboard -- terminal-based live incident monitoring.  Run the, DisasterMesh terminal dashboard -- live incident monitoring. (+21 more)

### Community 9 - "VerificationAgent"
Cohesion: 0.15
Nodes (20): OrchestratorAgent, Dispatch optimizer.      Uses a LangGraph StateGraph to manage the dispatch work, Run the LangGraph dispatch pipeline for *incident*.          Parameters, Batch multi-incident dispatch.          Runs the full LangGraph pipeline for eac, Convert a NeedsProfile to the capability dict expected by the solver.          `, Main entry point: verify + deduplicate a proto-incident.          Steps, Create a lone (single-member) cluster for a proto-incident that cannot         p, NeedsProfile (+12 more)

### Community 10 - "seed_data.py"
Cohesion: 0.20
Nodes (16): _jitter(), Seed script — populates demo_data/ with realistic mock records.  Usage:     cd b, Add small random noise to a coordinate so nearby reports aren't identical., Generate 25 realistic Hindi/English SMS-style citizen reports., Generate 20 realistic tweet-style social media posts., Generate 5 Sentinel-2 flood GeoJSON polygons., Generate 10 IoT sensor readings (water level + air quality)., Generate 8 mock responder teams with diverse capabilities. (+8 more)

### Community 12 - "test_ingest.py"
Cohesion: 0.12
Nodes (27): _build_dispatch_graph(), _cap_score(), commit_assignments(), DispatchState, _eta_seconds(), fetch_responders(), _haversine_m(), heuristic_assign() (+19 more)

### Community 13 - "CitizenReportInput"
Cohesion: 0.07
Nodes (31): get_intake_parser(), IntakeParserAgent, IntakeParsingError, Any, Intake Parser Agent — LLM Smart Intake Layer (Phase 4.5).  Uses LangChain's Chat, Parse raw unstructured text using Groq LLM via LangChain.          Retries trans, Return the shared IntakeParserAgent singleton., Raised when the intake parser cannot produce a ParsedIntake after retries. (+23 more)

### Community 14 - "incidents.py"
Cohesion: 0.09
Nodes (19): get_verification_agent(), Any, datetime, Verification Agent — Agent 2.  Responsibilities:   - Deduplicate reports using s, Determine which cluster to join (or create a new one).          Collect cluster_, Confidence = corroboration_factor × cross_source_bonus × stale_penalty, Choose the most authoritative / recent representative.          Priority order:, Return the shared VerificationAgent singleton. (+11 more)

### Community 22 - "SatellitePolygonInput"
Cohesion: 0.19
Nodes (14): get_orchestrator_agent(), AsyncSession, Return an OrchestratorAgent bound to *db* (a per-request AsyncSession)., BatchDispatchRequest, dispatch_incident(), _fetch_incident(), optimize_batch(), AsyncSession (+6 more)

### Community 23 - "SensorStreamInput"
Cohesion: 0.15
Nodes (18): _assess_body(), Integration tests for the VictimAgent assess endpoint — Phase 4.  Tests the full, Medical + rescue text in Delhi high-density zone → P1 or P2., Empty text → all needs=False, so base_needs_score=0.     Formula: (0 + 1.0 + pop, Response body must include all 6 scoring-factor keys., 3-source cluster should score higher than a 1-source cluster (same text)., Including satellite in provenance triggers the satellite_area factor., Valid request → 200 with well-formed SeverityAssessment JSON. (+10 more)

### Community 24 - "SocialPostInput"
Cohesion: 0.20
Nodes (11): LangChain-based vector store backed by Qdrant.      Wraps QdrantVectorStore for, Return the payload dict for the *verified* point with the given cluster_id., Return the payload dict for a verified incident cluster.          Thin alias for, VectorStore, memory_vector_store(), Integration tests for VectorStore with Qdrant — Phase 2.  Uses an in-memory Qdra, Create a fresh in-memory VectorStore for each test., test_ensure_collection_is_idempotent() (+3 more)

### Community 25 - "AsyncSession"
Cohesion: 0.05
Nodes (64): get_victim_agent(), _in_bbox(), Victim Agent — Agent 3.  Responsibilities:   - Extract needs (medical, shelter,, Return the shared VictimAgent singleton., Return True if (lat, lon) falls inside *bbox*., Extracts needs and computes severity for verified incidents., Assess needs and severity for a verified incident cluster.          Parameters, Fast bilingual keyword-based needs extraction. (+56 more)

### Community 26 - "CommunicationAgent"
Cohesion: 0.09
Nodes (25): Integration tests for the Communication Agent REST & WebSocket APIs — Phase 6., REPORTED → RESOLVED (skipping states) must return 422., Status transition for a non-existent cluster must return 404., When citizen_phone is provided, a CommunicationLog row must be written., GET /incidents/{id}/summary must return a valid SituationalSummary., human_summary must be a non-empty string containing key identifiers., GET /communications/logs?incident_id=unused should return []., After a citizen SMS is triggered, the log entry must be queryable. (+17 more)

### Community 27 - "test_schemas.py"
Cohesion: 0.20
Nodes (8): Communication Agent — Agent 6.  Responsibilities:   - Enforce the incident lifec, AuditLog, Base, DispatchRecord, SQLAlchemy ORM models for DisasterMesh.  Tables ------ raw_ingestion_records  —, Immutable record of each assignment made by the Orchestrator Agent.      Created, Immutable append-only audit trail — captures who/what/when for every     signifi, DeclarativeBase

### Community 28 - "AsyncSession"
Cohesion: 0.07
Nodes (46): Step-function penalty based on how old the proto-incident timestamp is., _mock_agent(), _proto(), Unit tests for VerificationAgent — Phase 3.  All tests mock VectorStore and Embe, Naive datetimes (no tzinfo) should be treated as UTC without raising., 1 fresh SMS, no cluster members → corroboration = 1/5 = 0.2., Adding more cluster members raises confidence., A satellite + SMS cluster should have higher confidence than all-SMS. (+38 more)

### Community 29 - "test_verification_integration.py"
Cohesion: 0.10
Nodes (29): Cosine similarity between two vectors.          Since normalize_embeddings=True,, embedding_service(), _ingest(), _now(), _proto(), datetime, Integration tests for VerificationAgent — Phase 3.  Uses an in-memory Qdrant ins, A satellite + 3× SMS cluster should have higher confidence than an     SMS-only (+21 more)

### Community 30 - ".verify"
Cohesion: 0.21
Nodes (7): ConnectionManager, Any, Real-time WebSocket endpoint for incident lifecycle updates.      Clients connec, Tracks all live WebSocket connections.      Thread-safety note: FastAPI runs in, Send *payload* as JSON to every connected client, evicting dead sockets., websocket_updates(), WebSocket

### Community 31 - ".upsert"
Cohesion: 0.10
Nodes (24): Generate a structured, human-readable situational summary for incident         c, assess_incident(), Run the VictimAgent needs-extraction and multi-factor severity scoring     pipel, AssessRequest, AssignedResponderSummary, Assignment, CommLogEntry, DispatchResult (+16 more)

### Community 32 - "get_resource_agent"
Cohesion: 0.18
Nodes (15): get_resource_agent(), AsyncSession, Return a ResourceAgent bound to *db* (a per-request AsyncSession)., create_responder(), get_responder(), list_responders(), AsyncSession, Responders router — CRUD for the live responder registry (Phase 5). (+7 more)

### Community 33 - "vector_store.py"
Cohesion: 0.22
Nodes (7): init_vector_store(), QdrantClient, Create the Qdrant collection if it doesn't exist, then bind         the LangChai, Initialise the VectorStore singleton and ensure the Qdrant collection exists., memory_vector_store(), Initialize an in-memory VectorStore for tests., QdrantVectorStore

### Community 34 - "TestNotificationMockMode"
Cohesion: 0.11
Nodes (13): CommunicationLog, Audit log of every outbound message dispatched by the CommunicationAgent.      A, Triggering a lifecycle transition that includes citizen_phone must write     ≥ 1, test_communication_log_written_for_full_pipeline(), _make_assignment(), Unit tests for CommunicationAgent — Phase 6.  All tests are fully mocked — no da, Verify notification dispatch works in demo mode (no Twilio credentials)., notify_responder_assignment returns True in mock mode. (+5 more)

### Community 35 - "_record_to_schema"
Cohesion: 0.13
Nodes (14): _haversine_m(), Resource Agent — Agent 4.  Responsibilities:   - Maintain live responder registr, Return all responders, optionally filtered by status., Update a responder's operational status.          When transitioning back to 'av, Return responders that are available within *radius_m* metres of the incident,, Great-circle distance in metres between two lat/lon points., Convert an ORM row to the Pydantic Responder schema., Create a new responder entry in the registry.          Returns the full Responde (+6 more)

### Community 36 - "get_settings"
Cohesion: 0.06
Nodes (40): async_sessionmaker, AsyncQdrantClient, API Authentication Module.  Provides secure API key verification for DisasterMes, Verify that the provided API key is valid.      Parameters     ----------     ap, verify_api_key(), get_settings(), DisasterMesh backend — application settings.  Loaded from environment variables, Return cached settings singleton. (+32 more)

### Community 37 - "init_vector_store"
Cohesion: 0.17
Nodes (9): _extract_vector(), _haversine_m(), Any, Vector Store — Phase 2.  Uses LangChain's QdrantVectorStore wrapper so both the, Normalize a Qdrant point's `.vector` field into a plain list[float].      Handle, Find ProtoIncident payloads (and optional vectors) within geo radius + optional, Fetch a payload by proto_id., Return ``(payload, vector)`` for every point whose ``proto_id`` payload (+1 more)

### Community 38 - "TestStateMachine"
Cohesion: 0.14
Nodes (8): _make_incident(), Walk the entire happy path in one test., Skipping states must raise ValueError., RESOLVED → anything must raise ValueError., Every IncidentStatus must have an entry in VALID_TRANSITIONS., transition() must return the same object (mutated), not a copy., Verify the lifecycle transition guard., TestStateMachine

### Community 39 - ".search_nearby"
Cohesion: 0.17
Nodes (8): _make_ws(), Unit tests for the WebSocket ConnectionManager — Phase 6.  Tests cover:   - conn, Repeated connect/disconnect cycles must keep the set consistent., Return a mock WebSocket with async accept / send_json / receive_text., Disconnecting a socket that was never connected must not raise., A client that raises on send_json must be removed from the active set., Broadcasting with no clients must not raise., TestConnectionManager

### Community 40 - "main.py"
Cohesion: 0.12
Nodes (15): CommunicationAgent, Any, AsyncSession, Notify a responder that they have been assigned to *incident*.          Sends an, Send a status-update SMS to the citizen who filed the report.          Parameter, Send *body* to *to_number* via Vonage, Twilio, or mock mode.          Priority:, Send SMS via Vonage Messages API (free tier: 200 SMS/month)., Send SMS/WhatsApp via Twilio REST API. (+7 more)

### Community 41 - "embeddings.py"
Cohesion: 0.15
Nodes (9): EmbeddingService, get_langchain_embeddings(), Embedding Service — Phase 2.  Uses LangChain's HuggingFaceEmbeddings wrapper aro, Embed a ProtoIncident using text + optional location context.          Appending, Embed multiple texts in a single batch call (more efficient than         calling, Return the shared LangChain HuggingFaceEmbeddings singleton.      First call dow, Async embedding service built on LangChain's HuggingFaceEmbeddings.      All pub, Encode a single text string into a 384-dim float list.          Uses LangChain's (+1 more)

### Community 42 - "get_qdrant_client_sync"
Cohesion: 0.05
Nodes (38): autoprefixer, eslint, eslint-config-next, dependencies, maplibre-gl, next, react, react-dom (+30 more)

### Community 43 - ".assess"
Cohesion: 0.09
Nodes (29): _detect_language(), _extract_geometry(), get_situational_agent(), _lookup_landmark(), _polygon_centroid(), Any, datetime, Situational Agent — Agent 1.  Responsibilities:   - Accept raw inputs from all f (+21 more)

### Community 44 - "ExaMonitor"
Cohesion: 0.09
Nodes (22): ExaMonitor, feed_exa_to_pipeline(), one_shot(), Any, Exa Social Media Monitor — DisasterMesh ========================================, Rotate through disaster queries., Search Exa for disaster-related posts.          Parameters         ----------, Normalize an Exa result into our standard format. (+14 more)

### Community 45 - "conftest.py"
Cohesion: 0.08
Nodes (16): DashboardPage(), MapView, EVENT_ICONS, EventFeedProps, STATUS_COLORS, IncidentCardProps, PRIORITY_STYLES, SOURCE_LABELS (+8 more)

### Community 46 - "get_embedding_service"
Cohesion: 0.33
Nodes (8): get_embedding_service(), Return the shared EmbeddingService singleton., Unit tests for EmbeddingService — Phase 2.  Run:     cd backend     pytest app/t, test_cosine_similarity(), test_embed_batch(), test_embed_incident_with_and_without_coords(), test_embed_text_english_and_hindi(), test_embed_text_returns_384_dims()

### Community 47 - "SourceType"
Cohesion: 0.18
Nodes (11): End-to-End Pipeline Integration Tests — Phase 7.  Validates the complete Disaste, 5 overlapping SMS reports about the Yamuna Bazar flood are ingested via     POST, A P1 VerifiedIncident with medical+rescue needs must receive ≥ 2     responders, Walk the complete 5-step lifecycle via POST /incidents/{id}/status and     asser, A WebSocket client connected before status transitions begin must receive     'l, Register *count* diverse responder teams. Returns list of IDs., _seed_responders(), test_citizen_sms_deduplication_pipeline() (+3 more)

### Community 48 - "conftest.py"
Cohesion: 0.07
Nodes (28): compilerOptions, allowJs, esModuleInterop, incremental, isolatedModules, jsx, lib, module (+20 more)

### Community 49 - "test_ingest.py"
Cohesion: 0.25
Nodes (3): Unit tests for the ingest endpoints.  Run:     cd backend     pytest app/tests/u, Accepts report with address but no lat/lon., test_ingest_citizen_report_address_only()

### Community 52 - "get_qdrant_client"
Cohesion: 0.14
Nodes (12): _cluster_id_to_point_id(), _proto_to_document(), Derive a stable integer point ID from a cluster_id string     (form: "cluster_<u, Convert a ProtoIncident to a LangChain Document.      page_content  = the text u, Store a ProtoIncident and its pre-computed embedding in Qdrant., Semantic similarity search using LangChain interface.          Returns list of (, Return the total number of points in the collection., Persist a :class:`~app.schemas.VerifiedIncident` back into the Qdrant         co (+4 more)

### Community 53 - "communication.py"
Cohesion: 0.21
Nodes (11): get_communication_agent(), Return the shared ``CommunicationAgent`` singleton., get_communication_logs(), get_situational_summary(), AsyncSession, Communication router — Phase 6.  Endpoints --------- POST /incidents/{cluster_id, Advance the incident lifecycle state machine.      Valid transitions:     ``REPO, Generate and return a structured situational summary for incident commanders. (+3 more)

### Community 54 - "get_vector_store"
Cohesion: 0.18
Nodes (9): get_vector_store(), Return the shared VectorStore singleton (initialised in main.py lifespan)., Integration tests for Dispatch & Responders REST APIs — Phase 5.  Validates:   -, test_dispatch_batch_optimize(), test_dispatch_cluster_flow(), A Sentinel-2 GeoJSON polygon and 3 SMS reports are ingested.     All 4 should la, An IoT water-level reading above the 3.0 m alert threshold is ingested     via P, test_iot_sensor_alert_pipeline() (+1 more)

### Community 55 - "SourceType"
Cohesion: 0.29
Nodes (9): Apply a lifecycle state transition to *incident* (in-place).          Parameters, _get_verified_incident(), Fetch a ``VerifiedIncident`` from the Qdrant vector store.      Raises     -----, IncidentStatus, Priority, SourceType, Embed and upsert a VerifiedIncident into the in-memory Qdrant store., _seed_verified_incident() (+1 more)

### Community 56 - "MapView.tsx"
Cohesion: 0.24
Nodes (9): createIncidentMarker(), createResponderMarker(), DARK_PAINT, MapView(), MapViewProps, NORMAL_PAINT, PRIORITY_COLORS, STATUS_COLORS (+1 more)

### Community 57 - "._haversine"
Cohesion: 0.22
Nodes (8): Distance in metres between two lat/lon points (great-circle)., Delhi (28.6139, 77.2090) → Agra (27.1767, 78.0081) ≈ 178 km ±10%., A point displaced ~140 m north should be within the 150 m window., A point displaced ~200 m north should be outside the 150 m window., test_haversine_boundary_150m_accepted(), test_haversine_boundary_151m_rejected(), test_haversine_known_distance(), test_haversine_zero()

### Community 58 - "incidents.py"
Cohesion: 0.31
Nodes (8): get_incident(), query_incidents(), Fetch a proto incident by ID from Qdrant vector store., Return incidents within `radius` metres of (lat, lon).      Returns verified inc, Transform a raw Qdrant payload into the frontend Incident interface.      Handle, Search incidents by semantic similarity using LangChain embeddings & Qdrant., search_incidents_semantic(), _transform_incident()

### Community 59 - "test_schemas.py"
Cohesion: 0.25
Nodes (7): Unit tests for Pydantic schemas.  Validates that models accept valid input and r, Address without lat/lon should be accepted (geocoded later)., Smoke-test the state machine transition table., test_citizen_report_input_address_only(), test_citizen_report_input_valid(), test_confidence_bounds(), test_lifecycle_transition_map()

### Community 60 - "AsyncClient"
Cohesion: 0.33
Nodes (6): AsyncClient, async_client(), async_client(), async_client(), ASGI test client — reuses the in-memory fixtures from conftest.py., async_client()

### Community 61 - "test_qdrant_vector_search_latency"
Cohesion: 0.33
Nodes (6): Convert a UUID string to an integer suitable as a Qdrant point ID., _uuid_to_int(), _dummy_vec(), Pre-load 1 000 ProtoIncidents (with dummy pre-computed vectors to avoid     embe, Deterministic unit-ish vector; avoids real embedding for bulk loads., test_qdrant_vector_search_latency()

### Community 62 - "DisasterMesh Frontend"
Cohesion: 0.40
Nodes (4): DisasterMesh Frontend, Environment Variables, Features, Setup

## Knowledge Gaps
- **96 isolated node(s):** `inter`, `metadata`, `MapView`, `EVENT_ICONS`, `STATUS_COLORS` (+91 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `VerifiedIncident` connect `VerificationAgent` to `TestNotificationMockMode`, `_record_to_schema`, `VerifiedIncident`, `TestStateMachine`, `main.py`, `test_schemas.py`, `test_ingest.py`, `incidents.py`, `get_qdrant_client`, `SatellitePolygonInput`, `SourceType`, `SocialPostInput`, `AsyncSession`, `CommunicationAgent`, `get_vector_store`, `.verify`, `.upsert`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `NeedsProfile` connect `VerificationAgent` to `TestNotificationMockMode`, `VerifiedIncident`, `TestStateMachine`, `main.py`, `test_ingest.py`, `CitizenReportInput`, `incidents.py`, `SourceType`, `SatellitePolygonInput`, `SourceType`, `get_vector_store`, `AsyncSession`, `CommunicationAgent`, `.verify`, `.upsert`?**
  _High betweenness centrality (0.067) - this node is a cross-community bridge._
- **Why does `VectorStore` connect `SocialPostInput` to `vector_store.py`, `init_vector_store`, `📦 Data schema`, `embeddings.py`, `VerificationAgent`, `CitizenReportInput`, `incidents.py`, `get_qdrant_client`, `get_vector_store`, `SatellitePolygonInput`, `test_verification_integration.py`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `VictimAgent` (e.g. with `NeedsProfile` and `Priority`) actually correct?**
  _`VictimAgent` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 27 inferred relationships involving `VerifiedIncident` (e.g. with `CommunicationAgent` and `DispatchState`) actually correct?**
  _`VerifiedIncident` has 27 INFERRED edges - model-reasoned connections that need verification._
- **Are the 41 inferred relationships involving `NeedsProfile` (e.g. with `DispatchState` and `OrchestratorAgent`) actually correct?**
  _`NeedsProfile` has 41 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `ResourceAgent` (e.g. with `DispatchState` and `OrchestratorAgent`) actually correct?**
  _`ResourceAgent` has 29 INFERRED edges - model-reasoned connections that need verification._