"use client";

import { useState, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { listConfig, getLLMProviders, getLLMConfig, saveLLMConfig, LLMProviderInfo } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Check, ExternalLink, Mail, GitPullRequest, Music, MessageCircle, Brain, Key, Send, Globe, Activity, CloudSun } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Service OAuth configs
const SERVICES = [
  {
    name: "google", label: "Google (Gmail + Calendar)",
    description: "Read/send emails and manage calendar events",
    icon: <Mail className="w-5 h-5" />, authPath: "/auth/google",
    setupUrl: "https://console.cloud.google.com/apis/credentials",
    setupText: "Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in server .env",
  },
  {
    name: "github", label: "GitHub",
    description: "Access repos, PRs, issues, and notifications",
    icon: <GitPullRequest className="w-5 h-5" />, authPath: "/auth/github",
    setupUrl: "https://github.com/settings/developers",
    setupText: "Requires GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET in server .env",
  },
  {
    name: "spotify", label: "Spotify",
    description: "Play music, search tracks, manage playlists",
    icon: <Music className="w-5 h-5" />, authPath: "/auth/spotify",
    setupUrl: "https://developer.spotify.com/dashboard",
    setupText: "Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in server .env",
  },
  {
    name: "discord", label: "Discord",
    description: "Send and read messages in Discord channels",
    icon: <MessageCircle className="w-5 h-5" />, authPath: "/auth/discord",
    setupUrl: "https://discord.com/developers/applications",
    setupText: "Requires DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, and DISCORD_BOT_TOKEN in server .env",
  },
  {
    name: "mastodon", label: "Mastodon",
    description: "Read timelines, analyze trends, post statuses, and search the fediverse",
    icon: <Globe className="w-5 h-5" />, authPath: "/auth/mastodon",
    setupUrl: "https://mastodon.social/settings/applications",
    setupText: "Requires MASTODON_CLIENT_ID, MASTODON_CLIENT_SECRET, and MASTODON_INSTANCE_URL in server .env",
  },
  {
    name: "weather", label: "Weather",
    description: "Get current weather and forecasts for any city",
    icon: <CloudSun className="w-5 h-5" />, authPath: "", // No OAuth for direct API key
    setupUrl: "https://openweathermap.org/api",
    setupText: "Requires an OpenWeatherMap API key in server .env (OPENWEATHERMAP_API_KEY)",
  },
];

