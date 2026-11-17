import { createContext, ReactNode, useContext, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, Me, post } from "./api";

interface AuthCtx {
  me: Me | null;
  loading: boolean;
  setMe(me: Me | null): void;
  logout(): Promise<void>;
}

const Ctx = createContext<AuthCtx>(null!);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/api/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: Infinity,
    retry: false,
  });

  const setMe = (me: Me | null) => {
    // сначала обновляем ["me"]: подписка useQuery должна получить новое значение.
    // qc.clear() здесь нельзя — он удаляет и сам запрос ["me"], и UI не узнаёт о выходе
    qc.setQueryData(["me"], me);
    // данные прошлого пользователя (история, статистика) не должны достаться следующему
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  };

  useEffect(() => {
    // любой 401 от API: сессия истекла → на страницу входа
    const h = () => setMe(null);
    window.addEventListener("unauthorized", h);
    return () => window.removeEventListener("unauthorized", h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const logout = async () => {
    try {
      await post("/api/auth/logout");
    } finally {
      setMe(null);
    }
  };

  return <Ctx.Provider value={{ me: q.data ?? null, loading: q.isLoading, setMe, logout }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
