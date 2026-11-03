import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { api, type Site } from "../api";
import { ScrollTabs } from "../components";
import Activity from "./Activity";
import FeedbackList from "./FeedbackList";
import Members from "./Members";
import Notifications from "./Notifications";
import Settings from "./Settings";

export default function SiteDetail() {
  const { siteId } = useParams();
  const [site, setSite] = useState<Site | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Site>(`/sites/${siteId}`).then(setSite).catch((e) => setError(e.message));
  }, [siteId]);

  if (error) return <p className="error">{error}</p>;
  if (!site) return <p className="muted">Loading…</p>;
  const isAdmin = site.my_role === "admin";

  return (
    <>
      <Link to="/sites" className="back">← All sites</Link>
      <div className="page-head">
        <h1>{site.name}</h1>
        <span className="badge">{site.my_role}</span>
        {!site.is_active && <span className="badge warn">disabled</span>}
      </div>
      <ScrollTabs>
        <NavLink to="" end>Feedback</NavLink>
        <NavLink to="activity">Activity</NavLink>
        {isAdmin && <NavLink to="settings">Settings</NavLink>}
        {isAdmin && <NavLink to="members">Members</NavLink>}
        {isAdmin && <NavLink to="notifications">Notifications</NavLink>}
      </ScrollTabs>
      <Routes>
        <Route index element={<FeedbackList site={site} />} />
        <Route path="feedback/:feedbackId" element={<FeedbackList site={site} />} />
        <Route path="activity" element={<Activity site={site} />} />
        {isAdmin && <Route path="settings" element={<Settings site={site} onChange={setSite} />} />}
        {isAdmin && <Route path="members" element={<Members site={site} />} />}
        {isAdmin && <Route path="notifications" element={<Notifications site={site} />} />}
        <Route path="*" element={<Navigate to="" replace />} />
      </Routes>
    </>
  );
}
