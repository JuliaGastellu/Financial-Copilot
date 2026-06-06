# AI Financial Copilot with Contextual Opportunity Engine

## Overview

This repository implements a local financial copilot that combines:

- A structured financial profile (cashflow, assets, liabilities, goals, preferences)
- A contextual knowledge base (ingested documents) retrieved through RAG
- A deterministic opportunity engine that filters and scores a local market opportunity dataset
- An explainability layer (decision trace, global decision context, constraint detection, and goal impact modeling)

The system is designed to support grounded question answering over ingested context and to generate auditable, outcome-driven recommendations without relying on an LLM for decision logic.

## Core Capabilities

- **Financial profile modeling and persistence**: create and update a `FinancialProfile` and store it in SQLite.
- **RAG-based contextual query system**: ingest documents, chunk them, index them in ChromaDB, and answer questions grounded in retrieved chunks with citations.
- **Opportunity engine**: load a local dataset of `InvestmentOpportunity` instruments and match them to a profile using deterministic filters and scoring.
- **Deterministic recommendation engine**: generate recommendations using tested, deterministic rules; an OpenAI LLM can optionally be used for synthesis only.
- **Decision trace and explainability**: expose filtering decisions, rejected opportunities with reasons, scoring breakdown per opportunity, and selection rationale.
- **Impact modeling on goals**: attach goal-level and recommendation-level impact estimates (time-to-goal change, probability-of-success estimate, allocation effect).
- **Constraint detection**: detect constraints such as negative cashflow, insufficient emergency fund, and high debt ratio; include them in decision outputs.
- **Offline mode**: run fully without OpenAI using hash-based embeddings and extractive answering.
- **Decision persistence**: store recommendation outputs (recommendations + decision context) as immutable decision records in SQLite.

## System Architecture

The implementation follows a layered structure:

- **API layer (FastAPI)**: request/response validation and endpoint definitions in `app/main.py`.
- **Service layer**: orchestration and use-cases in `app/services/financial_copilot.py`.
- **Domain models**
  - Financial profile and API schemas: `app/schemas/models.py`
  - Opportunity dataset model: `app/opportunity_engine/models.py`
  - Decision trace model: `app/opportunity_engine/decision_trace.py`
- **Data layer (SQLite)**: schema and repositories in `app/data/`
  - `profiles` table: user financial profiles
  - `documents` and `chunks` tables: ingested knowledge base source text
  - `decisions` table: persisted recommendation outputs
- **RAG layer (Chroma + embeddings + fallback)**: `app/rag/`
  - Ingestion: chunking + persistence + indexing
  - Retrieval: similarity retrieval from Chroma, with a repository-backed fallback path
  - Embeddings: OpenAI when enabled, stable hash embeddings in offline mode
- **Opportunity engine**: `app/opportunity_engine/`
  - Local dataset: `app/opportunity_engine/opportunities.json`
  - Repository: filtering by country and currency
  - Evaluation: deterministic filtering, scoring, and decision trace construction
- **Reasoning and decision engine**: `app/reasoning/`
  - Metrics: `metrics.py`
  - Constraints: `constraints.py`
  - Impact modeling and suggested allocation: `impact.py`
  - Recommendation and query generation: `engine.py`
- **Observability**: request id and structured JSON logging in `app/core/observability.py`

## Decision Flow

The `/recommendations` flow is deterministic and auditable:

1. **User profile load**: retrieve the stored `FinancialProfile` from SQLite.
2. **Context retrieval (RAG)**: retrieve macro/context chunks from ChromaDB (and build citations).
3. **Constraint detection**: detect constraints from the profile and computed metrics (cashflow, emergency fund coverage, debt ratio, high APR debt).
4. **Opportunity filtering**: filter opportunities by estimated available capital, risk tolerance, and goal liquidity/horizon constraints.
5. **Scoring**: compute a weighted score per eligible opportunity and record component scores.
6. **Recommendation generation**:
   - generate base rule-based recommendations
   - extend with opportunity-based recommendations (linked opportunities and match reasoning)
7. **Decision trace creation**: create a `DecisionTrace` capturing filters, rejections, scoring breakdown, and selection reasoning.
8. **Impact modeling**: attach `impacted_goals` and `projected_impact` to each recommendation using deterministic estimates.
9. **Decision persistence**: store the recommendations + global decision context as a decision record and return `decision_id` via `decision_context`.

## API Endpoints

All responses include an `X-Request-ID` header for request tracing.

### `GET /health`

- **Description**: health check.
- **Outputs**: `{ "status": "ok" }`.

