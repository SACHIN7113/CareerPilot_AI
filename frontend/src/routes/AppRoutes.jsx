import { Navigate, Route, Routes } from "react-router-dom";
import AnalysisAssessmentPage from "../pages/AnalysisAssessmentPage";
import AnalysisProcessPage from "../pages/AnalysisProcessPage";
import AnalysisPage from "../pages/AnalysisPage";
import AnalysisSkillQuizPage from "../pages/AnalysisSkillQuizPage";
import AnalysisSkillUpdatePage from "../pages/AnalysisSkillUpdatePage";
import AnalysisResumeUpgradePage from "../pages/AnalysisResumeUpgradePage";
import ChangePasswordPage from "../pages/ChangePasswordPage";
import DashboardPage from "../pages/DashboardPage";
import DocumentsPage from "../pages/DocumentsPage";
import LoginPage from "../pages/LoginPage";
import OnboardingPage from "../pages/OnboardingPage";
import SettingsPage from "../pages/SettingsPage";
import ScoresPage from "../pages/ScoresPage";
import { hasValidSession } from "../utils/auth";

function RequireAuth({ children }) {
  return hasValidSession() ? children : <Navigate to="/login" replace />;
}

function GuestOnly({ children }) {
  return hasValidSession() ? <Navigate to="/analysis" replace /> : children;
}

export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<OnboardingPage />} />
      <Route
        path="/login"
        element={
          <GuestOnly>
            <LoginPage />
          </GuestOnly>
        }
      />
      <Route
        path="/aiPrepare"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route path="/dashboard" element={<Navigate to="/aiPrepare" replace />} />
      <Route path="/eiPrepare" element={<Navigate to="/aiPrepare" replace />} />
      <Route
        path="/documents"
        element={
          <RequireAuth>
            <DocumentsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/history"
        element={
          <RequireAuth>
            <ScoresPage />
          </RequireAuth>
        }
      />
      <Route path="/scores" element={<Navigate to="/history" replace />} />
      <Route
        path="/analysis"
        element={
          <RequireAuth>
            <AnalysisPage />
          </RequireAuth>
        }
      />
      <Route
        path="/analysis/process"
        element={
          <RequireAuth>
            <AnalysisProcessPage />
          </RequireAuth>
        }
      />
      <Route
        path="/analysis/skill-update"
        element={
          <RequireAuth>
            <AnalysisSkillUpdatePage />
          </RequireAuth>
        }
      />
      <Route
        path="/analysis/resume-upgrade"
        element={
          <RequireAuth>
            <AnalysisResumeUpgradePage />
          </RequireAuth>
        }
      />
      <Route
        path="/analysis/skill-quiz"
        element={
          <RequireAuth>
            <AnalysisSkillQuizPage />
          </RequireAuth>
        }
      />
      <Route
        path="/analysis/assessment"
        element={
          <RequireAuth>
            <AnalysisAssessmentPage />
          </RequireAuth>
        }
      />
      <Route
        path="/settings"
        element={
          <RequireAuth>
            <SettingsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/settings/password"
        element={
          <RequireAuth>
            <ChangePasswordPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

