import { Navigate, Route, Routes } from "react-router-dom";
import { OfflineBanner } from "./components";
import Audit from "./pages/Audit";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import { ForgotPassword, ResetPassword } from "./pages/ResetPassword";
import SiteDetail from "./pages/SiteDetail";
import Dashboard from "./pages/Dashboard";
import Sites from "./pages/Sites";
import SystemSettings from "./pages/SystemSettings";
import Users from "./pages/Users";
import { Layout } from "./shell";

export default function App() {
  return (
    <>
      <OfflineBanner />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="sites" element={<Sites />} />
          <Route path="sites/:siteId/*" element={<SiteDetail />} />
          <Route path="users" element={<Users />} />
          <Route path="audit" element={<Audit />} />
          <Route path="system/:tab?" element={<SystemSettings />} />
          <Route path="profile" element={<Profile />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