### `PUT /profiles/{user_id}`

- **Description**: create or update a financial profile (persisted in SQLite).
- **Inputs**: `{ "profile": FinancialProfile }` where `profile.user_id` must match the path.
- **Outputs**: `{ "profile": FinancialProfile }`.
- **Errors**:
  - `400` if path `user_id` does not match `profile.user_id`.

### `GET /profiles/{user_id}`

- **Description**: fetch a stored profile.
- **Outputs**: `{ "profile": FinancialProfile }`.
- **Errors**:
  - `404` if the profile does not exist.

### `POST /context/ingest`

- **Description**: ingest a text document into the knowledge base (SQLite + ChromaDB).
- **Inputs**: `{ "title": string, "source": string|null, "content": string }`.
- **Outputs**: `{ "doc_id": string, "chunks_indexed": number }`.

### `POST /query`

- **Description**: grounded question answering over the ingested knowledge base (RAG).
- **Inputs**:
  - `user_id: string`
  - `query: string`
  - `top_k: number|null` (optional)
  - `include_recommendations: boolean` (optional, default `true`)
- **Outputs**:
  - `answer: string`
  - `citations: Citation[]`
  - `confidence: number (0..1)`
  - `mode: "offline" | "llm"`
  - `fallback_used: boolean`
  - `fallback_reason: string|null`
  - `recommendations: RecommendationItem[]` (empty when `include_recommendations=false`)

### `POST /recommendations`

- **Description**: generate deterministic recommendations grounded by retrieved context and matched opportunities.
- **Inputs**: `{ "user_id": string, "focus": string }`.
- **Outputs**:
  - `metrics: object`
  - `recommendations: RecommendationItem[]` (includes optional opportunity and explainability fields)
  - `mode: "offline" | "llm"`
  - `decision_context: object` (global decision context including `decision_id`)
- **Side effects**: persists a decision record to SQLite (`decisions` table).

### `GET /opportunities`

- **Description**: list opportunities from the local dataset.
- **Inputs** (query params):
  - `market_country: string|null`
  - `currency: string|null`
- **Outputs**: `InvestmentOpportunity[]`.

### `GET /opportunities/match/{user_id}`

- **Description**: evaluate and score opportunities for a user profile.
- **Outputs**:
  - `matches[]`: opportunity + scores + reasons
  - `decision_trace`: full decision trace for the evaluation
- **Errors**:
  - `404` if the profile does not exist.

### `GET /decisions/{user_id}`

- **Description**: list persisted decision records (most recent first).
- **Inputs**: `limit` query param (default `50`).
- **Outputs**: list of decisions containing:
  - `decision_id`, `user_id`, `created_at`
  - `recommendations`
  - `decision_context`
  - `mode`

## Example Response

The following example shows the structure returned by `POST /recommendations`. Values are representative and depend on the stored profile, ingested documents, and the local opportunity dataset.

