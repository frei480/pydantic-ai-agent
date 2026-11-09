import {
  AlertCircle,
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  CircleHelp,
  FileCode2,
  Layers3,
  LoaderCircle,
  Menu,
  MessageSquare,
  Plus,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Chat = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type ServiceHealth = "checking" | "ok" | "down";
type Activity = {
  id: number;
  kind: "phase" | "tool" | "draft" | "critique" | "warning";
  text: string;
  sufficient?: boolean;
};

type StreamEvent = {
  type?: string;
  phase?: string;
  round?: number;
  detail?: string;
  text?: string;
  message?: string;
  sufficient?: boolean;
  comments?: string;
  missing?: string[];
  chat?: Chat;
};

type Provider = "openai" | "openrouter" | "ollama" | "lmstudio" | "custom";
type ModelSettings = {
  provider: Provider;
  model: string;
  base_url: string;
  api_key_configured: boolean;
  context_window_tokens: number;
};

type SettingsForm = {
  provider: Provider;
  model: string;
  base_url: string;
  api_key: string;
  clear_api_key: boolean;
  context_window_tokens: number;
};

const providerOptions: { value: Provider; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "ollama", label: "Ollama" },
  { value: "lmstudio", label: "LM Studio" },
  { value: "custom", label: "Другой OpenAI-совместимый API" },
];

const providerDefaults: Record<Provider, { base_url: string; model: string }> = {
  openai: { base_url: "", model: "gpt-4o-mini" },
  openrouter: { base_url: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini" },
  ollama: { base_url: "http://host.docker.internal:11434/v1", model: "qwen2.5:7b" },
  lmstudio: { base_url: "http://host.docker.internal:1234/v1", model: "local-model" },
  custom: { base_url: "", model: "" },
};

const suggestions = [
  {
    icon: FileCode2,
    title: "Создать сплайн",
    description: "Как создать сплайн на 2D-сцене через API?",
  },
  {
    icon: Layers3,
    title: "Работа со слоями",
    description: "Как создать слой T-FLEX DOCs, связанный с параметром детали?",
  },
  {
    icon: BookOpen,
    title: "Найти методы класса",
    description: "Найди в документации все методы класса DocDocument.",
  },
];

const phaseLabels: Record<string, string> = {
  research: "Ищу в документации",
  critique: "Проверяю полноту",
  refine: "Уточняю поиск",
  write: "Готовлю ответ",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail || detail;
    } catch {
      // Non-JSON error responses use the HTTP status as their message.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function parseEvent(chunk: string): StreamEvent | null {
  const data = chunk
    .split(/\r?\n/)
    .find((line) => line.startsWith("data:"))
    ?.slice(5)
    .trim();
  if (!data) return null;
  try {
    return JSON.parse(data) as StreamEvent;
  } catch {
    return null;
  }
}

function ServiceIndicator({ label, status, title }: { label: string; status: ServiceHealth; title: string }) {
  const color =
    status === "ok" ? "bg-emerald-500" : status === "down" ? "bg-rose-500" : "bg-amber-400";
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-500" title={title} role="status">
      <span className={`h-2 w-2 rounded-full ${color} ${status === "checking" ? "pulse-dot" : ""}`} />
      <span className="hidden sm:inline">{label}</span>
    </span>
  );
}

