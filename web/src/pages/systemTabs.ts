/** Tabs in display order: URL segment, label and the setting groups each one shows. */
export const TABS = [
  { path: "status", label: "Status", groups: ["Server"] },
  { path: "email", label: "Email & notifications", groups: ["Email", "Inbound email", "Notifications"] },
  { path: "form", label: "Public form", groups: ["Public feedback form"] },
  { path: "storage", label: "Image storage", groups: ["Image storage"] },
  { path: "accounts", label: "Accounts & limits", groups: ["Sign-in and accounts", "Replies and data"] },
] as const;

export const tabFor = (group: string) => TABS.find((t) => (t.groups as readonly string[]).includes(group));