```json
{
  "metrics": {
    "monthly_income": 7000.0,
    "monthly_expenses": 4500.0,
    "free_cashflow": 2500.0,
    "total_assets": 8000.0,
    "total_liabilities": 0.0,
    "emergency_fund_months": 1.78,
    "high_apr_debt_count": 0
  },
  "recommendations": [
    {
      "title": "Allocate free cashflow intentionally",
      "rationale": "Free cashflow is positive. Establish an allocation plan aligned with your goals before increasing risk exposure.",
      "actions": [
        "Define a monthly allocation split across emergency fund, debt payoff, and goal contributions.",
        "Review spending categories and automate transfers on payday."
      ],
      "risks": ["Over-allocation to illiquid instruments can conflict with near-term goals."],
      "sources": [
        {
          "doc_id": "doc_123",
          "chunk_id": "chunk_123_0",
          "title": "Macro note",
          "source": "manual"
        }
      ],
      "impacted_goals": [
        {
          "goal_name": "Down payment",
          "priority": "high",
          "horizon_months": 18,
          "capital_allocation_effect": {
            "estimated_monthly_allocation": 1250.0,
            "assumed_annual_return_mid": null
          },
          "time_to_goal_change": 0,
          "probability_of_success": 0.8,
          "confidence": 0.95
        }
      ],
      "projected_impact": {
        "time_delta": 0,
        "confidence": 0.95,
        "explanation": "Estimated impact assumes an average monthly allocation of 1250 from free cashflow."
      },
      "suggested_amount": 1250.0,
      "suggested_currency": "USD"
    },
    {
      "title": "Consider: US Treasury Bills (3M)",
      "rationale": "Capital check: minimum 100 USD, estimated available 10500 USD. Risk check: profile medium, instrument low. Goal horizon: 18 months; instrument horizon 1-6 months; liquidity high. Scores: capital=1.00, risk=0.75, liquidity=1.00, horizon=0.60.",
      "actions": [
        "Verify access requirements: Brokerage account.",
        "Confirm liquidity level (high) and horizon (1-6 months) fit your goals.",
        "Decide an amount that preserves an emergency buffer and respects minimum capital requirements."
      ],
      "risks": [
        "Risk level: low. Expected returns are uncertain and may be negative over short periods.",
        "This is a local dataset example, not live market data."
      ],
      "sources": [
        {
          "doc_id": "doc_123",
          "chunk_id": "chunk_123_0",
          "title": "Macro note",
          "source": "manual"
        }
      ],
      "opportunity": {
        "instrument_id": "us-tbill-3m",
        "instrument_name": "US Treasury Bills (3M)",
        "asset_class": "cash_equivalent",
        "market_country": "US",
        "currency": "USD",
        "minimum_capital": 100.0,
        "liquidity_level": "high",
        "expected_return_range": { "min_annual": 0.03, "max_annual": 0.055 },
        "risk_level": "low",
        "investment_horizon": { "min_months": 1, "max_months": 6 },
        "access_requirements": ["Brokerage account"],
        "source_name": "Public treasury guidance",
        "source_url": "https://home.treasury.gov/",
        "last_updated_at": "2026-03-20T00:00:00Z"
      },
      "match_reason": "Capital check: minimum 100 USD, estimated available 10500 USD. Risk check: profile medium, instrument low. Goal horizon: 18 months; instrument horizon 1-6 months; liquidity high. Scores: capital=1.00, risk=0.75, liquidity=1.00, horizon=0.60.",
      "match_score": 0.90,
      "score_components": {
        "capital_score": 1.0,
        "risk_score": 0.75,
        "liquidity_score": 1.0,
        "horizon_alignment_score": 0.6
      },
      "decision_trace": {
        "input_summary": {
          "user_id": "demo-user",
          "market_country": "US",
          "risk_tolerance": "medium",
          "estimated_available_capital": 10500.0,
          "goal_horizon_months": 18,
          "cashflow": { "monthly_income": 7000.0, "monthly_expenses": 4500.0, "free_cashflow": 2500.0 },
          "constraints_detected": [
            {
              "constraint_id": "insufficient_emergency_fund",
              "severity": "medium",
              "message": "Emergency fund coverage is below the recommended minimum.",
              "evidence": { "emergency_fund_months": 1.78 }
            }
          ]
        },
        "filters_applied": [
          "minimum_capital <= estimated_available_capital",
          "instrument_risk_level <= profile_risk_tolerance",
          "liquidity_level compatible with high-priority goal horizon (if present)"
        ],
        "eligible_opportunities": [
          {
            "instrument_id": "us-tbill-3m",
            "instrument_name": "US Treasury Bills (3M)",
            "risk_level": "low",
            "liquidity_level": "high",
            "minimum_capital": 100.0,
            "market_country": "US",
            "currency": "USD",
            "investment_horizon_months": { "min_months": 1, "max_months": 6 }
          }
        ],
        "rejected_opportunities": [
          {
            "instrument_id": "us-private-credit",
            "instrument_name": "Private Credit Fund",
            "reasons": ["liquidity_incompatible_with_goal_horizon"]
          }
        ],
        "scoring_breakdown": [
          {
            "instrument_id": "us-tbill-3m",
            "total_score": 0.90,
            "risk_score": 0.75,
            "liquidity_score": 1.0,
            "capital_score": 1.0,
            "horizon_alignment_score": 0.6,
            "details": {
              "weights": { "capital": 0.35, "risk": 0.25, "liquidity": 0.2, "horizon": 0.2 },
              "available_capital": 10500.0
            }
          }
        ],
        "selected_option_reason": "Selected US Treasury Bills (3M) (us-tbill-3m) because it has the highest total score (0.90) after applying minimum capital, risk tolerance, and liquidity constraints.",
        "alternatives_considered": []
      },
      "impacted_goals": [
        {
          "goal_name": "Down payment",
          "priority": "high",
          "horizon_months": 18,
          "capital_allocation_effect": {
            "estimated_monthly_allocation": 625.0,
            "assumed_annual_return_mid": 0.0425
          },
          "time_to_goal_change": 0,
          "probability_of_success": 0.9,
          "confidence": 0.95
        }
      ],
      "projected_impact": {
        "time_delta": 0,
        "confidence": 0.95,
        "explanation": "Estimated impact assumes an average monthly allocation of 1250 from free cashflow."
      },
      "suggested_amount": 1050.0,
      "suggested_currency": "USD"
    }
  ],
  "mode": "offline",
  "decision_context": {
    "decision_id": "2a7a9d58-3b52-4b2a-b1e8-9ad3f7e1b1c0",
    "user_financial_state": {
      "user_id": "demo-user",
      "country": "US",
      "risk_tolerance": "medium",
      "metrics": {
        "monthly_income": 7000.0,
        "monthly_expenses": 4500.0,
        "free_cashflow": 2500.0
      }
    },
    "constraints_detected": [
      {
        "constraint_id": "insufficient_emergency_fund",
        "severity": "medium",
        "message": "Emergency fund coverage is below the recommended minimum.",
        "evidence": { "emergency_fund_months": 1.78 }
      }
    ],
    "available_capital": 10500.0,
    "goals_summary": [
      { "name": "Down payment", "priority": "high", "target_amount": 20000, "horizon_months": 18 }
    ],
    "high_level_reasoning": [
      "Emergency fund coverage is below target; preserve liquidity before taking additional risk."
    ],
    "opportunity_engine_summary": {
      "eligible_count": 3,
      "rejected_count": 5,
      "selected_option_reason": "Selected US Treasury Bills (3M) (us-tbill-3m) because it has the highest total score (0.90) after applying minimum capital, risk tolerance, and liquidity constraints."
    }
  }
}
```

