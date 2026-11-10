const SECTIONS: [id: string, label: string][] = [
  ["widget", "Widget"], ["api-key", "API key"], ["bot-protection", "Bot protection"], ["general", "General"],
  ["custom-fields", "Custom fields"], ["retention", "Retention"], ["personal-data", "Personal data"],
];

/** Links to the sections of the site settings page. Not tabs: the page stays one scroll, and focus moves to the heading. */
export default function JumpLinks() {
  function jump(e: React.MouseEvent, id: string) {
    e.preventDefault();
    const heading = document.getElementById(id)?.querySelector<HTMLElement>("h2");
    if (!heading) return;
    heading.tabIndex = -1;
    heading.scrollIntoView({ block: "start" });
    heading.focus({ preventScroll: true });
  }
  return (
    <nav className="jump" aria-label="On this page">
      <span className="jump-label">On this page</span>
      {SECTIONS.map(([id, label]) => <a key={id} href={`#${id}`} onClick={(e) => jump(e, id)}>{label}</a>)}
    </nav>
  );
}
