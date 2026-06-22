# TriageFlow — Dashboard

A real-time dashboard for hospital radiology operations that uses agentic AI to intelligently prioritize CT scan queues. This frontend integrates with a Python backend powered by Band agents to provide clinicians with dynamic queue management and escalation handling.

## Features

- **Real-time Queue Visualization** — Live CT scan queue with dynamic reordering based on clinical urgency
- **AI-Driven Prioritization** — LangGraph-based agents evaluate clinical urgency and optimal queue placement
- **Human Review Integration** — Escalated cases route to clinical staff for human decision-making
- **Simulation Mode** — Demo mode to test queue behavior with realistic case flows
- **Responsive Design** — TailwindCSS + Radix UI for accessible, modern interface

## Tech Stack

- **Framework** — React 19 with TanStack Start (full-stack React)
- **Routing** — TanStack Router
- **Data Fetching** — TanStack React Query
- **UI Components** — Radix UI primitives + custom components
- **Styling** — TailwindCSS + class-variance-authority
- **Forms** — React Hook Form + Zod validation
- **Charts** — Recharts for queue analytics
- **Build** — Vite with TypeScript

## Getting Started

### Prerequisites
- Node.js 18+
- Python API running at `http://127.0.0.1:8000`

### Installation

```bash
npm install
```

### Development

Start the frontend dev server (connects to Python API):

```bash
PYTHON_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Then open `http://localhost:5173` in your browser.

### Build

```bash
npm run build
npm run preview  # Test production build locally
```

## Project Structure

```
src/
├── routes/          # TanStack Router pages
├── components/      # Reusable UI components
├── lib/            # Utility functions and API clients
├── styles/         # Global styles
└── types/          # TypeScript type definitions
```

## Key Components

- **Dashboard** — Main queue visualization and controls
- **Queue Display** — Real-time case list with urgency indicators
- **Simulation Controls** — Start/stop demo case flow
- **Escalation Panel** — Manage cases awaiting human review

## API Integration

The dashboard communicates with the Python backend:

```
GET /queue              # Fetch current queue state
GET /dashboard-summary  # Get queue analytics
POST /simulation/run    # Start simulation
POST /simulation/stop   # Stop simulation
```

See the main [project README](../README.md) for full backend setup instructions.

## Documentation

- [User Guide](docs/user-guide.md)
- [Backend Setup](../README.md)
- [Agent Architecture](../agents/README.md)
