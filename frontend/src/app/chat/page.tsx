"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import Link from "next/link";
import { chatStream, listConfig, getConversation, SSEEvent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Send, Loader2, Bot, User, Wrench, Settings, ChevronDown, Brain, CheckCircle2, Circle, Square, Download } from "lucide-react";
import Sidebar from "@/components/sidebar";
import ReactMarkdown from "react-markdown";

interface Message {
  role: "user" | "assistant" | "system";
  content: string;
  thinking?: string;
  plan?: { step: number; description: string; tool?: string }[];
  toolActivity?: ToolActivity[];
}

interface ToolActivity {
  id: number;
  tool: string;
  status: "calling" | "done" | "error";
  arguments?: Record<string, unknown>;
  preview?: string;
}

interface PlanStep {
  step: number;
  description: string;
  status: "pending" | "running" | "done";
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [toolActivity, setToolActivity] = useState<ToolActivity[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [thinkingText, setThinkingText] = useState<string>("");
  const [planSteps, setPlanSteps] = useState<PlanStep[]>([]);
  const [hasServices, setHasServices] = useState(true);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    listConfig()
      .then((data) => setHasServices(data.services.length > 0))
      .catch(() => {});
  }, []);

  function handleNewChat() {
    setMessages([]);
    setConversationId(null);
    setInput("");
  }

  async function handleLoadConversation(id: number) {
    try {
      const data = await getConversation(id);
      setMessages(
        data.messages.map((m) => ({ role: m.role as "user" | "assistant", content: m.content }))
      );
      setConversationId(id);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolActivity]);

  function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }

  const sendMessage = useCallback(async (userMsg: string) => {
    if (!userMsg.trim() || loading) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);
    setToolActivity([]);
    setStatus("Thinking...");
    setThinkingText("");
    setPlanSteps([]);

    let assistantResponse = "";
    let allThinking = "";
    let completedPlan: { step: number; description: string; tool?: string }[] = [];
    let allToolActivity: ToolActivity[] = [];

    try {
      await chatStream(userMsg, (event: SSEEvent) => {
        switch (event.type) {
          case "compacted":
            setMessages((prev) => [
              ...prev,
              { role: "system", content: "Earlier messages have been summarized to save memory." },
            ]);
            break;
          case "thinking":
            const iter = event.data.iteration as number;
            setStatus(iter > 1 ? `Summarizing...` : "Thinking...");
            break;
          case "thinking_text":
            allThinking += (allThinking ? "\n\n" : "") + (event.data.text as string);
            setThinkingText(allThinking);
            break;
          case "planning":
            setStatus("Planning...");
            const steps = (event.data.steps as { step: number; description: string }[]) || [];
            completedPlan = steps.map((s) => ({ step: s.step, description: s.description }));
            setPlanSteps(steps.map((s) => ({ ...s, status: "pending" })));
            break;
          case "step":
            setStatus(`Step ${event.data.step}: ${event.data.description}`);
            const tool = event.data.tool as string;
            completedPlan = completedPlan.map((s) =>
              s.step === event.data.step ? { ...s, tool } : s
            );
            setPlanSteps((prev) =>
              prev.map((s) =>
                s.step === event.data.step ? { ...s, status: "running" } : s
              )
            );
            break;
          case "tool_call": {
            const newTool: ToolActivity = {
              id: allToolActivity.length,
              tool: event.data.tool as string,
              status: "calling",
              arguments: event.data.arguments as Record<string, unknown>,
            };
            allToolActivity = [...allToolActivity, newTool];
            setToolActivity([...allToolActivity]);
            break;
          }
          case "tool_result": {
            const preview = event.data.result_preview as string;
            const idx = [...allToolActivity].reverse().findIndex(
              (t) => t.tool === event.data.tool && t.status === "calling"
            );
            if (idx !== -1) {
              const realIdx = allToolActivity.length - 1 - idx;
              allToolActivity = allToolActivity.map((t, i) =>
                i === realIdx
                  ? { ...t, status: preview.startsWith("Error") ? "error" as const : "done" as const, preview }
                  : t
              );
              setToolActivity([...allToolActivity]);
            }
            setPlanSteps((prev) =>
              prev.map((s) => (s.status === "running" ? { ...s, status: "done" } : s))
            );
            break;
          }
          case "done":
            assistantResponse = event.data.response as string;
            if (event.data.conversation_id) {
              setConversationId(event.data.conversation_id as number);
            }
            break;
          case "error":
            assistantResponse = `Error: ${event.data.error}`;
            break;
        }
      }, "", "", controller.signal, conversationId);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        assistantResponse = assistantResponse || "(Stopped by user)";
      } else {
        assistantResponse = `Connection error: ${err instanceof Error ? err.message : "Unknown error"}`;
      }
    }

    setMessages((prev) => [
      ...prev,
      {
        role: "assistant",
        content: assistantResponse,
        thinking: allThinking || undefined,
        plan: completedPlan.length > 0 ? completedPlan : undefined,
        toolActivity: allToolActivity.length > 0 ? allToolActivity : undefined,
      },
    ]);
    abortRef.current = null;
    setToolActivity([]);
    setPlanSteps([]);
    setStatus(null);
    setThinkingText("");
    setLoading(false);
  }, [loading, conversationId]);

  function handleSidebarAction(prompt: string) {
    // If prompt ends with space, it's a partial prompt — put in input for user to complete
    if (prompt.endsWith(" ")) {
      setInput(prompt);
      inputRef.current?.focus();
    } else {
      sendMessage(prompt);
    }
  }

  async function handleSubmit(e?: { preventDefault?: () => void }) {
    e?.preventDefault?.();
    await sendMessage(input.trim());
  }

  return (
    <>
      {/* Sidebar */}
      <Sidebar
        onAction={handleSidebarAction}
        onNewChat={handleNewChat}
        onLoadConversation={handleLoadConversation}
        activeConversationId={conversationId}
      />

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-h-0">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4">
          <div className="max-w-3xl mx-auto space-y-4">
            {messages.length === 0 && (
              <div className="text-center py-20 space-y-4">
                <div className="text-4xl">
                  <Bot className="w-12 h-12 mx-auto text-primary" />
                </div>
                <h2 className="text-xl font-semibold text-foreground">Welcome to OpenPA</h2>
                <p className="text-muted-foreground max-w-md mx-auto">
                  Your personal assistant. Use the sidebar to quickly access
                  services, or just type what you need.
                </p>
                {!hasServices && (
                  <Link
                    href="/settings"
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 transition-colors text-sm font-medium"
                  >
                    <Settings className="w-4 h-4" />
                    Connect your services first (GitHub, Gmail, Spotify...)
                  </Link>
                )}
                <div className="flex flex-wrap gap-2 justify-center mt-4">
                  {[
                    "Give me a daily briefing",
                    "Check my emails",
                    "List my open PRs",
                    "Play some focus music",
                    "Summarize my RSS feeds",
                  ].map((suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => sendMessage(suggestion)}
                      className="text-sm px-3 py-1.5 rounded-full border border-border text-muted-foreground hover:bg-secondary hover:text-secondary-foreground transition-colors cursor-pointer"
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              msg.role === "system" ? (
                <div key={i} className="flex justify-center">
                  <div className="px-3 py-1 rounded-full bg-muted text-muted-foreground text-xs flex items-center gap-1.5">
                    <Brain className="w-3 h-3" />
                    {msg.content}
                  </div>
                </div>
              ) : (
              <div
                key={i}
                className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "assistant" && (
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    <Bot className="w-4 h-4 text-primary" />
                  </div>
                )}
                <div
                  className={`max-w-[80%] space-y-2 ${
                    msg.role === "user" ? "" : ""
                  }`}
                >
                  {/* Thinking block (collapsible) */}
                  {msg.thinking && <ThinkingBlock text={msg.thinking} />}

                  {/* Plan steps (collapsible) */}
                  {msg.plan && <PlanBlock steps={msg.plan} />}

                  {/* Tool activity (collapsible) */}
                  {msg.toolActivity && msg.toolActivity.length > 0 && (
                    <ToolActivityBlock tools={msg.toolActivity} />
                  )}

                  {/* Message content */}
                  <div
                    className={`rounded-xl px-4 py-2.5 ${
                      msg.role === "user"
                        ? "bg-primary text-white"
                        : "bg-card border border-border"
                    }`}
                  >
                    <div className="text-sm prose prose-sm dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
                      <ReactMarkdown components={{
                        a: ({ href, children }) => {
                          if (href && href.includes("/api/download/")) {
                            const token = typeof window !== "undefined" ? localStorage.getItem("openpa_token") : null;
                            const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
                            const fullUrl = `${apiBase}${href}`;
                            return (
                              <a
                                href={fullUrl}
                                onClick={(e) => {
                                  e.preventDefault();
                                  fetch(fullUrl, { headers: { Authorization: `Bearer ${token}` } })
                                    .then(res => {
                                      if (!res.ok) throw new Error("Download failed");
                                      const filename = res.headers.get("content-disposition")?.match(/filename="?(.+)"?/)?.[1] || "download";
                                      return res.blob().then(blob => ({ blob, filename }));
                                    })
                                    .then(({ blob, filename }) => {
                                      const url = URL.createObjectURL(blob);
                                      const a = document.createElement("a");
                                      a.href = url; a.download = filename; a.click();
                                      URL.revokeObjectURL(url);
                                    })
                                    .catch(err => alert(err.message));
                                }}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white no-underline text-xs font-medium hover:bg-primary/90 transition-colors cursor-pointer"
                              >
                                <Download className="w-3.5 h-3.5" />
                                {children}
                              </a>
                            );
                          }
                          return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
                        },
                      }}>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
                {msg.role === "user" && (
                  <div className="w-8 h-8 rounded-full bg-secondary flex items-center justify-center shrink-0">
                    <User className="w-4 h-4 text-secondary-foreground" />
                  </div>
                )}
              </div>
              )
            ))}

            {/* Status + thinking + tool activity */}
            {loading && (
              <div className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <Bot className="w-4 h-4 text-primary" />
                </div>
                <div className="space-y-2 max-w-[80%]">
                  {/* Live thinking text */}
                  {thinkingText && <ThinkingBlock text={thinkingText} defaultOpen />}

                  {/* Status + plan steps + tools */}
                  <div className="bg-card border border-border rounded-xl px-4 py-3 space-y-2 min-w-[250px]">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="w-3 h-3 animate-spin text-primary" />
                      <span>{status || "Thinking..."}</span>
                    </div>

                    {/* Plan steps */}
                    {planSteps.length > 0 && (
                      <div className="space-y-1 pt-1 border-t border-border">
                        {planSteps.map((s) => (
                          <div key={s.step} className="flex items-center gap-2 text-xs">
                            {s.status === "done" ? (
                              <CheckCircle2 className="w-3 h-3 text-primary" />
                            ) : s.status === "running" ? (
                              <Loader2 className="w-3 h-3 animate-spin text-primary" />
                            ) : (
                              <Circle className="w-3 h-3 text-muted-foreground/40" />
                            )}
                            <span className={s.status === "done" ? "text-muted-foreground" : s.status === "running" ? "text-foreground" : "text-muted-foreground/60"}>
                              {s.description}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Tool calls */}
                    {toolActivity.length > 0 && (
                      <div className="space-y-1 pt-1 border-t border-border">
                        {toolActivity.map((t) => (
                          <ToolCallEntry key={t.id} tool={t} />
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            <div ref={scrollRef} />
          </div>
        </div>

        {/* Input */}
        <div className="border-t border-border bg-card p-4">
          <div className="max-w-3xl mx-auto flex gap-2 items-end">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                // Auto-grow
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 200) + "px";
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit(e);
                }
              }}
              placeholder="Ask your assistant... (Shift+Enter for new line)"
              disabled={loading}
              rows={1}
              className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            />
            {loading ? (
              <Button type="button" onClick={handleStop} size="icon" variant="destructive" className="shrink-0">
                <Square className="w-4 h-4" />
              </Button>
            ) : (
              <Button type="button" onClick={(e) => handleSubmit(e)} disabled={!input.trim()} size="icon" className="shrink-0">
                <Send className="w-4 h-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

function ThinkingBlock({ text, defaultOpen = false }: { text: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-xl border border-border bg-muted/30 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <Brain className="w-3 h-3" />
        <span className="font-medium">Thinking</span>
        <ChevronDown
          className={`w-3 h-3 ml-auto transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 border-t border-border">
          <pre className="text-xs text-muted-foreground whitespace-pre-wrap mt-2 max-h-[300px] overflow-y-auto leading-relaxed">
            {text}
          </pre>
        </div>
      )}
    </div>
  );
}

function PlanBlock({ steps }: { steps: { step: number; description: string; tool?: string }[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-muted/30 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <CheckCircle2 className="w-3 h-3 text-primary" />
        <span className="font-medium">Executed {steps.length} steps</span>
        <ChevronDown
          className={`w-3 h-3 ml-auto transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 border-t border-border space-y-1.5 mt-2">
          {steps.map((s) => (
            <div key={s.step} className="flex items-center gap-2 text-xs">
              <CheckCircle2 className="w-3 h-3 text-primary shrink-0" />
              <span className="text-muted-foreground">{s.description}</span>
              {s.tool && (
                <Badge variant="secondary" className="text-[10px] font-mono px-1 py-0">
                  {s.tool}
                </Badge>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCallEntry({ tool }: { tool: ToolActivity }) {
  const [open, setOpen] = useState(false);

  const statusIcon = tool.status === "calling" ? (
    <Loader2 className="w-3 h-3 animate-spin text-primary" />
  ) : tool.status === "error" ? (
    <Circle className="w-3 h-3 text-red-500" />
  ) : (
    <CheckCircle2 className="w-3 h-3 text-primary" />
  );

  return (
    <div className="text-xs">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 py-1 hover:bg-muted/50 rounded px-1 transition-colors cursor-pointer"
      >
        {statusIcon}
        <Badge variant="secondary" className="text-[10px] font-mono px-1.5 py-0">
          {tool.tool}
        </Badge>
        {tool.status === "error" && (
          <span className="text-red-500 text-[10px]">failed</span>
        )}
        <ChevronDown
          className={`w-3 h-3 ml-auto text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="ml-5 mt-1 space-y-1.5 pb-1">
          {tool.arguments && Object.keys(tool.arguments).length > 0 && (
            <div>
              <span className="text-muted-foreground font-medium">Args:</span>
              <pre className="mt-0.5 p-2 rounded bg-muted/50 text-[11px] text-muted-foreground whitespace-pre-wrap max-h-[200px] overflow-y-auto leading-relaxed">
                {JSON.stringify(tool.arguments, null, 2)}
              </pre>
            </div>
          )}
          {tool.preview && (
            <div>
              <span className={`font-medium ${tool.status === "error" ? "text-red-500" : "text-muted-foreground"}`}>
                Result:
              </span>
              <pre className={`mt-0.5 p-2 rounded text-[11px] whitespace-pre-wrap max-h-[300px] overflow-y-auto leading-relaxed ${
                tool.status === "error" ? "bg-red-500/10 text-red-400" : "bg-muted/50 text-muted-foreground"
              }`}>
                {tool.preview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ToolActivityBlock({ tools }: { tools: ToolActivity[] }) {
  const [open, setOpen] = useState(false);
  const errorCount = tools.filter((t) => t.status === "error").length;

  return (
    <div className="rounded-xl border border-border bg-muted/30 overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
      >
        <Wrench className="w-3 h-3 text-primary" />
        <span className="font-medium">
          {tools.length} tool call{tools.length !== 1 ? "s" : ""}
          {errorCount > 0 && (
            <span className="text-red-500 ml-1">({errorCount} failed)</span>
          )}
        </span>
        <ChevronDown
          className={`w-3 h-3 ml-auto transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="px-2 pb-2 border-t border-border mt-1">
          {tools.map((t) => (
            <ToolCallEntry key={t.id} tool={t} />
          ))}
        </div>
      )}
    </div>
  );
}
