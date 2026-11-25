import { LoaderCircle, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type ReactElement } from "react";
import { modelsCountLabel, visibleModels } from "./modelFilter";

export type ModelListStatus = "idle" | "loading" | "ready" | "error";

type Props = {
  id: string;
  value: string;
  onChange: (value: string) => void; // каждое изменение текста
  options: readonly string[];
  status: ModelListStatus;
  error?: string; // причина при status === "error"
  onRefresh: () => void;
  disabled?: boolean;
};

const inputClass =
  "h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50";

/**
 * Поле «Модель»: свободный текст и выпадающий список моделей с поиском по подстроке.
 *
 * При входе в поле виден весь список; после изменения текста — только совпадения.
 * Выбранный пункт заполняет поле. Название, которого нет в списке, остаётся как введено.
 */
export function ModelCombobox({
  id,
  value,
  onChange,
  options,
  status,
  error = "",
  onRefresh,
  disabled = false,
}: Props): ReactElement {
  const [open, setOpen] = useState(false);
  const [edited, setEdited] = useState(false);
  const [highlighted, setHighlighted] = useState(-1); // -1 — ничего не подсвечено
  const listRef = useRef<HTMLUListElement>(null);
  const listId = `${id}-listbox`;
  const statusId = `${id}-status`;

  const { shown, hiddenCount } = visibleModels(options, edited ? value : "");
  const listVisible = open && status === "ready" && (shown.length > 0 || edited);
  // подсветка не выходит за пределы списка, даже если он стал короче
  const active = highlighted < 0 || shown.length === 0 ? -1 : Math.min(highlighted, shown.length - 1);

  const close = () => {
    setOpen(false);
    setEdited(false);
  };
  const pick = (model: string) => {
    onChange(model);
    close();
  };
  // Вход в поле: показываем весь список. Нужен и клик — после выбора пункта поле
  // остаётся в фокусе, и повторный клик события focus не вызовет.
  const showAll = () => {
    setOpen(true);
    setEdited(false);
    setHighlighted(-1);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      if (shown.length === 0) return;
      const forward = event.key === "ArrowDown";
      // без подсветки ↓ ведёт к первому пункту, ↑ — к последнему; дальше — по кругу
      setHighlighted((index) =>
        index < 0 ? (forward ? 0 : shown.length - 1) : (index + (forward ? 1 : shown.length - 1)) % shown.length
      );
    } else if (event.key === "Enter" && listVisible && active >= 0) {
      // выбран подсвеченный пункт — форму не отправляем
      event.preventDefault();
      pick(shown[active]);
    } else if (event.key === "Escape" && listVisible) {
      // закрываем только список: обработчик подложки диалога не должен получить Esc
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  };

  useEffect(() => {
    if (!listVisible || active < 0) return;
    listRef.current?.querySelectorAll('[role="option"]')[active]?.scrollIntoView({ block: "nearest" });
  }, [active, listVisible]);

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-slate-700">
        Модель
      </label>
      <div className="relative">
        <div className="flex gap-2">
          <input
            id={id}
            type="text"
            role="combobox"
            aria-expanded={listVisible}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-describedby={statusId}
            aria-activedescendant={listVisible && active >= 0 ? `${id}-option-${active}` : undefined}
            required
            maxLength={200}
            autoComplete="off"
            value={value}
            placeholder="Введите название или выберите из списка"
            disabled={disabled}
            onChange={(event) => {
              onChange(event.target.value);
              setEdited(true);
              setOpen(true);
              setHighlighted(-1);
            }}
            onFocus={showAll}
            onClick={showAll}
            onBlur={close}
            onKeyDown={onKeyDown}
            className={`${inputClass} min-w-0 flex-1`}
          />
          <button
            type="button"
            onClick={onRefresh}
            disabled={disabled || status === "loading"}
            className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-100 disabled:opacity-50"
          >
            {status === "loading" ? (
              <LoaderCircle size={14} className="animate-spin" />
            ) : (
              <RefreshCw size={14} />
            )}
            Обновить список
          </button>
        </div>
        {listVisible && (
          <ul
            id={listId}
            role="listbox"
            ref={listRef}
            className="absolute left-0 right-0 top-full z-10 mt-1 max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-[0_12px_32px_rgba(15,23,42,0.16)]"
          >
            {shown.map((model, index) => (
              <li
                key={model}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                // фокус остаётся в поле: иначе blur закроет список раньше клика
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setHighlighted(index)}
                onClick={() => pick(model)}
                className={`cursor-pointer px-3 py-2 text-xs ${
                  index === active ? "bg-blue-50 text-[#315fce]" : "text-slate-800"
                }`}
              >
                {model}
              </li>
            ))}
            {shown.length === 0 && (
              <li className="px-3 py-2 text-[11px] text-slate-400">
                Совпадений нет — можно оставить введённое название
              </li>
            )}
            {hiddenCount > 0 && (
              <li className="pointer-events-none px-3 py-2 text-[10px] text-slate-400">
                Ещё {modelsCountLabel(hiddenCount)} — уточните запрос
              </li>
            )}
          </ul>
        )}
      </div>
      <p
        id={statusId}
        className={`mt-1 text-[10px] leading-4 ${status === "error" ? "text-amber-700" : "text-slate-400"}`}
      >
        {status === "idle" && "Нажмите «Обновить список», чтобы получить модели провайдера"}
        {status === "loading" && "Загружаю список моделей…"}
        {status === "ready" &&
          (options.length > 0
            ? `Доступно моделей: ${options.length}`
            : "Провайдер не вернул ни одной модели. Название можно ввести вручную.")}
        {status === "error" && `Не удалось получить список моделей: ${error}`}
      </p>
    </div>
  );
}
