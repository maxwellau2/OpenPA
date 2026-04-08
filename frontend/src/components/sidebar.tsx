"use client";

import { useState, useEffect } from "react";
import { listConfig, listConversations, deleteConversation, Conversation } from "@/lib/api";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  Mail,
  GitPullRequest,
  Calendar,
  Music,
  Rss,
  MessageCircle,
  Search,
  Send,
  Globe,
  Clock,
  Brain,
  ChevronRight,
  Settings,
  Plus,
  MessageSquare,
  Trash2,
  Play,
} from "lucide-react";
import Link from "next/link";

interface SidebarSection {
  id: string;
  label: string;
  icon: React.ReactNode;
  service: string | null; // null = always available (like memory/rss)
  actions: { label: string; prompt: string }[];
}

const SECTIONS: SidebarSection[] = [
  {
    id: "email",
    label: "Email",
    icon: <Mail className="w-4 h-4" />,
    service: "google",
    actions: [
      { label: "Unread emails", prompt: "Check my unread emails" },
      { label: "Triage inbox", prompt: "Triage my inbox by urgency" },
      { label: "Send email", prompt: "Help me compose an email" },
    ],
  },
  {
    id: "github",
    label: "GitHub",
    icon: <GitPullRequest className="w-4 h-4" />,
    service: "github",
    actions: [
      { label: "Open PRs", prompt: "List my open pull requests" },
      { label: "Review a PR", prompt: "Review my latest PR" },
      { label: "Notifications", prompt: "Check my GitHub notifications" },
      { label: "Create issue", prompt: "Help me create a GitHub issue" },
      { label: "Vibe code", prompt: "Help me vibe code a new feature" },
    ],
  },
  {
    id: "calendar",
    label: "Calendar",
    icon: <Calendar className="w-4 h-4" />,
    service: "google",
    actions: [
      { label: "Today's events", prompt: "What's on my calendar today?" },
      { label: "This week", prompt: "Show me my week" },
      { label: "Create event", prompt: "Help me create a calendar event" },
      { label: "Plan my week", prompt: "Plan my week based on calendar, emails, and GitHub" },
    ],
  },
  {
    id: "spotify",
    label: "Spotify",
    icon: <Music className="w-4 h-4" />,
    service: "spotify",
    actions: [
      { label: "Now playing", prompt: "What's currently playing?" },
      { label: "Focus music", prompt: "Play some focus music" },
      { label: "Chill music", prompt: "Play something chill" },
      { label: "Search", prompt: "Search Spotify for " },
      { label: "My playlists", prompt: "Show my Spotify playlists" },
    ],
  },
  {
    id: "rss",
    label: "RSS Feeds",
    icon: <Rss className="w-4 h-4" />,
    service: null,
    actions: [
      { label: "Feed digest", prompt: "Summarize my RSS feeds" },
      { label: "Add feed", prompt: "Add an RSS feed: " },
      { label: "List feeds", prompt: "List my saved RSS feeds" },
    ],
  },
  {
    id: "discord",
    label: "Discord",
    icon: <MessageCircle className="w-4 h-4" />,
    service: "discord",
    actions: [
      { label: "Read messages", prompt: "Read recent Discord messages from channel " },
      { label: "Send message", prompt: "Send a Discord message to channel " },
      { label: "List channels", prompt: "List Discord channels in server " },
    ],
  },
  {
    id: "web_search",
    label: "Web Search",
    icon: <Search className="w-4 h-4" />,
    service: null,
    actions: [
      { label: "Search the web", prompt: "Search for " },
      { label: "Latest news on...", prompt: "Search for the latest news on " },
      { label: "What is...?", prompt: "Search the web: what is " },
    ],
  },
  {
    id: "telegram",
    label: "Telegram",
    icon: <Send className="w-4 h-4" />,
    service: "telegram",
    actions: [
      { label: "My chats", prompt: "List my Telegram chats" },
      { label: "Find contact", prompt: "Search my Telegram contacts for " },
      { label: "Send message", prompt: "Send a Telegram message to " },
      { label: "Read messages", prompt: "Read my Telegram messages from " },
    ],
  },
  {
    id: "mastodon",
    label: "Mastodon",
    icon: <Globe className="w-4 h-4" />,
    service: "mastodon",
    actions: [
      { label: "Home feed", prompt: "Show my Mastodon home timeline" },
      { label: "Trending tags", prompt: "What's trending on Mastodon?" },
      { label: "Trending posts", prompt: "Show trending posts on Mastodon" },
      { label: "Search posts", prompt: "Search Mastodon for " },
      { label: "Post a toot", prompt: "Help me post to Mastodon" },
      { label: "My profile", prompt: "Show my Mastodon profile info" },
    ],
  },
  {
    id: "youtube",
    label: "YouTube",
    icon: <Play className="w-4 h-4" />,
    service: null,
    actions: [
      { label: "Download video", prompt: "Download YouTube video from URL: " },
    ],
  },
  {
    id: "scheduler",
    label: "Scheduler",
    icon: <Clock className="w-4 h-4" />,
    service: null,
    actions: [
      { label: "Scheduled jobs", prompt: "List my scheduled tasks" },
      { label: "Schedule a task", prompt: "Schedule a task: " },
      { label: "Cancel a job", prompt: "Cancel scheduled task " },
    ],
  },
  {
    id: "memory",
    label: "Memory",
    icon: <Brain className="w-4 h-4" />,
    service: null,
    actions: [
      { label: "My preferences", prompt: "Show my saved preferences" },
      { label: "Save a note", prompt: "Save a note: " },
      { label: "Search history", prompt: "Search my conversation history for " },
    ],
  },
];