export default function SettingsPage() {
  const searchParams = useSearchParams();
  const [connectedServices, setConnectedServices] = useState<string[]>([]);
  const [justConnected, setJustConnected] = useState<string | null>(null);
  const [healthCheckData, setHealthCheckData] = useState<{ uptime: string; version: string } | null>(null);
  const [healthCheckLoading, setHealthCheckLoading] = useState(false);

  // LLM state
  const [llmProviders, setLLMProviders] = useState<Record<string, LLMProviderInfo>>({});
  const [llmConfig, setLLMConfig] = useState<{ default_provider: string; default_model: string; configured_providers: string[] }>({
    default_provider: "ollama", default_model: "", configured_providers: [],
  });
  const [llmKeys, setLLMKeys] = useState<Record<string, string>>({});
  const [llmSaving, setLLMSaving] = useState(false);
  const [llmSaved, setLLMSaved] = useState(false);

  useEffect(() => {
    const connected = searchParams.get("connected");
    if (connected) {
      setJustConnected(connected);
      setTimeout(() => setJustConnected(null), 5000);
    }
    listConfig().then((data) => setConnectedServices(data.services.map((s) => s.service))).catch(() => {});
    getLLMProviders().then((data) => setLLMProviders(data.providers)).catch(() => {});
    getLLMConfig().then((data) => setLLMConfig(data)).catch(() => {});
  }, [searchParams]);

  function handleOAuth(authPath: string) {
    const token = localStorage.getItem("openpa_token");
    if (!token) return;
    window.location.href = `${API_BASE}${authPath}?token=${encodeURIComponent(token)}`;
  }

  async function handleSaveLLM() {
    setLLMSaving(true);
    try {
      const payload: Record<string, string> = {};
      if (llmConfig.default_provider) payload.default_provider = llmConfig.default_provider;
      if (llmConfig.default_model) payload.default_model = llmConfig.default_model;
      for (const [key, value] of Object.entries(llmKeys)) {
        if (value) payload[key] = value;
      }
      await saveLLMConfig(payload);
      setLLMSaved(true);
      setLLMKeys({});
      setTimeout(() => setLLMSaved(false), 2000);
      // Refresh config
      getLLMConfig().then((data) => setLLMConfig(data)).catch(() => {});
    } finally {
      setLLMSaving(false);
    }
  }

  async function handleHealthCheck() {
    setHealthCheckLoading(true);
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      setHealthCheckData(data);
    } catch (e) {
      console.error("Health check failed:", e);
      setHealthCheckData({ uptime: "Error", version: "Error" });
    } finally {
      setHealthCheckLoading(false);
    }
  }

  const selectedProvider = llmProviders[llmConfig.default_provider];

  return (
    <div className="flex-1 p-6 overflow-y-auto">
      <div className="max-w-3xl mx-auto space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Settings</h1>
          <p className="text-muted-foreground mt-1">
            Configure your LLM provider and connect services.
          </p>
        </div>

        {justConnected && (
          <div className="p-3 rounded-lg bg-primary/10 text-primary text-sm font-medium flex items-center gap-2">
            <Check className="w-4 h-4" />
            {SERVICES.find((s) => s.name === justConnected)?.label || justConnected} connected!
          </div>
        )}

        {/* LLM Provider Section */}
        <div>
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2 mb-3">
            <Brain className="w-5 h-5 text-primary" />
            LLM Provider
          </h2>

          <Card className="border-border">
            <CardContent className="pt-6 space-y-4">
              {/* Provider selector */}
              <div>
                <label className="text-sm font-medium text-foreground mb-2 block">Provider</label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.entries(llmProviders).map(([key, info]) => (
                    <button
                      key={key}
                      onClick={() => setLLMConfig((prev) => ({
                        ...prev,
                        default_provider: key,
                        default_model: info.models[0] || "",
                      }))}
                      className={`p-3 rounded-lg border text-left transition-colors cursor-pointer ${
                        llmConfig.default_provider === key
                          ? "border-primary bg-primary/5"
                          : "border-border hover:border-primary/50"
                      }`}
                    >
                      <div className="text-sm font-medium">{info.label}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{info.description}</div>
                      {llmConfig.configured_providers.includes(key) && (
                        <Badge variant="secondary" className="mt-1 text-[10px] gap-0.5">
                          <Check className="w-2.5 h-2.5" /> Key set
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model selector */}
              {selectedProvider && (
                <div>
                  <label className="text-sm font-medium text-foreground mb-2 block">Model</label>
                  <div className="flex flex-wrap gap-2">
                    {selectedProvider.models.map((m) => (
                      <button
                        key={m}
                        onClick={() => setLLMConfig((prev) => ({ ...prev, default_model: m }))}
                        className={`px-3 py-1.5 rounded-md border text-xs font-mono transition-colors cursor-pointer ${
                          llmConfig.default_model === m
                            ? "border-primary bg-primary/5 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/50"
                        }`}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* API key input (for cloud providers) */}
              {selectedProvider?.needs_api_key && (
                <div>
                  <label className="text-sm font-medium text-foreground mb-1 block">
                    API Key
                    {llmConfig.configured_providers.includes(llmConfig.default_provider) && (
                      <span className="text-primary ml-2 font-normal">(already set — enter new to update)</span>
                    )}
                  </label>
                  <div className="flex items-center gap-2">
                    <Key className="w-4 h-4 text-muted-foreground shrink-0" />
                    <Input
                      type="password"
                      placeholder={`Paste your ${selectedProvider.label} API key`}
                      value={llmKeys[`${llmConfig.default_provider}_api_key`] || ""}
                      onChange={(e) => setLLMKeys((prev) => ({
                        ...prev,
                        [`${llmConfig.default_provider}_api_key`]: e.target.value,
                      }))}
                    />
                  </div>
                  {selectedProvider.get_key_url && (
                    <a
                      href={selectedProvider.get_key_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 mt-1.5 text-xs text-primary hover:underline"
                    >
                      Get API key <ExternalLink className="w-2.5 h-2.5" />
                    </a>
                  )}
                </div>
              )}

              <Button onClick={handleSaveLLM} disabled={llmSaving} size="sm">
                {llmSaved ? "Saved!" : llmSaving ? "Saving..." : "Save LLM Settings"}
              </Button>
            </CardContent>
          </Card>
        </div>

                <Separator />

        {/* Health Check Section */}
        <div>
          <h2 className="text-lg font-semibold text-foreground flex items-center gap-2 mb-3">
            <Activity className="w-5 h-5 text-primary" />
            Server Health
          </h2>
          <Card className="border-border">
            <CardContent className="pt-6 space-y-4">
              <Button onClick={handleHealthCheck} disabled={healthCheckLoading} size="sm">
                {healthCheckLoading ? "Checking..." : "Run Health Check"}
              </Button>
              {healthCheckData && (
                <div className="text-sm text-muted-foreground">
                  <p>Uptime: {healthCheckData.uptime}</p>
                  <p>Version: {healthCheckData.version}</p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <Separator />

        {/* Services Section */}
        <div>
          <h2 className="text-lg font-semibold text-foreground mb-3">Connected Services</h2>
          <div className="grid gap-4">
            {SERVICES.map((service) => {
              const isConnected = connectedServices.includes(service.name);
              return (
                <Card key={service.name} className="border-border">
                  <CardHeader>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                          {service.icon}
                        </div>
                        <div>
                          <CardTitle className="text-base flex items-center gap-2">
                            {service.label}
                            {isConnected && (
                              <Badge variant="secondary" className="gap-1 text-xs">
                                <Check className="w-3 h-3" /> Connected
                              </Badge>
                            )}
                          </CardTitle>
                          <CardDescription className="text-xs">{service.description}</CardDescription>
                        </div>
                      </div>
                      <Button
                        onClick={() => service.authPath ? handleOAuth(service.authPath) : null}
                        variant={isConnected ? "outline" : "default"}
                        size="sm"
                        disabled={!service.authPath}
                      >
                        {isConnected ? "Reconnect" : "Connect"}
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <p className="text-xs text-muted-foreground flex items-center gap-1">
                      {service.setupText}
                      <a href={service.setupUrl} target="_blank" rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-primary hover:underline ml-1">
                        Setup <ExternalLink className="w-2.5 h-2.5" />
                      </a>
                    </p>
                  </CardContent>
                </Card>
              );
            })}

            {/* Telegram — 2-step auth */}
            <TelegramConfig isConnected={connectedServices.includes("telegram")} />
          </div>
        </div>
      </div>
    </div>
  );
}

function TelegramConfig({ isConnected }: { isConnected: boolean }) {
  const [step, setStep] = useState<"idle" | "code_sent" | "done">("idle");
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  async function handleSendCode() {
    setLoading(true);
    setError("");
    const token = localStorage.getItem("openpa_token") || "";
    try {
      const res = await fetch(`${API_BASE_URL}/auth/telegram/start`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ api_id: apiId, api_hash: apiHash, phone, token }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      setStep("code_sent");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  async function handleVerify() {
    setLoading(true);
    setError("");
    const token = localStorage.getItem("openpa_token") || "";
    try {
      const res = await fetch(`${API_BASE_URL}/auth/telegram/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ code, token }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      setStep("done");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="border-border">
      <CardHeader>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
            <Send className="w-5 h-5" />
          </div>
          <div>
            <CardTitle className="text-base flex items-center gap-2">
              Telegram
              {(isConnected || step === "done") && (
                <Badge variant="secondary" className="gap-1 text-xs">
                  <Check className="w-3 h-3" /> Connected
                </Badge>
              )}
            </CardTitle>
            <CardDescription className="text-xs">Send/read messages from your Telegram account</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        {step === "idle" && !isConnected && (
          <>
            <p className="text-xs text-muted-foreground">
              Get your API ID and Hash from{" "}
              <a href="https://my.telegram.org" target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                my.telegram.org <ExternalLink className="w-2.5 h-2.5 inline" />
              </a>
            </p>
            <Input placeholder="API ID" value={apiId} onChange={(e) => setApiId(e.target.value)} />
            <Input type="password" placeholder="API Hash" value={apiHash} onChange={(e) => setApiHash(e.target.value)} />
            <Input placeholder="Phone number (+65...)" value={phone} onChange={(e) => setPhone(e.target.value)} />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button onClick={handleSendCode} disabled={loading || !apiId || !apiHash || !phone} size="sm">
              {loading ? "Sending code..." : "Send Verification Code"}
            </Button>
          </>
        )}
        {step === "code_sent" && (
          <>
            <p className="text-sm text-muted-foreground">Check your Telegram app for the verification code.</p>
            <Input placeholder="Enter code" value={code} onChange={(e) => setCode(e.target.value)} />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <Button onClick={handleVerify} disabled={loading || !code} size="sm">
              {loading ? "Verifying..." : "Verify & Connect"}
            </Button>
          </>
        )}
        {(step === "done" || isConnected) && step !== "idle" && (
          <p className="text-sm text-primary">Telegram connected! Messages will be sent from your account.</p>
        )}
        {isConnected && step === "idle" && (
          <Button onClick={() => setStep("idle")} variant="outline" size="sm">
            Reconnect
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
