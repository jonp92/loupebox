import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useParams } from "react-router-dom";
import { api, type Site } from "../api";
import { soleSiteId, useAuth } from "../auth";
import { ScrollTabs } from "../components";
import Activity from "./Activity";
import FeedbackDetail from "./FeedbackDetail";
import FeedbackList from "./FeedbackList";
import Members from "./Members";
import Notifications from "./Notifications";
import Settings from "./Settings";

export default function SiteDetail() {
  const { siteId } = useParams();
  const { me } = useAuth();
  const [site, setSite] = useState<Site | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Site>(`/sites/${siteId}`).then(setSite).catch((e) => setError(e.message));
  }, [siteId]);

  if (error) return <p className="error">{error}</p>;
  if (!site) return <p className="muted">Loading…</p>;
  const isAdmin = site.my_role === "admin";
  // Absolute links: inside the sites/:siteId/* route, relative ones resolve against the full URL.
  const base = `/sites/${site.id}`;

  return (
    <>
      {!soleSiteId(me) && <Link to="/sites" className="back">← All sites</Link>}
      <div className="page-head">
        <h1>{site.name}</h1>
        <span className="badge">{site.my_role}</span>
        {!site.is_active && <span className="badge warn">disabled</span>}
      </div>
      <ScrollTabs>
        <NavLink to={base} end>Feedback</NavLink>
        <NavLink to={`${base}/activity`}>Activity</NavLink>
        {isAdmin && <NavLink to={`${base}/settings`}>Settings</NavLink>}
        {isAdmin && <NavLink to={`${base}/members`}>Members</NavLink>}
        {isAdmin && <NavLink to={`${base}/notifications`}>Notifications</NavLink>}
      </ScrollTabs>
      <Routes>
        <Route index element={<FeedbackList site={site} />} />
        <Route path="feedback/:feedbackId" element={<FeedbackDetail site={site} />} />
        <Route path="activity" element={<Activity site={site} />} />
        {isAdmin && <Route path="settings" element={<Settings site={site} onChange={setSite} />} />}
        {isAdmin && <Route path="members" element={<Members site={site} />} />}
        {isAdmin && <Route path="notifications" element={<Notifications site={site} />} />}
        <Route path="*" element={<Navigate to={base} replace />} />
      </Routes>
    </>
  );
}
