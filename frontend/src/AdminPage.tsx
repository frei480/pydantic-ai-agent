import {
  ArrowLeft,
  Bot,
  Check,
  FileText,
  KeyRound,
  LoaderCircle,
  LogOut,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

type Prompts = {
  researcher: string;
  delegation: string;
  critic: string;
  writer: string;
};

type SubAgent = {
  name: string;
  description: string;
  instructions: string;
  skills_enabled: boolean;
};

type AgentConfig = {
  prompts: Prompts;
  subagents: SubAgent[];
};

type Skill = {
  name: string;
  description: string;
};

type SkillDocument = Skill & { content: string };
type Section = "prompts" | "skills" | "subagents";

const promptFields: { key: keyof Prompts; title: string; description: string }[] = [
  {
    key: "researcher",
    title: "Исследователь",
    description: "Основные инструкции агента, который ищет и проверяет сведения в документации.",
  },
  {
    key: "delegation",
    title: "Делегирование",
    description: "Правила выбора субагентов и передачи им исследовательских задач.",
  },
  {
    key: "critic",
    title: "Критик",
    description: "Инструкции для проверки полноты и достаточности собранных фактов.",
  },
  {
    key: "writer",
    title: "Писатель",
    description: "Инструкции для подготовки итогового ответа пользователю.",
  },
];

const sectionTitles: Record<Section, string> = {
  prompts: "Промпты",
  skills: "Навыки",
  subagents: "Субагенты",
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function adminApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (init?.method && init.method !== "GET") {
    headers.set("X-Admin-Request", "1");
  }
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string | { msg?: string }[] };
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map((item) => item.msg || "Некорректное значение").join("; ");
      }
    } catch {
      // Keep the HTTP status when the server does not return JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function skillTemplate(name: string): string {
  return `---\nname: ${name}\ndescription: Кратко опишите, когда следует применять этот навык.\n---\n\n# ${name}\n\nОпишите порядок действий и важные ограничения.\n`;
}