interface SidebarProps {
  onAction: (prompt: string) => void;
  onNewChat: () => void;
  onLoadConversation: (id: number) => void;
  activeConversationId?: number | null;
}

export default function Sidebar({ onAction, onNewChat, onLoadConversation, activeConversationId }: SidebarProps) {
  const [connectedServices, setConnectedServices] = useState<string[]>([]);
  const [expandedSection, setExpandedSection] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    listConfig()
      .then((data) => setConnectedServices(data.services.map((s) => s.service)))
      .catch(() => {});
    listConversations()
      .then((data) => setConversations(data.conversations))
      .catch(() => {});
  }, []);

  async function handleDeleteConversation(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    await deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
  }

  function isAvailable(section: SidebarSection) {
    return section.service === null || connectedServices.includes(section.service);
  }

  return (
    <div className="w-56 border-r border-border bg-card flex flex-col h-full">
      {/* New Chat + History toggle */}
      <div className="p-2 border-b border-border space-y-1">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium text-primary hover:bg-primary/10 transition-colors cursor-pointer"
        >
          <Plus className="w-4 h-4" />
          New Chat
        </button>
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="w-full flex items-center justify-between px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
        >
          <span className="flex items-center gap-2">
            <MessageSquare className="w-3 h-3" />
            History ({conversations.length})
          </span>
          <ChevronRight className={`w-3 h-3 transition-transform ${showHistory ? "rotate-90" : ""}`} />
        </button>
      </div>

      {/* Conversation history */}
      {showHistory && conversations.length > 0 && (
        <div className="border-b border-border max-h-48 overflow-y-auto">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              onClick={() => onLoadConversation(conv.id)}
              className={`flex items-center justify-between px-3 py-2 text-xs cursor-pointer group ${
                activeConversationId === conv.id
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
              }`}
            >
              <span className="truncate flex-1">{conv.title}</span>
              <button
                onClick={(e) => handleDeleteConversation(conv.id, e)}
                className="opacity-0 group-hover:opacity-100 p-0.5 hover:text-destructive transition-opacity cursor-pointer"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      <ScrollArea className="flex-1">
        <div className="p-2 space-y-0.5">
          {/* Quick actions */}
          <button
            onClick={() => onAction("Give me a daily briefing")}
            className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium text-primary hover:bg-primary/10 transition-colors cursor-pointer"
          >
            <ChevronRight className="w-3 h-3" />
            Daily Briefing
          </button>

          <Separator className="my-2" />

          {SECTIONS.map((section) => {
            const available = isAvailable(section);
            const isExpanded = expandedSection === section.id;

            return (
              <div key={section.id}>
                <button
                  onClick={() => setExpandedSection(isExpanded ? null : section.id)}
                  className={`w-full flex items-center justify-between px-3 py-2 rounded-md text-sm transition-colors cursor-pointer ${
                    available
                      ? "text-foreground hover:bg-secondary"
                      : "text-muted-foreground/50"
                  }`}
                >
                  <span className="flex items-center gap-2">
                    {section.icon}
                    {section.label}
                  </span>
                  <span className="flex items-center gap-1">
                    {!available && (
                      <Badge variant="outline" className="text-[10px] px-1 py-0">
                        Setup
                      </Badge>
                    )}
                    <ChevronRight
                      className={`w-3 h-3 transition-transform ${isExpanded ? "rotate-90" : ""}`}
                    />
                  </span>
                </button>

                {isExpanded && (
                  <div className="ml-4 pl-3 border-l border-border space-y-0.5 mb-1">
                    {available ? (
                      section.actions.map((action) => (
                        <button
                          key={action.label}
                          onClick={() => onAction(action.prompt)}
                          className="w-full text-left px-2 py-1.5 rounded text-xs text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors cursor-pointer"
                        >
                          {action.label}
                        </button>
                      ))
                    ) : (
                      <Link
                        href="/settings"
                        className="flex items-center gap-1 px-2 py-1.5 text-xs text-primary hover:underline"
                      >
                        <Settings className="w-3 h-3" />
                        Connect in Settings
                      </Link>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </ScrollArea>

      <div className="p-2 border-t border-border">
        <Link
          href="/settings"
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
        >
          <Settings className="w-4 h-4" />
          Settings
        </Link>
      </div>
    </div>
  );
}
