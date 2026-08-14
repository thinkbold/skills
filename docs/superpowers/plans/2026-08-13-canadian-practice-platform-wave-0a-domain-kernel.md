# Canadian Practice Platform Wave 0A Domain Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone, tested TypeScript domain package that defines the platform's safe identifiers, tenant scope, errors, fixed-decimal money, periods, locales, generic rule-pack applicability, and auditable event/outbox contracts without implementing tax logic or a network service.

**Architecture:** Add a new `canadian-practice-platform/` npm workspace beside the existing skill so the current Python skill remains untouched. Wave 0A is a pure domain kernel with Zod boundary schemas and immutable value objects; database, HTTP, UI, connectors, and model calls are excluded. Subsequent Wave 0 plans consume only exports from `@canada-practice/domain` rather than reaching into its internal files.

**Tech Stack:** Node.js 24 LTS runtime target (Node 24–26 accepted for development), npm workspaces, TypeScript 7.0.2 in strict NodeNext mode, Vitest 4.1.10, Zod 4.4.3, decimal.js 10.6.0, GitHub Actions checkout/setup-node v6.

**Spec:** `docs/superpowers/specs/2026-08-13-canadian-practice-platform-wave-0-design.md`

## Global Constraints

- Keep the existing `assess-ontario-tenant-application/` skill and its Python tests unchanged.
- Create all new product code under `canadian-practice-platform/`.
- Target Node.js 24 LTS; accept Node.js majors 24, 25, and 26 for local development so the current Node 26 workspace can run the plan.
- Use npm workspaces and commit the generated `package-lock.json`.
- Use TypeScript `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, and NodeNext ESM.
- Use fixed-decimal values created from strings for authoritative money. Never accept JavaScript `number` as a money input.
- Keep core facts, identifiers, amounts, periods, states, and rule results language-neutral. Supported display locales are exactly `en-CA` and `fr-CA`; default to `en-CA`.
- Do not add production tax, payroll, GST/HST, QST, PST/RST, objection, filing, representation, or assurance-opinion calculations.
- Do not add a database, HTTP server, UI, cloud SDK, model SDK, or customer data.
- All boundary parsers must reject invalid or unsupported input explicitly. They must not coerce, estimate, or silently default except for the documented English locale default.
- Every task follows red-green-refactor: add a focused failing test, observe the expected failure, add the minimum implementation, run focused and full verification, then commit.
- Run commands from `canadian-practice-platform/` unless the step states that it runs from the repository root.
- Do not commit `.superpowers/`, `node_modules/`, `dist/`, coverage output, secrets, or generated customer-like fixtures.

---

## Wave 0 Plan Map

The approved Wave 0 specification contains five reviewable delivery units. Each unit produces working, testable software and receives its own implementation plan.

| Plan | Deliverable | Consumes | Exit criterion | Planning estimate |
|---|---|---|---|---:|
| **0A — Domain kernel (this plan)** | Pure TypeScript contracts and invariants | Approved Wave 0 spec | `@canada-practice/domain` builds and all invariant tests pass | 1–2 person-weeks |
| **0B — Tenancy, registry, policy, audit persistence** | PostgreSQL-backed API for firms, users, clients, entities, engagements, credentials, policy decisions, audit log, and transactional outbox | 0A public exports | Cross-tenant tests, separation-of-duties tests, and transactional audit/outbox tests pass | 4–6 person-weeks |
| **0C — Ledger, import, and reconciliation** | Native journals plus one file-based connector contract, idempotent import, account mapping, reconciliation, and exception queue | 0A and 0B | Balanced-ledger, deduplication, cursor-resume, reversal, and reconciliation fixtures pass | 5–8 person-weeks |
| **0D — Evidence, workpapers, and snapshots** | Canadian object-storage abstraction, evidence graph, workpaper review cycle, locked/released/superseded snapshots | 0A–0C | Complete-lineage, immutability, successor-diff, and release-gate tests pass | 6–9 person-weeks |
| **0E — Bilingual release slice and channel shells** | English/French rendering, practice/client vertical slice, Codex/ChatGPT plugin shell, operational controls, Canada-residency evidence | 0A–0D | Bilingual parity, all-channel authorization, backup/restore, data-route, and controlled-pilot acceptance tests pass | 5–8 person-weeks |

The estimates assume experienced product engineers and exclude waiting time for Canadian privacy counsel, bilingual domain review, licensed-professional control review, vendor contracting, and penetration testing. The implementation team must not begin 0B until 0A's public API and test suite are approved.

## Wave 0A File Map

```text
canadian-practice-platform/
|-- README.md                         # Scope, commands, package map, and non-goals
|-- package.json                      # Private npm workspace and root quality commands
|-- package-lock.json                 # Reproducible dependency graph generated by npm
|-- tsconfig.base.json                # Shared strict TypeScript compiler settings
`-- packages/
    `-- domain/
        |-- package.json              # @canada-practice/domain package contract
        |-- tsconfig.json             # Domain build configuration
        |-- tsconfig.test.json        # Strict typecheck for source and tests
        |-- src/
        |   |-- index.ts              # Only supported public exports
        |   |-- version.ts            # Package identity used by the scaffold smoke test
        |   |-- errors.ts             # Safe domain errors, Result, and Zod boundary mapping
        |   |-- identity.ts           # Branded IDs and hierarchical tenant scope
        |   |-- money.ts              # Fixed-decimal, currency-safe Money value object
        |   |-- period.ts             # Valid date-only and reporting-period values
        |   |-- locale.ts             # en-CA/fr-CA parsing and English default
        |   |-- rules.ts              # Generic rule-pack metadata and applicability gate
        |   `-- events.ts             # Domain/audit event and outbox-record contracts
        `-- test/
            |-- scaffold.test.ts
            |-- errors.test.ts
            |-- identity.test.ts
            |-- money.test.ts
            |-- period-locale.test.ts
            |-- rules.test.ts
            |-- events.test.ts
            `-- public-api.test.ts

.github/workflows/
`-- canadian-practice-platform-domain.yml  # Repeatable 0A verification on Node 24
```

## Public API Contract

Only `packages/domain/src/index.ts` is public. Downstream plans may import these names:

```ts
export {
  DOMAIN_PACKAGE_NAME,
  DOMAIN_SCHEMA_VERSION,
} from "./version.js";

export {
  DomainError,
  DomainErrorCodeSchema,
  err,
  ok,
  parseWithSchema,
  toPublicError,
  type DomainErrorCode,
  type PublicError,
  type Result,
} from "./errors.js";

export {
  ClientIdSchema,
  EngagementIdSchema,
  EntityIdSchema,
  EventIdSchema,
  FirmIdSchema,
  TenantIdSchema,
  TenantScopeSchema,
  UserIdSchema,
  createClientId,
  createEngagementId,
  createEntityId,
  createEventId,
  createFirmId,
  createTenantId,
  createUserId,
  parseTenantScope,
  type ClientId,
  type EngagementId,
  type EntityId,
  type EventId,
  type FirmId,
  type TenantId,
  type TenantScope,
  type UserId,
} from "./identity.js";

