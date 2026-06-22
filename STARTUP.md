# CT Queue System — Startup Guide

## Quick Start

```bash
honcho start
```

This starts three services:
1. **api** — Python FastAPI backend on http://127.0.0.1:8000
2. **frontend** — TanStack Start dev server on http://127.0.0.1:8080
3. **agents** — Band agents in sequential order (see below)

The `PYTHON_API_BASE_URL` env var is set automatically for the frontend.

---

## Agent Startup Order

Agents must start in sequence to allow each to fully register with Band before downstream agents attempt to communicate with it. The `scripts/start_agents_sequential.sh` script handles this:

1. **Router** (3s delay) — Parses CSV and normalizes case payloads
2. **Review** (3s delay) — Runs clinical urgency assessment
3. **Moderator** (3s delay) — Performs pairwise queue placement
4. **Escalation** — Handles human review cases

Each agent waits 3 seconds after the previous one starts, giving Band time to register the agent handle and make it visible to other agents.

---

## Manual Startup

If you need to start agents individually (e.g., for debugging):

```bash
# Terminal 1: API
python3 -m api

# Terminal 2: Frontend
cd frontend && PYTHON_API_BASE_URL=http://127.0.0.1:8000 npm run dev

# Terminal 3+: Agents (in order, each after the previous one logs "running")
python3 -m agents.run_router
python3 -m agents.run_review
python3 -m agents.run_moderator
python3 -m agents.run_escalation
```

Wait for each agent to show `"is running. Press Ctrl+C to stop"` before starting the next.

---

## Why Sequential?

The review agent sends a message to the moderator agent via Band. If the moderator hasn't finished its registration handshake when review tries to send, Band returns `ValueError: Unknown participant 'ct_moderator_agent'`. Sequential startup with 3-second delays ensures each agent is visible to the next before communication begins.

**Before**: Honcho started all agents in parallel → race condition on Band registration.  
**After**: Sequential startup with staggered initialization → guaranteed visibility.

---

## Checking Agent Status

When each agent is running, you'll see:

```
INFO:__main__:CT [Agent] Agent is running. Press Ctrl+C to stop.
```

The dashboard at http://127.0.0.1:8080 will load once the frontend and API are up.
The queue starts empty on purpose, so cases will not appear until you start a simulation.

---

## Running a Simulation

Once all three services (API, frontend, agents) are running, start the simulation from the UI or with:

```bash
curl -X POST http://127.0.0.1:8000/simulation/run \
  -H "Content-Type: application/json" \
  -d '{"limit": 3, "arrival_gap_seconds": 4, "start_delay_seconds": 0, "top_leave_after_seconds": 12}'
```

Cases will appear in the queue and flow through the agents.
