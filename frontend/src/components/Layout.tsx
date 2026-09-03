import { NavLink, Outlet } from "react-router-dom";

import Icon from "./Icon";

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? "app-nav-link is-active" : "app-nav-link";
}

/**
 * App chrome: header with the main navigation (spec: Guardrail status
 * "reachable from the main navigation"), plus the routed page content.
 */
export default function Layout() {
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
          </nav>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
