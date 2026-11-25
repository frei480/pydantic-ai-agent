const MODEL_LIST_RENDER_LIMIT = 50;

export type VisibleModels = { shown: string[]; hiddenCount: number };

/** Модели, содержащие запрос как подстроку (без учёта регистра), в прежнем порядке. */
function filterModels(models: readonly string[], query: string): string[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...models];
  return models.filter((model) => model.toLowerCase().includes(needle));
}

/** Первые MODEL_LIST_RENDER_LIMIT совпадений и сколько их скрыто за пределами списка. */
export function visibleModels(models: readonly string[], query: string): VisibleModels {
  const matches = filterModels(models, query);
  const shown = matches.slice(0, MODEL_LIST_RENDER_LIMIT);
  return { shown, hiddenCount: matches.length - shown.length };
}

/** «1 модель», «2 модели», «5 моделей» — форма слова по числу. */
export function modelsCountLabel(count: number): string {
  const tens = count % 10;
  const hundreds = count % 100;
  let form = "моделей";
  if (tens === 1 && hundreds !== 11) {
    form = "модель";
  } else if (tens >= 2 && tens <= 4 && (hundreds < 12 || hundreds > 14)) {
    form = "модели";
  }
  return `${count} ${form}`;
}
