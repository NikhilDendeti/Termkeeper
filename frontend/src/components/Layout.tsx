import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import Icon from "./Icon";

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? "app-nav-link is-active" : "app-nav-link";
}

function uploadNavLinkClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? "btn btn-primary btn--sm app-nav-cta is-active" : "btn btn-primary btn--sm app-nav-cta";
}

const ROUTE_TITLES: Record<string, string> = {
  "/": "Contracts",
  "/guardrail": "Guardrail verification",
  "/evaluation": "Evaluation results",
  "/about": "About",
  "/upload": "Upload a contract",
};

function pageTitleForPath(pathname: string): string {
  if (ROUTE_TITLES[pathname]) return ROUTE_TITLES[pathname];
  if (pathname.startsWith("/contracts/")) return "Contract detail";
  return "ContractGuard";
}

/**
 * App chrome: header with the main navigation (spec: Guardrail status
 * "reachable from the main navigation"), plus the routed page content.
 *
 * Also owns two pieces of cross-page a11y state a React SPA doesn't get for
 * free: the document title (never updated per route otherwise, so the
 * browser tab and screen-reader page announcement stayed frozen on
 * "ContractGuard" for all six routes) and focus on route change (moved to
 * <main> so keyboard/screen-reader users get the same "landed somewhere new"
 * signal a full page navigation would give them).
 */
export default function Layout() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    document.title = `${pageTitleForPath(location.pathname)} · ContractGuard`;
    // Reset scroll explicitly rather than letting focus() do it - the
    // default scroll-into-view on focus() aligns <main>'s top edge with the
    // viewport top, which would tuck it behind the sticky header instead.
    window.scrollTo(0, 0);
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <NavLink to="/" end className="app-brand">
            <Icon name="shield-check" size={20} className="app-brand-icon" />
            Contract<span className="app-brand-mark">Guard</span>
          </NavLink>
          <nav className="app-nav" aria-label="Main">
            <NavLink to="/" end className={navLinkClassName}>
              Contracts
            </NavLink>
            <NavLink to="/guardrail" className={navLinkClassName}>
              Guardrail Status
            </NavLink>
            <NavLink to="/evaluation" className={navLinkClassName}>
              Evaluation
            </NavLink>
            <NavLink to="/about" className={navLinkClassName}>
              About
            </NavLink>
            <NavLink to="/upload" className={uploadNavLinkClassName}>
              Upload
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="app-main" ref={mainRef} tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}
