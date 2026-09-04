import type { SVGProps } from "react";

/**
 * Single source for every icon glyph used in the app - one stroke weight
 * (1.75), one viewBox (24x24), one line style (round caps/joins), sized via
 * the `size` prop. Keeping every icon behind this component is what keeps
 * icon weight/size/alignment consistent app-wide instead of drifting
 * per-usage. Icons are decorative only (aria-hidden) - every state they
 * accompany already carries its meaning in text.
 */
export type IconName =
  | "chevron-right"
  | "arrow-left"
  | "alert-triangle"
  | "check-circle"
  | "x-circle"
  | "inbox"
  | "shield-check"
  | "help-circle"
  | "file-text"
  | "clock"
  | "info"
  | "arrow-right"
  | "layers"
  | "git-branch";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  size?: number;
}

export default function Icon({ name, size = 16, className, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className ? `icon ${className}` : "icon"}
      {...rest}
    >
      {ICON_GLYPHS[name]}
    </svg>
  );
}

const ICON_GLYPHS: Record<IconName, React.ReactNode> = {
  "chevron-right": <polyline points="9 6 15 12 9 18" />,
  "arrow-left": (
    <>
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </>
  ),
  "alert-triangle": (
    <>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>
  ),
  "check-circle": (
    <>
      <circle cx="12" cy="12" r="9" />
      <polyline points="8 12 11 15 16 9" />
    </>
  ),
  "x-circle": (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </>
  ),
  inbox: (
    <>
      <polyline points="3 8 8 8 10 11 14 11 16 8 21 8" />
      <path d="M3 8 4.6 3.2A2 2 0 0 1 6.5 2h11a2 2 0 0 1 1.9 1.2L21 8v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    </>
  ),
  "shield-check": (
    <>
      <path d="M12 21s7-3.5 7-9V5l-7-3-7 3v7c0 5.5 7 9 7 9Z" />
      <polyline points="9 11.5 11.5 14 15.5 9" />
    </>
  ),
  "help-circle": (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9.5 9a2.5 2.5 0 0 1 4.7 1.2c0 1.8-2.5 2-2.5 3.6" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>
  ),
  "file-text": (
    <>
      <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z" />
      <polyline points="13 2 13 9 20 9" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="16" y2="17" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <polyline points="12 7 12 12 15.5 14" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <line x1="12" y1="16" x2="12" y2="11.5" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </>
  ),
  "arrow-right": (
    <>
      <line x1="5" y1="12" x2="19" y2="12" />
      <polyline points="12 5 19 12 12 19" />
    </>
  ),
  layers: (
    <>
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </>
  ),
  "git-branch": (
    <>
      <line x1="6" y1="3" x2="6" y2="15" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </>
  ),
};
