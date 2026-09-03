import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// React Testing Library's auto-cleanup only registers itself when it finds
// framework-global `afterEach`/`beforeEach` hooks (Jest-style globals).
// This project runs Vitest with `globals: false` (see vite.config.ts), so
// register cleanup explicitly - otherwise each test's rendered tree stays
// mounted into the next test within the same file.
afterEach(() => {
  cleanup();
});
