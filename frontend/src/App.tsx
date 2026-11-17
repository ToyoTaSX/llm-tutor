import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Documents from "./pages/Documents";
import Stats from "./pages/Stats";

export default function App() {
  const { me, loading } = useAuth();
  if (loading) return <div className="grid h-full place-items-center text-muted">Загрузка…</div>;
  if (!me) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }
  const lecturer = me.role === "lecturer";
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Chat />} />
        <Route path="/qa/:id" element={<Chat />} />
        <Route path="/documents" element={lecturer ? <Documents /> : <Navigate to="/" replace />} />
        <Route path="/stats" element={lecturer ? <Stats /> : <Navigate to="/" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
