"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { Moon, Sun } from "lucide-react";

const links = [
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();

  return (
    <nav className="border-b border-border bg-teal-800 dark:bg-teal-950">
      <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/chat" className="text-lg font-bold text-white">
            OpenPA
          </Link>
          {user &&
            links.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`text-sm transition-colors ${
                  pathname === link.href
                    ? "text-white font-medium"
                    : "text-teal-200 hover:text-white"
                }`}
              >
                {link.label}
              </Link>
            ))}
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={toggle}
            className="p-1.5 rounded-md text-teal-200 hover:text-white hover:bg-teal-700 transition-colors cursor-pointer"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          {user && (
            <>
              <span className="text-sm text-teal-200">{user.email}</span>
              <button
                onClick={logout}
                className="text-sm text-teal-200 hover:text-white transition-colors cursor-pointer"
              >
                Logout
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