function AdminPage() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [section, setSection] = useState<Section>("prompts");
  const [password, setPassword] = useState("");
  const [selectedSkill, setSelectedSkill] = useState("");
  const [skillDocument, setSkillDocument] = useState<SkillDocument | null>(null);
  const [newSkillName, setNewSkillName] = useState("");
  const [isNewSkill, setIsNewSkill] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadAdminData = async () => {
    const [savedConfig, savedSkills] = await Promise.all([
      adminApi<AgentConfig>("/api/admin/config"),
      adminApi<Skill[]>("/api/admin/skills"),
    ]);
    setConfig(savedConfig);
    setSkills(savedSkills);
    setSelectedSkill((current) => current || savedSkills[0]?.name || "");
    setAuthenticated(true);
  };

  useEffect(() => {
    void adminApi<unknown>("/api/admin/session")
      .then(() => loadAdminData())
      .catch((loadError: unknown) => {
        const message = errorText(loadError);
        if (!message.includes("Требуется вход администратора")) setError(message);
        setAuthenticated(false);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedSkill || isNewSkill || !authenticated) return;
    void adminApi<SkillDocument>(`/api/admin/skills/${encodeURIComponent(selectedSkill)}`)
      .then(setSkillDocument)
      .catch((loadError: unknown) => setError(`Не удалось загрузить навык: ${errorText(loadError)}`));
  }, [selectedSkill, isNewSkill, authenticated]);

  const login = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await adminApi("/api/admin/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setPassword("");
      await loadAdminData();
    } catch (loginError) {
      setError(errorText(loginError));
    } finally {
      setSaving(false);
      setLoading(false);
    }
  };

  const logout = async () => {
    try {
      await adminApi("/api/admin/logout", { method: "POST" });
    } catch (logoutError) {
      setError(`Не удалось завершить сеанс: ${errorText(logoutError)}`);
    } finally {
      setAuthenticated(false);
      setConfig(null);
      setSkills([]);
    }
  };

  const saveConfig = async (event: FormEvent) => {
    event.preventDefault();
    if (!config) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await adminApi<AgentConfig>("/api/admin/config", {
        method: "PUT",
        body: JSON.stringify(config),
      });
      setConfig(saved);
      setNotice("Изменения сохранены и применяются к новым запросам.");
    } catch (saveError) {
      setError(`Не удалось сохранить: ${errorText(saveError)}`);
    } finally {
      setSaving(false);
    }
  };

  const selectNewSkill = () => {
    const normalized = newSkillName
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    setNewSkillName(normalized);
    setSelectedSkill(normalized);
    setIsNewSkill(true);
    setSkillDocument({
      name: normalized,
      description: "",
      content: skillTemplate(normalized || "new-skill"),
    });
    setError("");
    setNotice("");
  };

  const saveSkill = async () => {
    if (!skillDocument || !selectedSkill) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const saved = await adminApi<SkillDocument>(
        `/api/admin/skills/${encodeURIComponent(selectedSkill)}`,
        {
          method: isNewSkill ? "POST" : "PUT",
          body: JSON.stringify({ content: skillDocument.content }),
        },
      );
      setSkillDocument(saved);
      setIsNewSkill(false);
      setSkills(await adminApi<Skill[]>("/api/admin/skills"));
      setNotice("Навык сохранён; новые запросы уже могут его использовать.");
    } catch (saveError) {
      setError(`Не удалось сохранить навык: ${errorText(saveError)}`);
    } finally {
      setSaving(false);
    }
  };

  const deleteSkill = async () => {
    if (!selectedSkill || isNewSkill || !window.confirm(`Удалить навык «${selectedSkill}»?`)) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await adminApi(`/api/admin/skills/${encodeURIComponent(selectedSkill)}`, { method: "DELETE" });
      const remaining = await adminApi<Skill[]>("/api/admin/skills");
      setSkills(remaining);
      setSelectedSkill(remaining[0]?.name || "");
      setSkillDocument(null);
      setNotice("Навык удалён.");
    } catch (deleteError) {
      setError(`Не удалось удалить навык: ${errorText(deleteError)}`);
    } finally {
      setSaving(false);
    }
  };

  if (loading || authenticated === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        <LoaderCircle className="mr-2 animate-spin" size={17} /> Проверка доступа…
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
        <form onSubmit={(event) => void login(event)} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-7 shadow-sm">
          <a href="/" className="mb-7 inline-flex items-center gap-2 text-xs text-slate-500 hover:text-blue-700">
            <ArrowLeft size={15} /> Вернуться в чат
          </a>
          <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
            <ShieldCheck size={21} />
          </div>
          <h1 className="text-xl font-semibold text-slate-900">Администрирование</h1>
          <p className="mt-2 text-sm leading-6 text-slate-500">Введите пароль администратора для управления инструкциями агента.</p>
          <label className="mt-6 block">
            <span className="mb-1.5 block text-xs font-medium text-slate-700">Пароль</span>
            <span className="relative block">
              <KeyRound size={15} className="absolute top-3 left-3 text-slate-400" />
              <input
                autoFocus
                required
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="h-10 w-full rounded-lg border border-slate-200 pr-3 pl-9 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </span>
          </label>
          {error && <div role="alert" className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</div>}
          <button
            type="submit"
            disabled={saving}
            className="mt-5 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-[#315fce] text-sm font-medium text-white hover:bg-[#244eaf] disabled:opacity-60"
          >
            {saving ? <LoaderCircle size={15} className="animate-spin" /> : <KeyRound size={15} />}
            Войти
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-[#f8f9fb] text-slate-800 lg:h-screen lg:flex-row lg:overflow-hidden">
      <aside className="flex shrink-0 flex-col border-b border-slate-200 bg-white lg:w-64 lg:border-r lg:border-b-0">
        <div className="flex h-[72px] items-center gap-3 border-b border-slate-100 px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-50 text-blue-700"><ShieldCheck size={19} /></div>
          <div>
            <div className="text-sm font-semibold">Администрирование</div>
            <div className="text-[11px] text-slate-400">Настройки AI-агента</div>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto p-3 lg:flex-col" aria-label="Разделы админки">
          {(["prompts", "skills", "subagents"] as Section[]).map((item) => {
            const Icon = item === "prompts" ? FileText : item === "skills" ? Check : Bot;
            return (
              <button
                key={item}
                type="button"
                onClick={() => { setSection(item); setError(""); setNotice(""); }}
                className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm ${section === item ? "bg-blue-50 font-medium text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}
              >
                <Icon size={16} /> {sectionTitles[item]}
              </button>
            );
          })}
        </nav>
        <div className="mt-auto hidden border-t border-slate-100 p-4 lg:block">
          <a href="/" className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-500 hover:bg-slate-50 hover:text-blue-700">
            <ArrowLeft size={14} /> Вернуться в чат
          </a>
          <button type="button" onClick={() => void logout()} className="mt-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-slate-500 hover:bg-slate-50 hover:text-rose-600">
            <LogOut size={14} /> Выйти
          </button>
        </div>
      </aside>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-[72px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-5 sm:px-8">
          <div>
            <h1 className="text-base font-semibold">{sectionTitles[section]}</h1>
            <p className="mt-1 text-[11px] text-slate-400">Изменения автоматически применяются к новым запросам.</p>
          </div>
          <div className="flex gap-2 lg:hidden">
            <a href="/" aria-label="Вернуться в чат" className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><ArrowLeft size={17} /></a>
            <button type="button" aria-label="Выйти" onClick={() => void logout()} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><LogOut size={17} /></button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-8">
          <div className="mx-auto max-w-5xl">
            {error && <div role="alert" className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</div>}
            {notice && <div role="status" className="mb-4 flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700"><Check size={16} />{notice}</div>}

            {section === "prompts" && config && (
              <form onSubmit={(event) => void saveConfig(event)} className="space-y-4">
                {promptFields.map(({ key, title, description }) => (
                  <label key={key} className="block rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
                    <span className="block text-sm font-semibold text-slate-800">{title}</span>
                    <span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span>
                    <textarea
                      required
                      value={config.prompts[key]}
                      onChange={(event) => setConfig({ ...config, prompts: { ...config.prompts, [key]: event.target.value } })}
                      rows={key === "researcher" ? 22 : 10}
                      className="mt-3 w-full resize-y rounded-lg border border-slate-200 bg-slate-50/50 p-3 font-mono text-xs leading-5 text-slate-700 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    />
                  </label>
                ))}
                <div className="flex justify-end">
                  <button disabled={saving} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#315fce] px-4 text-sm font-medium text-white hover:bg-[#244eaf] disabled:opacity-60">
                    {saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />} Сохранить промпты
                  </button>
                </div>
              </form>
            )}

            {section === "subagents" && config && (
              <form onSubmit={(event) => void saveConfig(event)} className="space-y-4">
                {config.subagents.map((subagent, index) => (
                  <section key={`${subagent.name}-${index}`} className="rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
                    <div className="mb-4 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-sm font-semibold"><Bot size={16} className="text-blue-600" /> Субагент {index + 1}</div>
                      <button type="button" onClick={() => setConfig({ ...config, subagents: config.subagents.filter((_, itemIndex) => itemIndex !== index) })} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-rose-600 hover:bg-rose-50">
                        <Trash2 size={14} /> Удалить
                      </button>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="block">
                        <span className="mb-1 block text-xs font-medium">ID (латиница, цифры, _)</span>
                        <input required pattern="[a-z][a-z0-9_]{2,63}" value={subagent.name} onChange={(event) => setConfig({ ...config, subagents: config.subagents.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) })} className="h-9 w-full rounded-lg border border-slate-200 px-3 font-mono text-xs outline-none focus:border-blue-400" />
                      </label>
                      <label className="flex items-center gap-2 self-end pb-2 text-xs text-slate-600">
                        <input type="checkbox" checked={subagent.skills_enabled} onChange={(event) => setConfig({ ...config, subagents: config.subagents.map((item, itemIndex) => itemIndex === index ? { ...item, skills_enabled: event.target.checked } : item) })} className="accent-blue-600" />
                        Доступ к навыкам
                      </label>
                    </div>
                    <label className="mt-3 block">
                      <span className="mb-1 block text-xs font-medium">Описание для исследователя</span>
                      <input required value={subagent.description} onChange={(event) => setConfig({ ...config, subagents: config.subagents.map((item, itemIndex) => itemIndex === index ? { ...item, description: event.target.value } : item) })} className="h-9 w-full rounded-lg border border-slate-200 px-3 text-xs outline-none focus:border-blue-400" />
                    </label>
                    <label className="mt-3 block">
                      <span className="mb-1 block text-xs font-medium">Инструкции субагента</span>
                      <textarea required rows={10} value={subagent.instructions} onChange={(event) => setConfig({ ...config, subagents: config.subagents.map((item, itemIndex) => itemIndex === index ? { ...item, instructions: event.target.value } : item) })} className="w-full resize-y rounded-lg border border-slate-200 bg-slate-50/50 p-3 font-mono text-xs leading-5 outline-none focus:border-blue-400" />
                    </label>
                  </section>
                ))}
                <div className="flex flex-wrap justify-between gap-2">
                  <button type="button" onClick={() => { let suffix = config.subagents.length + 1; let name = `new_researcher_${suffix}`; while (config.subagents.some((item) => item.name === name)) { suffix += 1; name = `new_researcher_${suffix}`; } setConfig({ ...config, subagents: [...config.subagents, { name, description: "Опишите специализацию субагента", instructions: "Опишите задачу, границы поиска и формат возвращаемых фактов.", skills_enabled: true }] }); }} className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 text-sm text-slate-700 hover:bg-slate-50">
                    <Plus size={15} /> Добавить субагента
                  </button>
                  <button disabled={saving || config.subagents.length === 0} className="inline-flex h-10 items-center gap-2 rounded-lg bg-[#315fce] px-4 text-sm font-medium text-white hover:bg-[#244eaf] disabled:opacity-60">
                    {saving ? <LoaderCircle size={15} className="animate-spin" /> : <Save size={15} />} Сохранить субагентов
                  </button>
                </div>
              </form>
            )}

            {section === "skills" && (
              <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
                <aside className="h-fit rounded-xl border border-slate-200 bg-white p-3">
                  <div className="mb-2 flex items-center justify-between px-1">
                    <span className="text-xs font-semibold text-slate-700">Навыки · {skills.length}</span>
                    <button type="button" aria-label="Создать навык" onClick={() => { setIsNewSkill(true); setSelectedSkill(""); setSkillDocument(null); setNewSkillName(""); setError(""); setNotice(""); }} className="rounded-md p-1.5 text-blue-700 hover:bg-blue-50"><Plus size={16} /></button>
                  </div>
                  <div className="max-h-[55vh] space-y-0.5 overflow-y-auto">
                    {skills.map((skill) => (
                      <button key={skill.name} type="button" onClick={() => { setIsNewSkill(false); setSelectedSkill(skill.name); setNotice(""); }} className={`block w-full rounded-lg px-2.5 py-2 text-left ${selectedSkill === skill.name && !isNewSkill ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-50"}`}>
                        <span className="block truncate text-xs font-medium">{skill.name}</span>
                        <span className="mt-0.5 block truncate text-[10px] text-slate-400">{skill.description}</span>
                      </button>
                    ))}
                  </div>
                </aside>

                <section className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
                  {!skillDocument && !isNewSkill ? (
                    <div className="py-12 text-center text-sm text-slate-400">Выберите навык или создайте новый.</div>
                  ) : isNewSkill && !skillDocument ? (
                    <form onSubmit={(event) => { event.preventDefault(); selectNewSkill(); }} className="max-w-md">
                      <h2 className="text-sm font-semibold">Новый навык</h2>
                      <label className="mt-4 block">
                        <span className="mb-1 block text-xs font-medium">ID навыка (kebab-case)</span>
                        <input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={newSkillName} onChange={(event) => setNewSkillName(event.target.value)} placeholder="my-custom-skill" className="h-9 w-full rounded-lg border border-slate-200 px-3 font-mono text-xs outline-none focus:border-blue-400" />
                      </label>
                      <button className="mt-4 inline-flex h-9 items-center gap-2 rounded-lg bg-[#315fce] px-3 text-xs font-medium text-white"><Plus size={14} /> Продолжить</button>
                    </form>
                  ) : skillDocument ? (
                    <>
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <h2 className="text-sm font-semibold">{isNewSkill ? "Создание навыка" : skillDocument.name}</h2>
                          <p className="mt-1 text-[11px] text-slate-400">Редактируйте Markdown вместе с YAML frontmatter.</p>
                        </div>
                        <div className="flex gap-2">
                          {!isNewSkill && <button type="button" disabled={saving} onClick={() => void deleteSkill()} className="inline-flex h-9 items-center gap-1 rounded-lg border border-rose-200 px-3 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-50"><Trash2 size={14} /> Удалить</button>}
                          <button type="button" disabled={saving} onClick={() => void saveSkill()} className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#315fce] px-3 text-xs font-medium text-white hover:bg-[#244eaf] disabled:opacity-50">
                            {saving ? <LoaderCircle size={14} className="animate-spin" /> : <Save size={14} />} Сохранить
                          </button>
                        </div>
                      </div>
                      <textarea spellCheck={false} rows={25} value={skillDocument.content} onChange={(event) => setSkillDocument({ ...skillDocument, content: event.target.value })} className="w-full resize-y rounded-lg border border-slate-200 bg-slate-50/50 p-3 font-mono text-xs leading-5 outline-none focus:border-blue-400" />
                    </>
                  ) : null}
                </section>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default AdminPage;