function App() {
  const [chats, setChats] = useState<Chat[]>([]);
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [currentTitle, setCurrentTitle] = useState("Новый чат");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activities, setActivities] = useState<Activity[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [backendHealth, setBackendHealth] = useState<ServiceHealth>("checking");
  const [modelHealth, setModelHealth] = useState<ServiceHealth>("checking");
  const [modelName, setModelName] = useState("");
  const [modelDetail, setModelDetail] = useState("");
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [settingsSuccess, setSettingsSuccess] = useState("");
  const [hasSavedApiKey, setHasSavedApiKey] = useState(false);
  const [settings, setSettings] = useState<SettingsForm>({
    provider: "openai",
    model: "gpt-4o-mini",
    base_url: "",
    api_key: "",
    clear_api_key: false,
    context_window_tokens: 120000,
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const activityId = useRef(0);
  const healthCheckRunning = useRef(false);

  const scrollBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, []);

  useEffect(() => {
    scrollBottom();
  }, [messages, activities, scrollBottom]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, window.innerHeight * 0.35)}px`;
  }, [input]);

  const loadChats = useCallback(async () => {
    const data = await api<Chat[]>("/api/chats");
    setChats(data);
  }, []);

  const checkHealth = useCallback(async () => {
    if (healthCheckRunning.current) return;
    healthCheckRunning.current = true;
    const request = async <T,>(path: string, timeoutMs: number): Promise<T> => {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        return await api<T>(path, { cache: "no-store", signal: controller.signal });
      } finally {
        window.clearTimeout(timeout);
      }
    };

    try {
      try {
        await request<unknown>("/api/health", 5_000);
        setBackendHealth("ok");
      } catch {
        setBackendHealth("down");
        setModelHealth("down");
        return;
      }

      try {
        const model = await request<{ status: string; model: string; detail: string }>("/api/health/model", 15_000);
        setModelName(model.model);
        setModelDetail(model.detail);
        setModelHealth(model.status === "ok" ? "ok" : "down");
      } catch {
        setModelDetail("Не удалось проверить доступность модели");
        setModelHealth("down");
      }
    } finally {
      healthCheckRunning.current = false;
    }
  }, []);

  useEffect(() => {
    void loadChats().catch((loadError: unknown) =>
      setError(`Не удалось загрузить чаты: ${errorMessage(loadError)}`),
    );
    void checkHealth();
    const timer = window.setInterval(() => void checkHealth(), 60_000);
    return () => window.clearInterval(timer);
  }, [checkHealth, loadChats]);

  const addActivity = (activity: Omit<Activity, "id">) => {
    setActivities((current) => [...current, { ...activity, id: ++activityId.current }]);
  };

  const selectChat = async (chat: Chat) => {
    if (busy) return;
    setError("");
    setCurrentId(chat.id);
    setCurrentTitle(chat.title);
    setMessages([]);
    setActivities([]);
    setSidebarOpen(false);
    try {
      const data = await api<{ chat: Chat; messages: ChatMessage[] }>(`/api/chats/${chat.id}/messages`);
      setCurrentTitle(data.chat.title);
      setMessages(data.messages);
    } catch (loadError) {
      setError(`Не удалось открыть чат: ${errorMessage(loadError)}`);
    }
  };

  const startNewChat = () => {
    if (busy) return;
    setCurrentId(null);
    setCurrentTitle("Новый чат");
    setMessages([]);
    setActivities([]);
    setStatus("");
    setError("");
    setSidebarOpen(false);
    inputRef.current?.focus();
  };

  const openSettings = async () => {
    setSettingsOpen(true);
    setSettingsLoading(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      const current = await api<ModelSettings>("/api/settings");
      setSettings({
        ...current,
        api_key: "",
        clear_api_key: false,
      });
      setHasSavedApiKey(current.api_key_configured);
    } catch (loadError) {
      setSettingsError(`Не удалось загрузить настройки: ${errorMessage(loadError)}`);
    } finally {
      setSettingsLoading(false);
    }
  };

  const saveSettings = async (event: FormEvent) => {
    event.preventDefault();
    if (settingsSaving) return;
    setSettingsSaving(true);
    setSettingsError("");
    setSettingsSuccess("");
    try {
      const saved = await api<ModelSettings>("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: settings.provider,
          model: settings.model,
          base_url: settings.base_url,
          api_key: settings.api_key || undefined,
          clear_api_key: settings.clear_api_key,
          context_window_tokens: settings.context_window_tokens,
        }),
      });
      setSettings({
        ...saved,
        api_key: "",
        clear_api_key: false,
      });
      setHasSavedApiKey(saved.api_key_configured);
      setSettingsSuccess("Настройки сохранены. Проверяю подключение к модели…");
      await checkHealth();
      setSettingsSuccess("Настройки сохранены. Состояние подключения обновлено.");
    } catch (saveError) {
      setSettingsError(`Не удалось сохранить настройки: ${errorMessage(saveError)}`);
    } finally {
      setSettingsSaving(false);
    }
  };

  const chooseProvider = (provider: Provider) => {
    const currentDefault = providerDefaults[settings.provider];
    const useNewDefaults = !settings.base_url || settings.base_url === currentDefault.base_url;
    setSettings((current) => ({
      ...current,
      provider,
      base_url: useNewDefaults ? providerDefaults[provider].base_url : current.base_url,
      model:
        !current.model || current.model === currentDefault.model
          ? providerDefaults[provider].model
          : current.model,
    }));
  };

  const deleteChat = async (event: MouseEvent<HTMLButtonElement>, chat: Chat) => {
    event.stopPropagation();
    if (busy || !window.confirm("Удалить чат?")) return;
    setError("");
    try {
      await api(`/api/chats/${chat.id}`, { method: "DELETE" });
      if (currentId === chat.id) startNewChat();
      await loadChats();
    } catch (deleteError) {
      setError(`Не удалось удалить чат: ${errorMessage(deleteError)}`);
    }
  };

  const submitMessage = async (event?: FormEvent) => {
    event?.preventDefault();
    const content = input.trim();
    if (!content || busy) return;

    setInput("");
    setError("");
    setActivities([]);
    setBusy(true);
    let chatId = currentId;
    try {
      if (chatId === null) {
        const chat = await api<Chat>("/api/chats", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title: content.slice(0, 60) }),
        });
        chatId = chat.id;
        setCurrentId(chat.id);
      }

      await loadChats();
      setCurrentTitle(content.slice(0, 60));
      setMessages((current) => [...current, { role: "user", content }, { role: "assistant", content: "" }]);
      const response = await fetch(`/api/chats/${chatId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        let detail = "Ошибка сервера";
        try {
          const body = (await response.json()) as { detail?: string };
          detail = body.detail || detail;
        } catch {
          detail = `${response.status} ${response.statusText}`;
        }
        throw new Error(detail);
      }
      if (!response.body) throw new Error("Сервер не вернул поток ответа");

      let answer = "";
      let buffer = "";
      let draftSeen = false;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const handleEvent = (event: StreamEvent) => {
        switch (event.type) {
          case "start":
            if (event.chat?.title) setCurrentTitle(event.chat.title);
            break;
          case "phase": {
            const label = phaseLabels[event.phase || ""] || "Обрабатываю запрос";
            setStatus(event.round && event.round > 1 ? `${label} · итерация ${event.round}` : label);
            if (event.phase === "research") addActivity({ kind: "phase", text: "Ищу в документации…" });
            if (event.phase === "write") setStatus(phaseLabels.write);
            break;
          }
          case "tool":
            addActivity({ kind: "tool", text: event.detail || "Вызван инструмент поиска" });
            break;
          case "draft":
            if (!draftSeen) {
              draftSeen = true;
              addActivity({ kind: "draft", text: "Исследователь собирает факты…" });
            }
            break;
          case "critique": {
            const missing = (event.missing || []).slice(0, 3).join("; ");
            addActivity({
              kind: "critique",
              text: event.comments || missing || (event.sufficient ? "Данных достаточно" : "Нужно уточнить поиск"),
              sufficient: event.sufficient,
            });
            break;
          }
          case "text":
            answer += event.text || "";
            setMessages((current) => {
              const next = [...current];
              const last = next.at(-1);
              if (last?.role === "assistant") next[next.length - 1] = { ...last, content: answer };
              return next;
            });
            break;
          case "error":
            answer += `${answer ? "\n\n" : ""}**Ошибка:** ${event.message || "Неизвестная ошибка"}`;
            setMessages((current) => {
              const next = [...current];
              const last = next.at(-1);
              if (last?.role === "assistant") next[next.length - 1] = { ...last, content: answer };
              return next;
            });
            break;
          case "warning":
            addActivity({
              kind: "warning",
              text: event.message || "Контекст запроса был сокращён.",
            });
            break;
          default:
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let boundary = buffer.indexOf("\n\n");
        while (boundary !== -1) {
          const chunk = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const parsed = parseEvent(chunk);
          if (parsed) handleEvent(parsed);
          boundary = buffer.indexOf("\n\n");
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) {
        const parsed = parseEvent(buffer);
        if (parsed) handleEvent(parsed);
      }
      setStatus("");
      await loadChats();
    } catch (sendError) {
      const message = errorMessage(sendError);
      setError(message);
      setMessages((current) => {
        const last = current.at(-1);
        if (last?.role === "assistant" && !last.content) {
          return [...current.slice(0, -1), { ...last, content: `**Ошибка:** ${message}` }];
        }
        return current;
      });
    } finally {
      setBusy(false);
      setStatus("");
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitMessage();
    }
  };

  return (
    <div className="flex h-[100dvh] overflow-hidden bg-[#f8f9fb]">
      {sidebarOpen && (
        <button
          aria-label="Закрыть меню"
          className="fixed inset-0 z-30 bg-slate-950/25 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-[280px] shrink-0 flex-col border-r border-slate-200/80 bg-white transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-[76px] items-center gap-3 px-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-[#315fce] text-white shadow-sm shadow-blue-900/15">
            <BookOpen size={19} strokeWidth={2.2} />
          </div>
          <div className="min-w-0">
            <div className="text-[14px] font-semibold tracking-[-0.02em] text-slate-900">Docs AI Agent</div>
            <div className="mt-0.5 text-[11px] text-slate-400">Помощник по документации</div>
          </div>
          <button
            aria-label="Закрыть меню"
            className="ml-auto rounded-lg p-2 text-slate-400 hover:bg-slate-100 md:hidden"
            onClick={() => setSidebarOpen(false)}
          >
            <X size={17} />
          </button>
        </div>

        <div className="px-3 pb-5">
          <button
            onClick={startNewChat}
            disabled={busy}
            className="flex w-full items-center gap-2.5 rounded-xl border border-slate-200 px-3.5 py-2.5 text-left text-[13px] font-medium text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.03)] transition hover:border-blue-200 hover:bg-blue-50/60 hover:text-[#315fce] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Plus size={16} />
            Новый чат
          </button>
        </div>

        <div className="px-5 pb-2 text-[10px] font-semibold tracking-[0.13em] text-slate-400 uppercase">
          История чатов
        </div>
        <nav aria-label="Чаты" className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-4">
          {chats.length === 0 ? (
            <div className="px-3 py-5 text-xs leading-5 text-slate-400">Здесь появятся ваши диалоги</div>
          ) : (
            chats.map((chat) => (
              <div
                key={chat.id}
                className={`group mb-0.5 flex w-full items-center rounded-lg text-[12px] transition ${
                  chat.id === currentId
                    ? "bg-blue-50 font-medium text-[#315fce]"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                <button
                  type="button"
                  aria-current={chat.id === currentId ? "page" : undefined}
                  onClick={() => void selectChat(chat)}
                  className="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2.5 text-left"
                >
                  <MessageSquare size={14} className="shrink-0 opacity-65" />
                  <span className="min-w-0 flex-1 truncate">{chat.title}</span>
                </button>
                <button
                  type="button"
                  aria-label={`Удалить чат: ${chat.title}`}
                  title="Удалить чат"
                  onClick={(event) => void deleteChat(event, chat)}
                  className="mr-2 rounded p-1 text-slate-400 opacity-0 transition hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 focus:opacity-100"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))
          )}
        </nav>

        <div className="border-t border-slate-100 p-4">
          <div className="flex items-center gap-3 rounded-xl bg-slate-50/80 px-3 py-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-[#315fce]">
              <Sparkles size={15} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-xs font-medium text-slate-700">Проверенные ответы</div>
              <div className="mt-0.5 truncate text-[10px] text-slate-400">С опорой на API-документацию</div>
            </div>
          </div>
        </div>
      </aside>

      <main className="relative flex min-w-0 flex-1 flex-col">
        <header className="flex h-[62px] shrink-0 items-center gap-3 border-b border-slate-200/70 bg-white/90 px-4 sm:px-7">
          <button
            aria-label="Открыть меню"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 md:hidden"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu size={18} />
          </button>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold text-slate-800">{currentTitle}</div>
            {status && <div className="mt-0.5 truncate text-[10px] text-slate-400">{status}</div>}
          </div>
          <div className="flex shrink-0 items-center gap-3 border-l border-slate-100 pl-3 sm:gap-4 sm:pl-5">
            <ServiceIndicator
              label="Backend"
              status={backendHealth}
              title={backendHealth === "ok" ? "Backend доступен" : "Backend недоступен"}
            />
            <ServiceIndicator
              label={modelName ? `Модель · ${modelName}` : "Модель"}
              status={modelHealth}
              title={modelDetail || modelName || "Состояние модели"}
            />
          </div>
          <button
            type="button"
            aria-label="Настройки ИИ-провайдера"
            title="Настройки ИИ-провайдера"
            onClick={() => void openSettings()}
            className="ml-1 rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-[#315fce]"
          >
            <Settings2 size={17} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col">
          <section className="min-h-0 flex-1 overflow-y-auto px-4 pt-6 pb-5 sm:px-8 sm:pt-9">
            {error && (
              <div className="mx-auto mb-5 flex max-w-[820px] items-start gap-2.5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs leading-5 text-rose-700">
                <AlertCircle size={16} className="mt-0.5 shrink-0" />
                <span className="flex-1">{error}</span>
                <button
                  aria-label="Закрыть уведомление"
                  onClick={() => setError("")}
                  className="text-rose-400 hover:text-rose-700"
                >
                  <X size={15} />
                </button>
              </div>
            )}

            {messages.length === 0 ? (
              <div className="mx-auto flex min-h-full max-w-[800px] flex-col justify-center pb-10">
                <div className="mb-8 text-center">
                  <div className="mx-auto mb-5 flex h-[54px] w-[54px] items-center justify-center rounded-[18px] bg-blue-50 text-[#315fce] ring-1 ring-blue-100">
                    <Sparkles size={24} strokeWidth={1.7} />
                  </div>
                  <p className="mb-2 text-[11px] font-semibold tracking-[0.15em] text-[#5277c6] uppercase">
                    Ваш AI-помощник
                  </p>
                  <h1 className="text-[27px] font-semibold tracking-[-0.04em] text-slate-900 sm:text-[32px]">
                    Что будем искать?
                  </h1>
                  <p className="mx-auto mt-3 max-w-[430px] text-[13px] leading-6 text-slate-500">
                    Задайте вопрос по API-документации — агент найдёт источники, проверит факты и подготовит ответ с
                    кодом.
                  </p>
                </div>
                <div className="grid gap-2.5 sm:grid-cols-3">
                  {suggestions.map(({ icon: Icon, title, description }) => (
                    <button
                      key={title}
                      onClick={() => {
                        setInput(description);
                        inputRef.current?.focus();
                      }}
                      className="group rounded-xl border border-slate-200/80 bg-white p-4 text-left shadow-[0_2px_8px_rgba(20,35,70,0.025)] transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-[0_8px_24px_rgba(30,64,130,0.08)]"
                    >
                      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg bg-slate-50 text-slate-500 transition group-hover:bg-blue-50 group-hover:text-[#315fce]">
                        <Icon size={16} />
                      </div>
                      <div className="text-xs font-semibold text-slate-700">{title}</div>
                      <div className="mt-1.5 text-[11px] leading-[1.65] text-slate-400">{description}</div>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="mx-auto flex max-w-[820px] flex-col gap-5">
                {messages.map((message, index) => (
                  <div key={`${index}-${message.role}`} className={message.role === "user" ? "flex justify-end" : "flex gap-3"}>
                    {message.role === "assistant" && (
                      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[11px] bg-[#315fce] text-white">
                        <Sparkles size={15} />
                      </div>
                    )}
                    <div
                      className={
                        message.role === "user"
                          ? "max-w-[85%] rounded-2xl rounded-br-md bg-[#315fce] px-4 py-3 text-[13px] leading-6 text-white shadow-sm sm:max-w-[75%]"
                          : "min-w-0 flex-1 pt-1 text-[13px] text-slate-700"
                      }
                    >
                      {message.role === "assistant" ? (
                        message.content ? (
                          <div className="markdown-content">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                            {busy && index === messages.length - 1 && message.content && (
                              <span className="ml-1 inline-block h-4 w-1 animate-pulse rounded bg-blue-500 align-middle" />
                            )}
                          </div>
                        ) : (
                          <div className="flex items-center gap-2 py-1 text-xs text-slate-400">
                            <LoaderCircle size={14} className="animate-spin text-[#5277c6]" />
                            Ищу ответ в документации…
                          </div>
                        )
                      ) : (
                        message.content
                      )}
                    </div>
                  </div>
                ))}
                {activities.length > 0 && (
                  <div className="ml-11 -mt-2 max-w-[650px] overflow-hidden rounded-xl border border-slate-200/70 bg-white/80">
                    <details className="group">
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[11px] text-slate-500">
                        {activities.some((activity) => activity.kind === "warning") ? (
                          <AlertCircle size={13} className="text-amber-500" />
                        ) : busy ? (
                          <LoaderCircle size={13} className="animate-spin text-blue-500" />
                        ) : (
                          <Check size={13} className="text-emerald-500" />
                        )}
                        <span className="flex-1">
                          {activities.some((activity) => activity.kind === "warning")
                            ? "Контекст запроса сокращён — показать подробности"
                            : busy
                              ? "Агент работает"
                              : "Ход работы агента"}{" "}
                          · {activities.length}
                        </span>
                        <ChevronDown size={13} className="transition group-open:rotate-180" />
                      </summary>
                      <div className="border-t border-slate-100 px-3.5 py-2">
                        {activities.map((activity) => (
                          <div key={activity.id} className="flex items-start gap-2 py-1 text-[11px] leading-5 text-slate-500">
                            {activity.kind === "critique" ? (
                              <span
                                className={`mt-1 shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium ${
                                  activity.sufficient
                                    ? "bg-emerald-50 text-emerald-700"
                                    : "bg-amber-50 text-amber-700"
                                }`}
                              >
                                {activity.sufficient ? "Проверено" : "Уточнение"}
                              </span>
                            ) : activity.kind === "warning" ? (
                              <AlertCircle size={13} className="mt-1 shrink-0 text-amber-500" />
                            ) : (
                              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-slate-300" />
                            )}
                            <span className="min-w-0 break-words">{activity.text}</span>
                          </div>
                        ))}
                      </div>
                    </details>
                  </div>
                )}
              </div>
            )}
            <div ref={messagesEndRef} />
          </section>

          <div className="shrink-0 bg-gradient-to-t from-[#f8f9fb] via-[#f8f9fb] to-transparent px-4 pt-2 pb-4 sm:px-8 sm:pb-6">
            <form
              onSubmit={(event) => void submitMessage(event)}
              className="mx-auto max-w-[820px] rounded-2xl border border-slate-200 bg-white p-2 shadow-[0_8px_30px_rgba(25,40,75,0.07)] transition focus-within:border-blue-200 focus-within:shadow-[0_8px_32px_rgba(49,95,206,0.10)]"
            >
              <textarea
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Спросите что-нибудь о API…"
                rows={1}
                disabled={busy}
                aria-label="Сообщение"
                className="block max-h-[35vh] min-h-11 w-full resize-none bg-transparent px-3 py-3 text-[13px] leading-5 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-60"
              />
              <div className="flex items-center justify-between px-1.5 pb-0.5">
                <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                  <CircleHelp size={12} />
                  <span className="hidden sm:inline">Ответы основаны на вашей документации</span>
                  <span className="sm:hidden">Поиск по документации</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="hidden text-[10px] text-slate-400 sm:inline">
                    Enter — отправить · Shift + Enter — новая строка
                  </span>
                  <button
                    type="submit"
                    disabled={busy || !input.trim()}
                    aria-label="Отправить сообщение"
                    title="Отправить"
                    className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-[#315fce] text-white transition hover:bg-[#244eaf] disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-400"
                  >
                    {busy ? <LoaderCircle size={15} className="animate-spin" /> : <ArrowUp size={17} />}
                  </button>
                </div>
              </div>
            </form>
            <div className="mt-2 text-center text-[10px] text-slate-400">
              AI может ошибаться — проверяйте важные детали по источникам
            </div>
          </div>
        </div>
      </main>
      {settingsOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-[2px]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !settingsSaving) setSettingsOpen(false);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !settingsSaving) setSettingsOpen(false);
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            className="max-h-[min(90dvh,760px)] w-full max-w-[500px] overflow-y-auto rounded-2xl border border-slate-200 bg-white shadow-[0_24px_80px_rgba(15,23,42,0.22)]"
          >
            <div className="flex items-start gap-3 border-b border-slate-100 px-5 py-4 sm:px-6">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-[#315fce]">
                <Settings2 size={18} />
              </div>
              <div className="min-w-0 flex-1">
                <h2 id="settings-title" className="text-[15px] font-semibold text-slate-900">
                  Настройки ИИ-провайдера
                </h2>
                <p className="mt-1 text-[11px] leading-5 text-slate-500">
                  Настройки применяются ко всем чатам этого сервера.
                </p>
              </div>
              <button
                type="button"
                aria-label="Закрыть настройки"
                disabled={settingsSaving}
                onClick={() => setSettingsOpen(false)}
                className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
              >
                <X size={17} />
              </button>
            </div>

            {settingsLoading ? (
              <div className="flex items-center justify-center gap-2 px-6 py-12 text-xs text-slate-500">
                <LoaderCircle size={16} className="animate-spin" />
                Загружаю настройки…
              </div>
            ) : (
              <form onSubmit={(event) => void saveSettings(event)} className="space-y-4 px-5 py-5 sm:px-6">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-slate-700">Провайдер</span>
                  <select
                    value={settings.provider}
                    onChange={(event) => chooseProvider(event.target.value as Provider)}
                    disabled={settingsSaving}
                    className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  >
                    {providerOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-slate-700">Модель</span>
                  <input
                    required
                    maxLength={200}
                    value={settings.model}
                    onChange={(event) => setSettings((current) => ({ ...current, model: event.target.value }))}
                    placeholder="Например, gpt-4o-mini"
                    disabled={settingsSaving}
                    className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  />
                </label>

                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-slate-700">
                    Окно контекста модели (токенов)
                  </span>
                  <input
                    type="number"
                    required
                    min={4096}
                    max={2_000_000}
                    step={1024}
                    value={settings.context_window_tokens}
                    onChange={(event) =>
                      setSettings((current) => ({
                        ...current,
                        context_window_tokens: Number(event.target.value),
                      }))
                    }
                    disabled={settingsSaving}
                    className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  />
                  <span className="mt-1 block text-[10px] leading-4 text-slate-400">
                    Это лимит всего запроса, а не только найденных документов. Агент резервирует около 20% для ответа,
                    ограничивает поиск и сокращает старую историю при необходимости. Оценка токенов приблизительная.
                  </span>
                </label>

                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-slate-700">API-адрес</span>
                  <input
                    type="url"
                    maxLength={2048}
                    value={settings.base_url}
                    onChange={(event) => setSettings((current) => ({ ...current, base_url: event.target.value }))}
                    placeholder="По умолчанию для OpenAI"
                    disabled={settingsSaving}
                    className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  />
                  <span className="mt-1 block text-[10px] leading-4 text-slate-400">
                    Для Ollama и LM Studio в Docker используйте host.docker.internal. В LM Studio укажите ID
                    загруженной модели.
                  </span>
                </label>

                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium text-slate-700">API-ключ</span>
                  <input
                    type="password"
                    autoComplete="new-password"
                    maxLength={4096}
                    value={settings.api_key}
                    onChange={(event) =>
                      setSettings((current) => ({
                        ...current,
                        api_key: event.target.value,
                        clear_api_key: false,
                      }))
                    }
                    placeholder={hasSavedApiKey ? "Ключ сохранён — введите новый, чтобы заменить" : "Введите API-ключ"}
                    disabled={settingsSaving || settings.clear_api_key}
                    className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50"
                  />
                  <span className="mt-1 block text-[10px] leading-4 text-slate-400">
                    Ключ хранится на сервере и не передаётся обратно в браузер.
                  </span>
                </label>

                {hasSavedApiKey && (
                  <label className="flex cursor-pointer items-center gap-2 text-[11px] text-slate-600">
                    <input
                      type="checkbox"
                      checked={settings.clear_api_key}
                      onChange={(event) =>
                        setSettings((current) => ({
                          ...current,
                          clear_api_key: event.target.checked,
                          api_key: "",
                        }))
                      }
                      disabled={settingsSaving}
                      className="h-3.5 w-3.5 rounded border-slate-300 accent-[#315fce]"
                    />
                    Удалить сохранённый ключ
                  </label>
                )}

                <div className="rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2.5 text-[10px] leading-[1.6] text-amber-800">
                  Эти настройки общие для сервера. API-ключ хранится в локальной базе данных без шифрования;
                  используйте приложение только в доверенной сети.
                </div>

                {settingsError && (
                  <div role="alert" className="rounded-lg border border-rose-100 bg-rose-50 px-3 py-2.5 text-[11px] text-rose-700">
                    {settingsError}
                  </div>
                )}
                {settingsSuccess && (
                  <div role="status" className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2.5 text-[11px] text-emerald-700">
                    {settingsSuccess}
                  </div>
                )}

                <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
                  <button
                    type="button"
                    disabled={settingsSaving}
                    onClick={() => setSettingsOpen(false)}
                    className="h-9 rounded-lg px-3.5 text-xs font-medium text-slate-600 transition hover:bg-slate-100 disabled:opacity-50"
                  >
                    Закрыть
                  </button>
                  <button
                    type="submit"
                    disabled={settingsSaving || settingsLoading}
                    className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#315fce] px-3.5 text-xs font-medium text-white transition hover:bg-[#244eaf] disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {settingsSaving ? <LoaderCircle size={14} className="animate-spin" /> : <Save size={14} />}
                    Сохранить настройки
                  </button>
                </div>
              </form>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
