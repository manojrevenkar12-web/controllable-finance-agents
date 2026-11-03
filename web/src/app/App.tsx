import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CloseScreen } from "../features/close/CloseScreen";
import { InboxScreen, splitProposals } from "../features/inbox/InboxScreen";
import { QualityScreen } from "../features/quality/QualityScreen";
import { SignIn } from "../features/session/SignIn";
import { api, setToken } from "../shared/api/client";
import type { Session } from "../shared/api/types";

const SCREENS = {
  inbox: { title: "To approve", view: InboxScreen },
  close: { title: "Close", view: CloseScreen },
  quality: { title: "Agent quality", view: QualityScreen },
} as const;
type Screen = keyof typeof SCREENS;

const KEY = "cfa.session";

function load(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

function fromHash(): Screen {
  const h = window.location.hash.replace("#/", "");
  return h in SCREENS ? (h as Screen) : "inbox";
}

function Counts() {
  const q = useQuery({ queryKey: ["proposals", "proposed"], queryFn: () => api.proposals("proposed") });
  if (!q.data) return null;
  const p = splitProposals(q.data);
  return <>{p.ready.length + p.review.length + p.checks.length}</>;
}

function CompanyName({ fallback }: { fallback: string }) {
  const q = useQuery({ queryKey: ["reference"], queryFn: api.reference });
  return <>{q.data?.company ?? fallback}</>;
}

export function App() {
  const [session, setSession] = useState<Session | null>(() => {
    const s = load();
    setToken(s?.token ?? null);
    return s;
  });
  const [screen, setScreen] = useState<Screen>(fromHash);
  const qc = useQueryClient();
  useEffect(() => {
    const on = () => setScreen(fromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    document.title = `${SCREENS[screen].title} · Finance agents`;
  }, [screen]);

  const signIn = (s: Session) => {
    setToken(s.token);
    try {
      sessionStorage.setItem(KEY, JSON.stringify(s));
    } catch {
      /* the session then lasts until reload */
    }
    setSession(s);
  };
  const signOut = () => {
    setToken(null);
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* nothing stored */
    }
    qc.clear();
    setSession(null);
  };

  if (!session) return <SignIn onSignedIn={signIn} />;
  const View = SCREENS[screen].view;
  return (
    <div className="shell">
      <header className="nav">
        <div className="nav__company">
          <CompanyName fallback={session.tenant} />
          <small>Finance agents</small>
        </div>
        <nav aria-label="Main">
          <ul>
            {(Object.keys(SCREENS) as Screen[]).map((s) => (
              <li key={s}>
                <a href={`#/${s}`} aria-current={s === screen ? "page" : undefined}>
                  <span>{SCREENS[s].title}</span>
                  {s === "inbox" && (
                    <span className="nav__count">
                      <Counts />
                    </span>
                  )}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        <div className="nav__me">
          {session.person.name}
          <br />
          {session.person.role}, {session.person.department}
          <br />
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>
      <main className="main" id="main">
        <View />
      </main>
    </div>
  );
}
