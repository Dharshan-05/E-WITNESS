# E-WITNESS Web Client Workspace

Institutional digital evidence custody, incident triage, and case investigation web platform for campus misconduct and security operations.

## Architecture Overview (Phase 111)

The E-WITNESS frontend is built with:
- **Runtime & Build Tooling**: [Vite](https://vitejs.dev/) with React 18 & TypeScript 5.6
- **Styling & Design System**: [Tailwind CSS](https://tailwindcss.com/) with institutional design tokens (WCAG AA compliant contrast)
- **Routing**: [React Router DOM](https://reactrouter.com/) (v6) with layout hierarchy and future flag awareness
- **Icons**: [Lucide React](https://lucide.dev/)
- **API Client**: Strongly-typed HTTP client with correlation ID tracing (`X-Request-ID`), standardized `ErrorResponse` envelope parsing, and bearer token injection
- **Unit Testing**: [Vitest](https://vitest.dev/) with [Testing Library](https://testing-library.com/) and `jsdom`

---

## Security Boundary Invariants

1. **Zero Client-Side Authorization Reliance**: All RBAC, ABAC, and departmental tenant isolation boundaries are strictly enforced by the backend API and database row-level filters. Client-side route guards are for UX only.
2. **Zero Secret Storage**: Never embed API keys, database credentials, AWS S3 secret keys, or JWT signing keys in frontend source code, environment variables, or build outputs.
3. **Statutory AI Advisory Banner**: AI violence detection outputs are strictly non-authoritative candidate annotations. Every screen displaying AI predictions must present the statutory disclaimer.
4. **Biometric Prohibitions Maintained**: The platform adheres to `BIOMETRIC_MATCHING_ENABLED = False`. The frontend contains zero 1:N facial search or automated suspect tagging interfaces.

---

## Project Structure

```text
frontend/
├── .env.example             # Documented non-secret configuration template
├── .env                     # Local environment settings
├── eslint.config.js         # Flat ESLint 9 configuration with TS and React hooks
├── index.html               # Main HTML entry point with security CSP meta tags
├── package.json             # NPM package dependencies and scripts
├── postcss.config.js        # PostCSS configuration for Tailwind CSS
├── tailwind.config.js       # Institutional palette, typography, and container tokens
├── tsconfig.json            # Unified TypeScript configuration (strict mode)
├── vite.config.ts           # Vite build config with path aliases and dev proxy
├── public/
│   └── shield.svg           # Institutional brand mark
└── src/
    ├── main.tsx             # DOM mount entrypoint
    ├── App.tsx              # Root application router wrapper
    ├── index.css            # Global CSS, Tailwind layers, and accessibility focus styles
    ├── api/                 # Typed API client and endpoint consumers
    │   ├── client.ts        # ApiClient class with correlation ID and error normalization
    │   ├── health.ts        # Health check API callers (/health/live, /health/ready)
    │   └── index.ts
    ├── components/
    │   ├── layout/          # Institutional shell, Header, Sidebar, PageHeader, AppLayout
    │   └── ui/              # Reusable design primitives (Button, Badge, Card, Alert, etc.)
    ├── pages/               # Top-level route views and module placeholders
    │   ├── HomePage.tsx     # Executive workspace dashboard and navigation
    │   ├── HealthPage.tsx   # Live backend diagnostics probe view
    │   ├── IncidentsPlaceholderPage.tsx # Phase 113 boundary
    │   ├── CasesPlaceholderPage.tsx     # Phase 115 boundary
    │   ├── EvidencePlaceholderPage.tsx  # Phase 114 boundary
    │   ├── AuditPlaceholderPage.tsx     # Phase 118 boundary
    │   └── NotFoundPage.tsx # Accessible 404 error page
    ├── router/
    │   └── routes.tsx       # Route definitions and placeholder hierarchy
    ├── test/                # Vitest test suites
    │   ├── setup.ts         # Testing library setup and DOM mocks
    │   ├── apiClient.test.ts # API client unit test suite (8 tests)
    │   ├── ui.test.tsx      # Design system component test suite (10 tests)
    │   └── App.test.tsx     # Root application integration test suite (1 test)
    └── types/               # TypeScript interfaces mirrored from backend schemas
        ├── api.ts           # ApiError, PaginatedResponse, RequestOptions
        ├── auth.ts          # RoleCode, AccountStatus, User, Department, TokenResponse
        ├── incident.ts      # IncidentCategory, IncidentSeverity, IncidentStatus, Incident
        ├── case.ts          # CaseStatus, CasePriority, CaseNoteVisibility, Case, CaseNote
        ├── evidence.ts      # UploadStatus, EvidenceAttachment, LegalHold
        ├── ai.ts            # SegmentReviewStatus, AICandidateSegment, AI_ADVISORY_DISCLAIMER
        └── index.ts
```

---

## Getting Started

### Prerequisites

- Node.js `v20+` (Tested on Node v24.8.0)
- npm `v10+` (Tested on npm 11.5.2)

### Installation

```bash
cd frontend
npm install
```

### Environment Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Default configuration:
```env
VITE_API_BASE_URL=/api/v1
VITE_APP_TITLE=E-WITNESS Evidence Management
VITE_ENABLE_ANALYTICS=false
```

### Development Server

Start Vite with hot module replacement (HMR) and backend proxy:

```bash
npm run dev
```

The app will be available at `http://localhost:5173`. Requests to `/api` are automatically proxied to the backend at `http://127.0.0.1:8000`.

### Running Tests

```bash
# Run all Vitest suites
npm run test

# Run tests in watch mode
npm run test:watch
```

### Type Checking & Linting

```bash
# TypeScript compiler check (strict mode)
npm run typecheck

# ESLint flat config validation
npm run lint
```

### Production Build

```bash
npm run build
npm run preview
```
Production assets are emitted into `frontend/dist/`.