export {
  CurrencyCodeSchema,
  Money,
  type CurrencyCode,
  type MoneyJSON,
} from "./money.js";

export {
  DateOnlySchema,
  ReportingPeriodSchema,
  containsDate,
  parseDateOnly,
  parseReportingPeriod,
  type DateOnly,
  type ReportingPeriod,
} from "./period.js";

export {
  DEFAULT_LOCALE,
  EngagementLocaleSchema,
  parseEngagementLocale,
  type EngagementLocale,
} from "./locale.js";

export {
  EntityTypeSchema,
  PrimarySourceSchema,
  RulePackMetadataSchema,
  RulePackStatusSchema,
  ServiceTypeSchema,
  evaluateRulePackApplicability,
  type EntityType,
  type PrimarySource,
  type RuleApplicabilityContext,
  type RulePackMetadata,
  type RulePackStatus,
  type ServiceType,
} from "./rules.js";

export {
  ActorSchema,
  DomainEventEnvelopeSchema,
  OutboxRecordSchema,
  createDomainEvent,
  newPendingOutboxRecord,
  type Actor,
  type CreateDomainEventInput,
  type DomainEventEnvelope,
  type EventDependencies,
  type OutboxRecord,
} from "./events.js";
```

No downstream plan may import `@canada-practice/domain/src/*`.

### Task 1: Scaffold the npm workspace and domain package

**Files:**
- Modify: `.gitignore`
- Create: `canadian-practice-platform/package.json`
- Create: `canadian-practice-platform/package-lock.json` through `npm install`
- Create: `canadian-practice-platform/tsconfig.base.json`
- Create: `canadian-practice-platform/packages/domain/package.json`
- Create: `canadian-practice-platform/packages/domain/tsconfig.json`
- Create: `canadian-practice-platform/packages/domain/tsconfig.test.json`
- Create: `canadian-practice-platform/packages/domain/test/scaffold.test.ts`
- Create: `canadian-practice-platform/packages/domain/src/version.ts`
- Create: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: No product code. Uses npm and the versions fixed in this plan.
- Produces: `DOMAIN_PACKAGE_NAME: "@canada-practice/domain"` and `DOMAIN_SCHEMA_VERSION: 1`; root commands `npm run typecheck`, `npm test`, `npm run build`, and `npm run verify`.

- [ ] **Step 1: Extend repository ignores without changing existing entries**

Append these exact lines to the repository-root `.gitignore`:

```gitignore
.superpowers/
node_modules/
dist/
coverage/
*.tsbuildinfo
```

Run from the repository root:

```bash
git diff -- .gitignore
```

Expected: only the five ignore rules are added; the Python and worktree rules remain.

- [ ] **Step 2: Add workspace manifests and strict compiler configuration**

Create `canadian-practice-platform/package.json`:

```json
{
  "name": "canadian-practice-platform",
  "version": "0.0.0",
  "private": true,
  "packageManager": "npm@11.16.0",
  "engines": {
    "node": ">=24 <27",
    "npm": ">=11 <13"
  },
  "workspaces": [
    "packages/*",
    "apps/*"
  ],
  "scripts": {
    "build": "npm run build --workspaces --if-present",
    "test": "npm run test --workspaces --if-present",
    "typecheck": "npm run typecheck --workspaces --if-present",
    "verify": "npm run typecheck && npm test && npm run build"
  },
  "devDependencies": {
    "@types/node": "24.13.3",
    "typescript": "7.0.2",
    "vitest": "4.1.10"
  }
}
```

Create `canadian-practice-platform/tsconfig.base.json`:

```json
{
  "compilerOptions": {
    "target": "ES2024",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "lib": ["ES2024"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "exactOptionalPropertyTypes": true,
    "useUnknownInCatchVariables": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "verbatimModuleSyntax": true,
    "isolatedModules": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "skipLibCheck": true
  }
}
```

Create `canadian-practice-platform/packages/domain/package.json`:

```json
{
  "name": "@canada-practice/domain",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.js"
    }
  },
  "files": ["dist"],
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run",
    "typecheck": "tsc -p tsconfig.json --noEmit && tsc -p tsconfig.test.json"
  },
  "dependencies": {
    "decimal.js": "10.6.0",
    "zod": "4.4.3"
  }
}
```

Create `canadian-practice-platform/packages/domain/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "rootDir": "src",
    "outDir": "dist"
  },
  "include": ["src/**/*.ts"]
}
```

Create `canadian-practice-platform/packages/domain/tsconfig.test.json`:

```json
{
  "extends": "./tsconfig.json",
  "compilerOptions": {
    "rootDir": ".",
    "noEmit": true,
    "declaration": false,
    "declarationMap": false
  },
  "include": ["src/**/*.ts", "test/**/*.ts"]
}
```

- [ ] **Step 3: Write the failing scaffold test**

Create `canadian-practice-platform/packages/domain/test/scaffold.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  DOMAIN_PACKAGE_NAME,
  DOMAIN_SCHEMA_VERSION,
} from "../src/index.js";

describe("domain package scaffold", () => {
  it("publishes a stable package identity and schema version", () => {
    expect(DOMAIN_PACKAGE_NAME).toBe("@canada-practice/domain");
    expect(DOMAIN_SCHEMA_VERSION).toBe(1);
  });
});
```

- [ ] **Step 4: Install dependencies and verify the test fails for the missing public entrypoint**

Run:

```bash
npm install
npm test --workspace @canada-practice/domain
```

Expected: `package-lock.json` is created; the test fails because `../src/index.js` does not exist.

- [ ] **Step 5: Add the minimal package identity implementation**

Create `canadian-practice-platform/packages/domain/src/version.ts`:

```ts
export const DOMAIN_PACKAGE_NAME = "@canada-practice/domain" as const;
export const DOMAIN_SCHEMA_VERSION = 1 as const;
```

Create `canadian-practice-platform/packages/domain/src/index.ts`:

```ts
export {
  DOMAIN_PACKAGE_NAME,
  DOMAIN_SCHEMA_VERSION,
} from "./version.js";
```

- [ ] **Step 6: Run the task verification**

Run:

```bash
npm run verify
npm audit --audit-level=high
```

Expected: typecheck, one test, and build pass; audit reports no high or critical vulnerabilities.

- [ ] **Step 7: Commit the scaffold**

Run from the repository root:

```bash
git add .gitignore canadian-practice-platform/package.json canadian-practice-platform/package-lock.json canadian-practice-platform/tsconfig.base.json canadian-practice-platform/packages/domain
git commit -m "build: scaffold Canadian practice domain workspace"
```

### Task 2: Add safe domain errors and Result values

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/errors.ts`
- Create: `canadian-practice-platform/packages/domain/test/errors.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: Zod 4.4.3.
- Produces: `DomainError`, `DomainErrorCodeSchema`, `Result<T, E>`, `ok`, `err`, `parseWithSchema`, and `toPublicError`. Boundary validation exposes issue paths and codes but never rejected values.

- [ ] **Step 1: Write failing error-behaviour tests**

Create `canadian-practice-platform/packages/domain/test/errors.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  DomainError,
  err,
  ok,
  parseWithSchema,
  toPublicError,
} from "../src/index.js";

