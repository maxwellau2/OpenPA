"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { getMe } from "./api";

interface User {
  id: number;
  email: string;
  display_name: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  setAuth: (token: string, user: User) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  loading: true,
  setAuth: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const initialToken = typeof window !== "undefined" ? localStorage.getItem("openpa_token") : null;
  const [token, setToken] = useState<string | null>(initialToken);
  const [loading, setLoading] = useState(!!initialToken);

  useEffect(() => {
    if (!token) return;
    getMe()
      .then((data) => setUser(data.user))
      .catch(() => {
        localStorage.removeItem("openpa_token");
        setToken(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  function setAuth(newToken: string, newUser: User) {
    localStorage.setItem("openpa_token", newToken);
    setToken(newToken);
    setUser(newUser);
  }

  function logout() {
    localStorage.removeItem("openpa_token");
    setToken(null);
    setUser(null);
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, setAuth, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