## Setup Instructions

### Requirements

- Python 3.11+ recommended

### Install dependencies

```bash
python -m pip install -r requirements.txt
```

### Run the API

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Run with Docker

Build the Docker image:

```bash
docker build -t financial-copilot:latest .
```

Run the container:

```bash
docker run --rm -p 8000:8000 financial-copilot:latest
```

If you want to load environment variables from a file, create a `.env` and run:

```bash
docker run --rm --env-file .env -p 8000:8000 financial-copilot:latest
```

Alternatively, if you prefer Docker Compose:

```bash
docker compose up --build
```

### Run tests

```bash
python -m pytest -q
```

## Environment Variables

The system runs in offline mode unless OpenAI is enabled. Settings are loaded via Pydantic; environment variable names are treated case-insensitively on typical setups.

- `OPENAI_API_KEY` (optional): enables OpenAI embeddings and LLM synthesis paths.
- `OPENAI_MODEL` (optional): overrides the model name used by the OpenAI chat client.
- `OFFLINE_MODE` (optional): if set to `true`, forces offline mode even if `OPENAI_API_KEY` is present.

## Running the System

- Start the server and use:
  - `http://127.0.0.1:8000/docs` for OpenAPI docs
  - `http://127.0.0.1:8000/` for the minimal UI
- Persistent storage:
  - SQLite database and Chroma persistence are written under `./data/` by default.
- Request tracing:
  - every response includes `X-Request-ID` and logs include the same id for correlation.

## Testing

The `pytest` suite covers:

- API endpoint behavior and contracts (`/profiles`, `/query`, `/recommendations`)
- RAG end-to-end (ingest → retrieve → grounded answer)
- Opportunity loading, filtering, matching, and decision traces
- Constraint detection and impact modeling structures
- Decision persistence (`/decisions/{user_id}`) and request tracing (`X-Request-ID`)
- Structured logging emission for core events (basic validation)

## Technical Decisions

- **Deterministic decision logic**: recommendation selection, constraint detection, and opportunity scoring are deterministic to make behavior testable and auditable.
- **RAG for grounding only**: retrieved context is used to ground explanations and provide citations; it is not used to make opaque investment decisions.
- **Offline-first operation**: offline embeddings and extractive answering ensure the system can start and function without external services.
- **Decision trace as a product feature**: the decision trace and decision context are first-class outputs to support review, debugging, and user-facing explainability.

## Limitations

- The opportunity dataset is local and intentionally small; it is not real-time market data.
- The impact model is simplified and uses deterministic heuristics; it is not a financial forecast.
- No authentication, multi-tenant isolation, or encryption at rest is implemented.
- No portfolio optimization, position sizing optimization, or tax-aware planning is implemented.
- Document ingestion is plain-text only (no PDF/HTML parsing).

## Future Improvements

- Add real market data integrations with explicit provenance and update schedules.
- Add portfolio allocation and risk budgeting with auditable constraints.
- Improve impact modeling using scenario analysis and sensitivity bounds.
- Expand the UI beyond the current minimal interaction page.
