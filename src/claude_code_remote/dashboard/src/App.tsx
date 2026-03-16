import { Routes, Route, NavLink } from "react-router";
import { ConfigProvider } from "./config";

import SessionList from "./pages/SessionList";
import SessionDetail from "./pages/SessionDetail";
import CronList from "./pages/CronList";
import CronDetail from "./pages/CronDetail";

function Nav() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 text-sm font-medium rounded-md transition-colors ${
      isActive
        ? "bg-zinc-800 text-white"
        : "text-zinc-400 hover:text-white hover:bg-zinc-800/50"
    }`;

  return (
    <header className="border-b border-zinc-800 bg-zinc-950">
      <div className="mx-auto max-w-7xl px-4 py-3 flex items-center gap-6">
        <h1 className="text-lg font-semibold text-white tracking-tight">
          CCR Dashboard
        </h1>
        <nav className="flex gap-1">
          <NavLink to="/" end className={linkClass}>
            Sessions
          </NavLink>
          <NavLink to="/cron" className={linkClass}>
            Cron Jobs
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <ConfigProvider>
      <div className="min-h-screen bg-zinc-950 text-zinc-100">
        <Nav />
        <main className="mx-auto max-w-7xl px-4 py-6">
          <Routes>
            <Route index element={<SessionList />} />
            <Route path="sessions/:id" element={<SessionDetail />} />
            <Route path="cron" element={<CronList />} />
            <Route path="cron/:id" element={<CronDetail />} />
          </Routes>
        </main>
      </div>
    </ConfigProvider>
  );
}
