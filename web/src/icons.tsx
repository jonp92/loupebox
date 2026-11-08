import type { ReactNode } from "react";

// 24px line icons. They inherit the text color, so they follow the theme and the active-nav color.
const PATHS: Record<string, ReactNode> = {
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  dashboard: <><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" /></>,
  sites: <><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2.5 2.3 3.5 5 3.5 8s-1 5.7-3.5 8c-2.5-2.3-3.5-5-3.5-8s1-5.7 3.5-8z" /></>,
  users: <><circle cx="9" cy="8.5" r="3" /><path d="M3.5 19c.5-3.2 2.7-4.7 5.5-4.7s5 1.5 5.5 4.7M15.5 5.6a3 3 0 010 5.8M17.5 14.6c1.7.6 2.7 2 3 4.4" /></>,
  audit: <><path d="M7 3.5h7l4 4V19a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 016 19V5a1.5 1.5 0 011-1.5z" /><path d="M14 3.5V8h4M9 12.5h6M9 16h6" /></>,
  system: <><path d="M4 8h8M18 8h2M4 16h2M12 16h8" /><circle cx="15" cy="8" r="2.2" /><circle cx="9" cy="16" r="2.2" /></>,
  user: <><circle cx="12" cy="8.5" r="3.5" /><path d="M5 20c.6-3.8 3.6-6 7-6s6.4 2.2 7 6" /></>,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" />,
  contrast: <><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 010 16z" fill="currentColor" /></>,
  caret: <path d="M6 9l6 6 6-6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  more: <><circle cx="5.5" cy="12" r="1.2" fill="currentColor" /><circle cx="12" cy="12" r="1.2" fill="currentColor" /><circle cx="18.5" cy="12" r="1.2" fill="currentColor" /></>,
  reply: <path d="M9 7L4 12l5 5M4 12h10a6 6 0 016 6" />,
  clip: <path d="M20 11.5l-7.6 7.6a4.5 4.5 0 01-6.4-6.4l8-8a3 3 0 014.3 4.2l-8 8a1.5 1.5 0 01-2.2-2.1l7.2-7.2" />,
  note: <path d="M5 5h14v10H10l-5 4z" />,
  person: <><circle cx="12" cy="8.5" r="3.2" /><path d="M5.5 19.5c.6-3.4 3.2-5.2 6.5-5.2s5.9 1.8 6.5 5.2" /></>,
  refresh: <path d="M20 5v5h-5M4 19v-5h5M18.2 9A7 7 0 006.3 7.3L4 10M5.8 15A7 7 0 0017.7 16.7L20 14" />,
  chevron: <path d="M9 6l6 6-6 6" />,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg className="icon-svg" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false">
      {PATHS[name]}
    </svg>
  );
}