describe("domain errors", () => {
  it("maps boundary failures without returning rejected values", () => {
    const schema = z.object({ secret: z.string().min(8) });

    expect(() => parseWithSchema(schema, { secret: "short" }, "credential"))
      .toThrowError(DomainError);

    try {
      parseWithSchema(schema, { secret: "short" }, "credential");
    } catch (error) {
      const publicError = toPublicError(error);
      expect(publicError.code).toBe("VALIDATION_FAILED");
      expect(JSON.stringify(publicError)).not.toContain("short");
      expect(publicError.details).toEqual({
        context: "credential",
        issues: [{ code: "too_small", path: "secret" }],
      });
    }
  });

  it("uses a generic public error for unknown exceptions", () => {
    expect(toPublicError(new Error("database password leaked"))).toEqual({
      code: "INTERNAL_ERROR",
      message: "An internal error occurred.",
      details: {},
    });
  });

  it("represents success and failure without exceptions", () => {
    expect(ok("accepted")).toEqual({ ok: true, value: "accepted" });
    const failure = new DomainError("CONFLICT", "Version conflict.");
    expect(err(failure)).toEqual({ ok: false, error: failure });
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- errors.test.ts
```

Expected: FAIL because the error exports do not exist.

- [ ] **Step 3: Implement the exact safe-error contract**

Create `canadian-practice-platform/packages/domain/src/errors.ts`:

```ts
import { z, type ZodType } from "zod";

export const DomainErrorCodeSchema = z.enum([
  "VALIDATION_FAILED",
  "CURRENCY_MISMATCH",
  "BLOCKED_UNSUPPORTED",
  "AUTHORIZATION_DENIED",
  "CONFLICT",
  "IMMUTABLE_STATE",
  "TRANSIENT_DEPENDENCY",
  "INTERNAL_ERROR",
]);

export type DomainErrorCode = z.infer<typeof DomainErrorCodeSchema>;
export type SafeDetails = Readonly<Record<string, unknown>>;

export class DomainError extends Error {
  readonly code: DomainErrorCode;
  readonly safeDetails: SafeDetails;

  constructor(
    code: DomainErrorCode,
    message: string,
    safeDetails: SafeDetails = {},
  ) {
    super(message);
    this.name = "DomainError";
    this.code = code;
    this.safeDetails = Object.freeze({ ...safeDetails });
  }
}

export type Result<T, E extends DomainError = DomainError> =
  | Readonly<{ ok: true; value: T }>
  | Readonly<{ ok: false; error: E }>;

export const ok = <T>(value: T): Result<T, never> => ({ ok: true, value });

export const err = <E extends DomainError>(error: E): Result<never, E> => ({
  ok: false,
  error,
});

export function parseWithSchema<T>(
  schema: ZodType<T>,
  value: unknown,
  context: string,
): T {
  const parsed = schema.safeParse(value);
  if (parsed.success) {
    return parsed.data;
  }

  throw new DomainError("VALIDATION_FAILED", `Invalid ${context}.`, {
    context,
    issues: parsed.error.issues.map((issue) => ({
      code: issue.code,
      path: issue.path.join("."),
    })),
  });
}

export interface PublicError {
  readonly code: DomainErrorCode;
  readonly message: string;
  readonly details: SafeDetails;
}

export function toPublicError(error: unknown): PublicError {
  if (error instanceof DomainError) {
    return {
      code: error.code,
      message: error.message,
      details: error.safeDetails,
    };
  }

  return {
    code: "INTERNAL_ERROR",
    message: "An internal error occurred.",
    details: {},
  };
}
```

Add the error exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- errors.test.ts
npm run verify
```

Expected: three error tests and the scaffold test pass; typecheck and build pass.

- [ ] **Step 5: Commit the error contract**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/errors.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/errors.test.ts
git commit -m "feat: add safe domain error contract"
```

### Task 3: Add branded identifiers and hierarchical tenant scope

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/identity.ts`
- Create: `canadian-practice-platform/packages/domain/test/identity.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: `parseWithSchema` from Task 2 and Node `crypto.randomUUID`.
- Produces: branded tenant, firm, user, client, entity, engagement, and event IDs; `TenantScope`; deterministic ID factories that accept an optional UUID for tests.

- [ ] **Step 1: Write failing identity and hierarchy tests**

Create `canadian-practice-platform/packages/domain/test/identity.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  DomainError,
  createClientId,
  createEngagementId,
  createEntityId,
  createFirmId,
  createTenantId,
  parseTenantScope,
} from "../src/index.js";

const UUIDS = {
  tenant: "00000000-0000-4000-8000-000000000001",
  firm: "00000000-0000-4000-8000-000000000002",
  client: "00000000-0000-4000-8000-000000000003",
  entity: "00000000-0000-4000-8000-000000000004",
  engagement: "00000000-0000-4000-8000-000000000005",
} as const;

describe("identity", () => {
  it("creates prefixed branded identifiers", () => {
    expect(createTenantId(UUIDS.tenant)).toBe(`ten_${UUIDS.tenant}`);
    expect(createFirmId(UUIDS.firm)).toBe(`frm_${UUIDS.firm}`);
  });

  it("accepts a complete hierarchical scope", () => {
    const scope = parseTenantScope({
      tenantId: createTenantId(UUIDS.tenant),
      firmId: createFirmId(UUIDS.firm),
      clientId: createClientId(UUIDS.client),
      entityId: createEntityId(UUIDS.entity),
      engagementId: createEngagementId(UUIDS.engagement),
    });

    expect(scope.engagementId).toBe(`eng_${UUIDS.engagement}`);
  });

  it("rejects a deep scope with missing parents", () => {
    expect(() => parseTenantScope({
      tenantId: createTenantId(UUIDS.tenant),
      engagementId: createEngagementId(UUIDS.engagement),
    })).toThrowError(DomainError);
  });

  it("rejects an identifier with the wrong prefix", () => {
    expect(() => parseTenantScope({
      tenantId: `frm_${UUIDS.tenant}`,
    })).toThrowError(DomainError);
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- identity.test.ts
```

Expected: FAIL because identity exports do not exist.

- [ ] **Step 3: Implement branded IDs and the scope parser**

Create `canadian-practice-platform/packages/domain/src/identity.ts`:

```ts
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { parseWithSchema } from "./errors.js";

type Brand<T, Name extends string> = T & { readonly __brand: Name };

export type TenantId = Brand<string, "TenantId">;
export type FirmId = Brand<string, "FirmId">;
export type UserId = Brand<string, "UserId">;
export type ClientId = Brand<string, "ClientId">;
export type EntityId = Brand<string, "EntityId">;
export type EngagementId = Brand<string, "EngagementId">;
export type EventId = Brand<string, "EventId">;

const prefixedUuidSchema = <T extends string>(prefix: T) =>
  z.string().refine((value) => {
    if (!value.startsWith(`${prefix}_`)) {
      return false;
    }
    return z.string().uuid().safeParse(value.slice(prefix.length + 1)).success;
  }, `Expected ${prefix}_ followed by a UUID`);

export const TenantIdSchema = prefixedUuidSchema("ten")
  .transform((value) => value as TenantId);
export const FirmIdSchema = prefixedUuidSchema("frm")
  .transform((value) => value as FirmId);
export const UserIdSchema = prefixedUuidSchema("usr")
  .transform((value) => value as UserId);
export const ClientIdSchema = prefixedUuidSchema("cli")
  .transform((value) => value as ClientId);
export const EntityIdSchema = prefixedUuidSchema("ent")
  .transform((value) => value as EntityId);
export const EngagementIdSchema = prefixedUuidSchema("eng")
  .transform((value) => value as EngagementId);
export const EventIdSchema = prefixedUuidSchema("evt")
  .transform((value) => value as EventId);

const createId = <T>(
  prefix: string,
  schema: z.ZodType<T>,
  uuid: string,
): T => parseWithSchema(schema, `${prefix}_${uuid}`, `${prefix} identifier`);

export const createTenantId = (uuid = randomUUID()): TenantId =>
  createId("ten", TenantIdSchema, uuid);
export const createFirmId = (uuid = randomUUID()): FirmId =>
  createId("frm", FirmIdSchema, uuid);
export const createUserId = (uuid = randomUUID()): UserId =>
  createId("usr", UserIdSchema, uuid);
export const createClientId = (uuid = randomUUID()): ClientId =>
  createId("cli", ClientIdSchema, uuid);
export const createEntityId = (uuid = randomUUID()): EntityId =>
  createId("ent", EntityIdSchema, uuid);
export const createEngagementId = (uuid = randomUUID()): EngagementId =>
  createId("eng", EngagementIdSchema, uuid);
export const createEventId = (uuid = randomUUID()): EventId =>
  createId("evt", EventIdSchema, uuid);

export const TenantScopeSchema = z.object({
  tenantId: TenantIdSchema,
  firmId: FirmIdSchema.optional(),
  clientId: ClientIdSchema.optional(),
  entityId: EntityIdSchema.optional(),
  engagementId: EngagementIdSchema.optional(),
}).strict().superRefine((scope, context) => {
  if ((scope.clientId || scope.entityId || scope.engagementId) && !scope.firmId) {
    context.addIssue({
      code: "custom",
      path: ["firmId"],
      message: "firmId is required for client, entity, or engagement scope",
    });
  }
  if ((scope.entityId || scope.engagementId) && !scope.clientId) {
    context.addIssue({
      code: "custom",
      path: ["clientId"],
      message: "clientId is required for entity or engagement scope",
    });
  }
  if (scope.engagementId && !scope.entityId) {
    context.addIssue({
      code: "custom",
      path: ["entityId"],
      message: "entityId is required for engagement scope",
    });
  }
});

export type TenantScope = z.infer<typeof TenantScopeSchema>;

export const parseTenantScope = (value: unknown): TenantScope =>
  parseWithSchema(TenantScopeSchema, value, "tenant scope");
```

Add all identity exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- identity.test.ts
npm run verify
```

Expected: all four identity tests pass and the full suite builds.

- [ ] **Step 5: Commit the identity contract**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/identity.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/identity.test.ts
git commit -m "feat: add tenant-scoped domain identifiers"
```

### Task 4: Add fixed-decimal, currency-safe Money

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/money.ts`
- Create: `canadian-practice-platform/packages/domain/test/money.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: `DomainError` and `parseWithSchema` from Task 2; decimal.js 10.6.0.
- Produces: immutable `Money`, `CurrencyCode`, and `MoneyJSON`. `Money.from` accepts `unknown` at runtime but validates a decimal string and a three-letter uppercase currency.

- [ ] **Step 1: Write failing money invariant tests**

Create `canadian-practice-platform/packages/domain/test/money.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { DomainError, Money } from "../src/index.js";

describe("Money", () => {
  it("adds decimal values without binary floating-point drift", () => {
    const result = Money.from({ amount: "0.1", currency: "CAD" })
      .add(Money.from({ amount: "0.2", currency: "CAD" }));

    expect(result.toJSON()).toEqual({ amount: "0.3", currency: "CAD" });
  });

  it("rejects JavaScript number inputs", () => {
    expect(() => Money.from({ amount: 0.1, currency: "CAD" }))
      .toThrowError(DomainError);
  });

  it("rejects exponent and formatted strings", () => {
    expect(() => Money.from({ amount: "1e3", currency: "CAD" }))
      .toThrowError(DomainError);
    expect(() => Money.from({ amount: "1,000.00", currency: "CAD" }))
      .toThrowError(DomainError);
  });

  it("blocks arithmetic across currencies", () => {
    const cad = Money.from({ amount: "10.00", currency: "CAD" });
    const usd = Money.from({ amount: "1.00", currency: "USD" });

    expect(() => cad.add(usd)).toThrowError(DomainError);
    try {
      cad.add(usd);
    } catch (error) {
      expect(error).toMatchObject({ code: "CURRENCY_MISMATCH" });
    }
  });

  it("supports subtract, negate, equality, and zero", () => {
    const ten = Money.from({ amount: "10.00", currency: "CAD" });
    const three = Money.from({ amount: "3", currency: "CAD" });

    expect(ten.subtract(three).toJSON().amount).toBe("7");
    expect(three.negate().toJSON().amount).toBe("-3");
    expect(Money.zero("CAD").equals(Money.from({ amount: "0.00", currency: "CAD" }))).toBe(true);
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- money.test.ts
```

Expected: FAIL because `Money` is not exported.

- [ ] **Step 3: Implement Money without implicit rounding**

Create `canadian-practice-platform/packages/domain/src/money.ts`:

```ts
import Decimal from "decimal.js";
import { z } from "zod";
import { DomainError, parseWithSchema } from "./errors.js";

const AccountingDecimal = Decimal.clone({
  precision: 40,
  rounding: Decimal.ROUND_HALF_EVEN,
});

export const CurrencyCodeSchema = z.string().regex(/^[A-Z]{3}$/)
  .transform((value) => value as CurrencyCode);
export type CurrencyCode = string & { readonly __brand: "CurrencyCode" };

const MoneyInputSchema = z.object({
  amount: z.string().regex(/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/),
  currency: CurrencyCodeSchema,
}).strict();

export interface MoneyJSON {
  readonly amount: string;
  readonly currency: CurrencyCode;
}

export class Money {
  readonly #amount: Decimal;
  readonly currency: CurrencyCode;

  private constructor(amount: Decimal, currency: CurrencyCode) {
    this.#amount = amount;
    this.currency = currency;
    Object.freeze(this);
  }

  static from(value: unknown): Money {
    const parsed = parseWithSchema(MoneyInputSchema, value, "money");
    return new Money(new AccountingDecimal(parsed.amount), parsed.currency);
  }

  static zero(currency: string): Money {
    return Money.from({ amount: "0", currency });
  }

  add(other: Money): Money {
    this.#assertSameCurrency(other);
    return new Money(this.#amount.plus(other.#amount), this.currency);
  }

  subtract(other: Money): Money {
    this.#assertSameCurrency(other);
    return new Money(this.#amount.minus(other.#amount), this.currency);
  }

  negate(): Money {
    return new Money(this.#amount.negated(), this.currency);
  }

  equals(other: Money): boolean {
    return this.currency === other.currency && this.#amount.equals(other.#amount);
  }

  toJSON(): MoneyJSON {
    return { amount: this.#amount.toString(), currency: this.currency };
  }

  #assertSameCurrency(other: Money): void {
    if (this.currency !== other.currency) {
      throw new DomainError(
        "CURRENCY_MISMATCH",
        "Money currencies must match.",
        { leftCurrency: this.currency, rightCurrency: other.currency },
      );
    }
  }
}
```

Add the money exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- money.test.ts
npm run verify
```

Expected: five money tests pass; no authoritative amount is created from a JavaScript number.

- [ ] **Step 5: Commit the Money value object**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/money.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/money.test.ts
git commit -m "feat: add fixed-decimal money value object"
```

### Task 5: Add valid reporting periods and bilingual locale values

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/period.ts`
- Create: `canadian-practice-platform/packages/domain/src/locale.ts`
- Create: `canadian-practice-platform/packages/domain/test/period-locale.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: `parseWithSchema` from Task 2.
- Produces: calendar-valid `DateOnly`, inclusive `ReportingPeriod`, `containsDate`, and `EngagementLocale` with exact values `en-CA`/`fr-CA` and default `en-CA`.

- [ ] **Step 1: Write failing date and locale tests**

Create `canadian-practice-platform/packages/domain/test/period-locale.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  DEFAULT_LOCALE,
  DomainError,
  containsDate,
  parseDateOnly,
  parseEngagementLocale,
  parseReportingPeriod,
} from "../src/index.js";

describe("reporting periods", () => {
  it("accepts a valid leap day and rejects impossible dates", () => {
    expect(parseDateOnly("2028-02-29")).toBe("2028-02-29");
    expect(() => parseDateOnly("2027-02-29")).toThrowError(DomainError);
  });

  it("requires an ordered inclusive period", () => {
    const period = parseReportingPeriod({
      start: "2026-01-01",
      end: "2026-12-31",
    });
    expect(containsDate(period, parseDateOnly("2026-12-31"))).toBe(true);
    expect(() => parseReportingPeriod({
      start: "2026-12-31",
      end: "2026-01-01",
    })).toThrowError(DomainError);
  });
});

describe("engagement locales", () => {
  it("defaults only absent input to English", () => {
    expect(DEFAULT_LOCALE).toBe("en-CA");
    expect(parseEngagementLocale(undefined)).toBe("en-CA");
  });

  it("accepts French and rejects unsupported locales", () => {
    expect(parseEngagementLocale("fr-CA")).toBe("fr-CA");
    expect(() => parseEngagementLocale("en-US")).toThrowError(DomainError);
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- period-locale.test.ts
```

Expected: FAIL because period and locale exports do not exist.

- [ ] **Step 3: Implement calendar-safe date-only and period schemas**

Create `canadian-practice-platform/packages/domain/src/period.ts`:

```ts
import { z } from "zod";
import { parseWithSchema } from "./errors.js";

export type DateOnly = string & { readonly __brand: "DateOnly" };

const isCalendarDate = (value: string): boolean => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return false;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  date.setUTCHours(0, 0, 0, 0);
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
};

export const DateOnlySchema = z.string()
  .refine(isCalendarDate, "Expected a calendar-valid YYYY-MM-DD date")
  .transform((value) => value as DateOnly);

export const ReportingPeriodSchema = z.object({
  start: DateOnlySchema,
  end: DateOnlySchema,
}).strict().refine((period) => period.start <= period.end, {
  message: "Reporting period start must not be after end",
  path: ["end"],
});

export type ReportingPeriod = z.infer<typeof ReportingPeriodSchema>;

export const parseDateOnly = (value: unknown): DateOnly =>
  parseWithSchema(DateOnlySchema, value, "date");

export const parseReportingPeriod = (value: unknown): ReportingPeriod =>
  parseWithSchema(ReportingPeriodSchema, value, "reporting period");

export const containsDate = (
  period: ReportingPeriod,
  date: DateOnly,
): boolean => period.start <= date && date <= period.end;
```

- [ ] **Step 4: Implement the exact bilingual locale boundary**

Create `canadian-practice-platform/packages/domain/src/locale.ts`:

```ts
import { z } from "zod";
import { parseWithSchema } from "./errors.js";

export const EngagementLocaleSchema = z.enum(["en-CA", "fr-CA"]);
export type EngagementLocale = z.infer<typeof EngagementLocaleSchema>;
export const DEFAULT_LOCALE: EngagementLocale = "en-CA";

export const parseEngagementLocale = (value: unknown): EngagementLocale =>
  value === undefined
    ? DEFAULT_LOCALE
    : parseWithSchema(EngagementLocaleSchema, value, "engagement locale");
```

Add the period and locale exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 5: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- period-locale.test.ts
npm run verify
```

Expected: four tests pass; leap-day validation and locale refusal are deterministic.

- [ ] **Step 6: Commit periods and locales**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/period.ts canadian-practice-platform/packages/domain/src/locale.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/period-locale.test.ts
git commit -m "feat: add reporting period and locale contracts"
```

### Task 6: Add the generic versioned rule-pack applicability gate

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/rules.ts`
- Create: `canadian-practice-platform/packages/domain/test/rules.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: `DateOnlySchema`, `UserIdSchema`, `DomainError`, `Result`, `ok`, and `err`.
- Produces: language-neutral entity/service enums, primary-source metadata, published-rule validation, and `evaluateRulePackApplicability(metadata, context): Result<RulePackMetadata, DomainError>`.

- [ ] **Step 1: Write failing rule-pack release and applicability tests**

Create `canadian-practice-platform/packages/domain/test/rules.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  DomainError,
  RulePackMetadataSchema,
  createUserId,
  evaluateRulePackApplicability,
  parseDateOnly,
  parseWithSchema,
} from "../src/index.js";

const authorId = createUserId("00000000-0000-4000-8000-000000000011");
const reviewerId = createUserId("00000000-0000-4000-8000-000000000012");
const approverId = createUserId("00000000-0000-4000-8000-000000000013");

const publishedPack = {
  stableId: "ca.federal.bookkeeping.base",
  version: "1.0.0",
  status: "published",
  jurisdictions: ["CA"],
  entityTypes: ["ccpc", "corporation"],
  service: "bookkeeping",
  effectiveFrom: "2026-01-01",
  effectiveTo: "2026-12-31",
  reviewedAt: "2026-07-01",
  expiresAt: "2026-12-31",
  sources: [{
    url: "https://www.canada.ca/en/revenue-agency/services/forms-publications/publications/ic05-1/electronic-record-keeping.html",
    publishedOrUpdatedOn: "2025-01-01",
    reviewedOn: "2026-07-01",
  }],
  fixtureIds: ["balanced-journal-v1"],
  authorId,
  independentReviewerId: reviewerId,
  qualifiedApproverId: approverId,
} as const;

describe("rule packs", () => {
  it("accepts an independently reviewed published pack", () => {
    const metadata = parseWithSchema(
      RulePackMetadataSchema,
      publishedPack,
      "rule pack",
    );
    const result = evaluateRulePackApplicability(metadata, {
      jurisdiction: "CA",
      entityType: "ccpc",
      service: "bookkeeping",
      asOf: parseDateOnly("2026-08-13"),
    });
    expect(result.ok).toBe(true);
  });

  it("rejects self-review on a published pack", () => {
    expect(() => parseWithSchema(RulePackMetadataSchema, {
      ...publishedPack,
      independentReviewerId: authorId,
    }, "rule pack")).toThrowError(DomainError);
  });

  it.each([
    ["expired", { asOf: "2027-01-01", jurisdiction: "CA", entityType: "ccpc", service: "bookkeeping" }],
    ["wrong jurisdiction", { asOf: "2026-08-13", jurisdiction: "QC", entityType: "ccpc", service: "bookkeeping" }],
    ["wrong entity", { asOf: "2026-08-13", jurisdiction: "CA", entityType: "trust", service: "bookkeeping" }],
    ["wrong service", { asOf: "2026-08-13", jurisdiction: "CA", entityType: "ccpc", service: "direct_tax" }],
  ] as const)("fails closed when %s", (_label, input) => {
    const metadata = parseWithSchema(RulePackMetadataSchema, publishedPack, "rule pack");
    const result = evaluateRulePackApplicability(metadata, {
      ...input,
      asOf: parseDateOnly(input.asOf),
    });
    expect(result).toEqual({
      ok: false,
      error: expect.objectContaining({ code: "BLOCKED_UNSUPPORTED" }),
    });
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- rules.test.ts
```

Expected: FAIL because rule-pack exports do not exist.

- [ ] **Step 3: Implement metadata validation and fail-closed applicability**

Create `canadian-practice-platform/packages/domain/src/rules.ts`:

```ts
import { z } from "zod";
import { DomainError, err, ok, type Result } from "./errors.js";
import { UserIdSchema } from "./identity.js";
import { DateOnlySchema, type DateOnly } from "./period.js";

export const EntityTypeSchema = z.enum([
  "corporation",
  "ccpc",
  "sole_proprietorship",
  "partnership",
  "trust",
  "non_profit",
  "charity",
]);
export type EntityType = z.infer<typeof EntityTypeSchema>;

export const ServiceTypeSchema = z.enum([
  "bookkeeping",
  "direct_tax",
  "payroll",
  "indirect_tax",
  "tax_planning",
  "cra_dispute",
  "assurance",
]);
export type ServiceType = z.infer<typeof ServiceTypeSchema>;

export const RulePackStatusSchema = z.enum([
  "draft",
  "reviewed",
  "published",
  "retired",
]);
export type RulePackStatus = z.infer<typeof RulePackStatusSchema>;

export const PrimarySourceSchema = z.object({
  url: z.string().url().refine((value) => value.startsWith("https://")),
  publishedOrUpdatedOn: DateOnlySchema,
  reviewedOn: DateOnlySchema,
}).strict();
export type PrimarySource = z.infer<typeof PrimarySourceSchema>;

export const RulePackMetadataSchema = z.object({
  stableId: z.string().regex(/^[a-z0-9]+(?:[._-][a-z0-9]+)+$/),
  version: z.string().regex(/^\d+\.\d+\.\d+$/),
  status: RulePackStatusSchema,
  jurisdictions: z.array(z.string().min(2)).min(1),
  entityTypes: z.array(EntityTypeSchema).min(1),
  service: ServiceTypeSchema,
  effectiveFrom: DateOnlySchema,
  effectiveTo: DateOnlySchema.optional(),
  reviewedAt: DateOnlySchema,
  expiresAt: DateOnlySchema,
  sources: z.array(PrimarySourceSchema).min(1),
  fixtureIds: z.array(z.string().min(1)).min(1),
  authorId: UserIdSchema,
  independentReviewerId: UserIdSchema.optional(),
  qualifiedApproverId: UserIdSchema.optional(),
}).strict().superRefine((pack, context) => {
  if (pack.effectiveTo && pack.effectiveFrom > pack.effectiveTo) {
    context.addIssue({
      code: "custom",
      path: ["effectiveTo"],
      message: "effectiveTo must not precede effectiveFrom",
    });
  }
  if (pack.status === "published") {
    if (!pack.independentReviewerId || !pack.qualifiedApproverId) {
      context.addIssue({
        code: "custom",
        path: ["status"],
        message: "Published packs require independent review and qualified approval",
      });
    }
    const participants = new Set([
      pack.authorId,
      pack.independentReviewerId,
      pack.qualifiedApproverId,
    ].filter((value) => value !== undefined));
    if (participants.size !== 3) {
      context.addIssue({
        code: "custom",
        path: ["independentReviewerId"],
        message: "Author, reviewer, and qualified approver must be different users",
      });
    }
  }
});

export type RulePackMetadata = z.infer<typeof RulePackMetadataSchema>;

export interface RuleApplicabilityContext {
  readonly jurisdiction: string;
  readonly entityType: EntityType;
  readonly service: ServiceType;
  readonly asOf: DateOnly;
}

export function evaluateRulePackApplicability(
  pack: RulePackMetadata,
  context: RuleApplicabilityContext,
): Result<RulePackMetadata, DomainError> {
  const reasons: string[] = [];
  if (pack.status !== "published") reasons.push("not_published");
  if (!pack.jurisdictions.includes(context.jurisdiction)) reasons.push("jurisdiction");
  if (!pack.entityTypes.includes(context.entityType)) reasons.push("entity_type");
  if (pack.service !== context.service) reasons.push("service");
  if (context.asOf < pack.effectiveFrom) reasons.push("not_effective");
  if (pack.effectiveTo && context.asOf > pack.effectiveTo) reasons.push("past_effective_period");
  if (context.asOf > pack.expiresAt) reasons.push("expired");

  if (reasons.length > 0) {
    return err(new DomainError(
      "BLOCKED_UNSUPPORTED",
      "No applicable approved rule-pack version is available.",
      {
        stableId: pack.stableId,
        version: pack.version,
        reasons,
      },
    ));
  }

  return ok(pack);
}
```

Add all rule exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- rules.test.ts
npm run verify
```

Expected: six generated test cases pass; unsupported or stale contexts return `BLOCKED_UNSUPPORTED` rather than a guessed result.

- [ ] **Step 5: Commit the rule-pack gate**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/rules.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/rules.test.ts
git commit -m "feat: add versioned rule-pack applicability gate"
```

### Task 7: Add auditable domain events and outbox records

**Files:**
- Create: `canadian-practice-platform/packages/domain/src/events.ts`
- Create: `canadian-practice-platform/packages/domain/test/events.test.ts`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts`

**Interfaces:**
- Consumes: `createEventId`, `TenantScopeSchema`, `UserIdSchema`, and `parseWithSchema`.
- Produces: schema-versioned `CreateDomainEventInput`, `DomainEventEnvelope`, `createDomainEvent`, and `newPendingOutboxRecord`. Persistence and publishing are owned by Plan 0B.

- [ ] **Step 1: Write failing deterministic event tests**

Create `canadian-practice-platform/packages/domain/test/events.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  createDomainEvent,
  createFirmId,
  createTenantId,
  createUserId,
  newPendingOutboxRecord,
} from "../src/index.js";

const EVENT_UUID = "00000000-0000-4000-8000-000000000021";

describe("domain event envelope", () => {
  it("creates a deterministic tenant-scoped audit event", () => {
    const event = createDomainEvent({
      eventType: "engagement.created",
      scope: {
        tenantId: createTenantId("00000000-0000-4000-8000-000000000022"),
        firmId: createFirmId("00000000-0000-4000-8000-000000000023"),
      },
      actor: {
        type: "user",
        userId: createUserId("00000000-0000-4000-8000-000000000024"),
      },
      correlationId: "corr-123",
      reason: "Create a controlled test engagement",
      policyDecision: "allowed",
      payload: { engagementKind: "bookkeeping" },
    }, {
      uuid: () => EVENT_UUID,
      now: () => "2026-08-13T16:30:00.000Z",
    });

    expect(event).toMatchObject({
      eventId: `evt_${EVENT_UUID}`,
      schemaVersion: 1,
      occurredAt: "2026-08-13T16:30:00.000Z",
      eventType: "engagement.created",
      correlationId: "corr-123",
    });
  });

  it("creates an idempotent pending outbox record from the event", () => {
    const event = createDomainEvent({
      eventType: "ledger.imported",
      scope: { tenantId: createTenantId("00000000-0000-4000-8000-000000000025") },
      actor: { type: "system", systemId: "ledger-importer" },
      correlationId: "corr-456",
      reason: "Record import completion",
      policyDecision: "not_applicable",
      payload: { manifestId: "manifest-1" },
    }, { uuid: () => EVENT_UUID, now: () => "2026-08-13T16:31:00.000Z" });

    expect(newPendingOutboxRecord(event)).toEqual({
      event,
      status: "pending",
      attempts: 0,
      lastErrorCode: null,
      publishedAt: null,
    });
  });
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
npm test --workspace @canada-practice/domain -- events.test.ts
```

Expected: FAIL because event exports do not exist.

- [ ] **Step 3: Implement the event and outbox schemas**

Create `canadian-practice-platform/packages/domain/src/events.ts`:

```ts
import { randomUUID } from "node:crypto";
import { z } from "zod";
import { parseWithSchema } from "./errors.js";
import {
  EventIdSchema,
  TenantScopeSchema,
  UserIdSchema,
  createEventId,
} from "./identity.js";

export const ActorSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("user"), userId: UserIdSchema }).strict(),
  z.object({ type: z.literal("client"), userId: UserIdSchema }).strict(),
  z.object({ type: z.literal("support"), userId: UserIdSchema }).strict(),
  z.object({ type: z.literal("system"), systemId: z.string().min(1) }).strict(),
]);
export type Actor = z.infer<typeof ActorSchema>;

export const DomainEventEnvelopeSchema = z.object({
  eventId: EventIdSchema,
  schemaVersion: z.literal(1),
  eventType: z.string().regex(/^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$/),
  occurredAt: z.string().datetime({ offset: true }),
  scope: TenantScopeSchema,
  actor: ActorSchema,
  correlationId: z.string().min(1),
  reason: z.string().min(1),
  policyDecision: z.enum(["allowed", "denied", "not_applicable"]),
  credentialId: z.string().min(1).optional(),
  payload: z.record(z.string(), z.unknown()),
}).strict();
export type DomainEventEnvelope = z.infer<typeof DomainEventEnvelopeSchema>;

export interface EventDependencies {
  readonly uuid: () => string;
  readonly now: () => string;
}

const DEFAULT_EVENT_DEPENDENCIES: EventDependencies = {
  uuid: randomUUID,
  now: () => new Date().toISOString(),
};

export type CreateDomainEventInput = Omit<
  DomainEventEnvelope,
  "eventId" | "schemaVersion" | "occurredAt"
>;

export function createDomainEvent(
  input: CreateDomainEventInput,
  dependencies: EventDependencies = DEFAULT_EVENT_DEPENDENCIES,
): DomainEventEnvelope {
  return parseWithSchema(DomainEventEnvelopeSchema, {
    ...input,
    eventId: createEventId(dependencies.uuid()),
    schemaVersion: 1,
    occurredAt: dependencies.now(),
  }, "domain event");
}

export const OutboxRecordSchema = z.object({
  event: DomainEventEnvelopeSchema,
  status: z.enum(["pending", "published", "failed"]),
  attempts: z.number().int().nonnegative(),
  lastErrorCode: z.string().nullable(),
  publishedAt: z.string().datetime({ offset: true }).nullable(),
}).strict();
export type OutboxRecord = z.infer<typeof OutboxRecordSchema>;

export const newPendingOutboxRecord = (
  event: DomainEventEnvelope,
): OutboxRecord => ({
  event,
  status: "pending",
  attempts: 0,
  lastErrorCode: null,
  publishedAt: null,
});
```

Add all event exports from the Public API Contract to `src/index.ts`.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
npm test --workspace @canada-practice/domain -- events.test.ts
npm run verify
```

Expected: both event tests pass; the event ID and timestamp are deterministic under injected dependencies.

- [ ] **Step 5: Commit the event contracts**

Run from the repository root:

```bash
git add canadian-practice-platform/packages/domain/src/events.ts canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/events.test.ts
git commit -m "feat: add audit event and outbox contracts"
```

### Task 8: Lock the public API, documentation, and continuous verification

**Files:**
- Create: `canadian-practice-platform/packages/domain/test/public-api.test.ts`
- Create: `canadian-practice-platform/README.md`
- Create: `.github/workflows/canadian-practice-platform-domain.yml`
- Modify: `canadian-practice-platform/packages/domain/src/index.ts` only if an earlier export is missing

**Interfaces:**
- Consumes: Every public export produced by Tasks 1–7.
- Produces: a tested package surface, explicit non-goals, repeatable local commands, and Node 24 CI verification. No new domain capability is added.

- [ ] **Step 1: Write a failing public-surface test**

Create `canadian-practice-platform/packages/domain/test/public-api.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import * as domain from "../src/index.js";

const REQUIRED_EXPORTS = [
  "DOMAIN_PACKAGE_NAME",
  "DOMAIN_SCHEMA_VERSION",
  "DomainError",
  "DomainErrorCodeSchema",
  "TenantIdSchema",
  "TenantScopeSchema",
  "Money",
  "CurrencyCodeSchema",
  "DateOnlySchema",
  "ReportingPeriodSchema",
  "EngagementLocaleSchema",
  "DEFAULT_LOCALE",
  "RulePackMetadataSchema",
  "evaluateRulePackApplicability",
  "DomainEventEnvelopeSchema",
  "OutboxRecordSchema",
  "createDomainEvent",
  "newPendingOutboxRecord",
] as const;

const FORBIDDEN_EXPORT_PATTERNS = [
  /calculate.*tax/i,
  /calculate.*payroll/i,
  /file.*return/i,
  /submit.*cra/i,
  /issue.*opinion/i,
  /represent.*taxpayer/i,
];

describe("public domain API", () => {
  it("exports every approved Wave 0A contract", () => {
    expect(Object.keys(domain)).toEqual(expect.arrayContaining(REQUIRED_EXPORTS));
  });

  it("does not expose production tax, filing, representation, or opinion actions", () => {
    for (const exportedName of Object.keys(domain)) {
      for (const pattern of FORBIDDEN_EXPORT_PATTERNS) {
        expect(exportedName).not.toMatch(pattern);
      }
    }
  });
});
```

- [ ] **Step 2: Run the focused test and repair only missing approved exports**

Run:

```bash
npm test --workspace @canada-practice/domain -- public-api.test.ts
```

Expected before repair: FAIL if any Public API Contract export was omitted. Add only the missing export statements to `src/index.ts`. Re-run and expect PASS.

- [ ] **Step 3: Write the Wave 0A README with exact boundaries**

Create `canadian-practice-platform/README.md` with these sections and content:

```markdown
# Canadian Practice Platform

This directory contains the service-backed Canadian bookkeeping and regulated-workflow platform. It is separate from the existing Ontario tenant-assessment skill.

## Current delivery: Wave 0A

Wave 0A publishes `@canada-practice/domain`, a pure TypeScript domain kernel for identifiers, tenant scope, safe errors, fixed-decimal money, reporting periods, English/French locale selection, versioned rule-pack applicability, and audit/outbox event contracts.

It contains no customer data, database, API, UI, model integration, tax formula, filing action, representation action, or assurance opinion.

## Commands

Run from this directory:

- `npm ci` — install the committed dependency graph.
- `npm run typecheck` — verify strict TypeScript contracts.
- `npm test` — run domain invariant tests.
- `npm run build` — compile ESM and declarations to package `dist/` directories.
- `npm run verify` — run typecheck, tests, and build in sequence.
- `npm audit --audit-level=high` — fail on high or critical dependency advisories.

## Package boundary

Consumers import only from `@canada-practice/domain`. Imports from `@canada-practice/domain/src/*` are unsupported.

## Safety boundary

Wave 0A is infrastructure, not tax, legal, accounting, payroll, filing, representation, or assurance advice or software. Production capabilities require separately approved entity, jurisdiction, service, professional-validation, privacy, security, and release plans.
```

- [ ] **Step 4: Add Node 24 continuous verification**

Create `.github/workflows/canadian-practice-platform-domain.yml`:

```yaml
name: Canadian practice platform domain

on:
  pull_request:
    paths:
      - "canadian-practice-platform/**"
      - ".github/workflows/canadian-practice-platform-domain.yml"
  push:
    branches: [main]
    paths:
      - "canadian-practice-platform/**"
      - ".github/workflows/canadian-practice-platform-domain.yml"

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    defaults:
      run:
        working-directory: canadian-practice-platform
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-node@v6
        with:
          node-version: "24"
          cache: npm
          cache-dependency-path: canadian-practice-platform/package-lock.json
          package-manager-cache: true
      - run: npm ci
      - run: npm run verify
      - run: npm audit --audit-level=high
```

- [ ] **Step 5: Run the full local release gate**

Run from `canadian-practice-platform/`:

```bash
npm ci
npm run verify
npm audit --audit-level=high
npm pack --workspace @canada-practice/domain --dry-run
```

Expected:

- all tests pass;
- strict typecheck and build pass;
- audit has no high or critical advisories;
- the dry-run package contains only `package.json` and `dist/**` artifacts;
- no source test, `.superpowers`, Python-skill, or customer-like file appears in the package.

- [ ] **Step 6: Run repository regression and whitespace checks**

Run from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s assess-ontario-tenant-application/tests -p 'test_*.py'
git diff --check
git status --short
```

Expected: the existing Python suite passes; `git diff --check` prints nothing; status lists only the intended README, workflow, public API test, and any missing export repair.

- [ ] **Step 7: Commit the release gate**

Run from the repository root:

```bash
git add canadian-practice-platform/README.md canadian-practice-platform/packages/domain/src/index.ts canadian-practice-platform/packages/domain/test/public-api.test.ts .github/workflows/canadian-practice-platform-domain.yml
git commit -m "ci: verify Canadian practice domain kernel"
```

## Wave 0A Completion Gate

Before marking this plan complete, run from `canadian-practice-platform/`:

```bash
npm ci
npm run verify
npm audit --audit-level=high
npm pack --workspace @canada-practice/domain --dry-run
```

Then run from the repository root:

```bash
.venv/bin/python -m unittest discover -s assess-ontario-tenant-application/tests -p 'test_*.py'
git diff --check
git status --short --branch
git log --oneline -8
```

The completion evidence must show:

- eight Wave 0A test files passing;
- TypeScript typecheck and build passing;
- no high or critical npm advisory;
- a package dry run containing no unintended files;
- the existing Ontario tenant skill tests still passing;
- one focused commit per task; and
- no production tax, filing, representation, or assurance capability.

## Spec Coverage and Explicit Plan Boundaries

This plan implements the Wave 0 specification's foundational type and invariant contracts:

- strict tenant-scoped identifiers and scope hierarchy;
- safe explicit failures including `BLOCKED_UNSUPPORTED`;
- fixed-decimal, currency-safe authoritative amounts;
- period and bilingual locale primitives;
- versioned, sourced, independently reviewed rule-pack metadata;
- deterministic applicability refusal for stale or unsupported packs; and
- schema-versioned audit/outbox event envelopes.

The remaining approved requirements are assigned to named delivery plans rather than hidden inside 0A:

- **0B:** stored firms/users/clients/entities/engagements, credentials, authorization decisions, professional gates, support access, tamper-evident audit persistence, and transactional outbox delivery.
- **0C:** external/native ledger records, balanced journal state, immutable posting/reversal, idempotent import, mapping, reconciliation, cursor recovery, and posting-back results.
- **0D:** Canadian document storage, evidence graph, review notes, workpaper state machine, locked/released/superseded snapshots, lineage completeness, and successor differences.
- **0E:** practice/client/plugin channel shells, English/French rendering parity, all-channel policy enforcement, Canada-only data-route proof, retention/legal hold/export/deletion, backup restore, security exercises, and controlled-pilot release package.

Production tax/entity/jurisdiction packs begin only after Wave 0E passes and each pack receives its own design, implementation plan, primary-source registry, professional validation fixtures, and release approval.
