import assert from "node:assert/strict";
import test from "node:test";
import { modelsCountLabel, visibleModels } from "../../frontend/src/modelFilter.ts";

const models = ["Qwen/Qwen2.5-7B-Instruct", "gpt-4o-mini", "gpt-4o", "qwen2.5:7b"];
const shownFor = (query: string) => visibleModels(models, query).shown;

test("пустой запрос — все модели в прежнем порядке", () => {
  assert.deepEqual(visibleModels(models, ""), { shown: models, hiddenCount: 0 });
});

test("подстрока без учёта регистра; пробелы по краям не мешают", () => {
  assert.deepEqual(shownFor("GPT"), ["gpt-4o-mini", "gpt-4o"]);
  // совпадение в середине и в конце названия, а не только в начале
  assert.deepEqual(shownFor("7b"), ["Qwen/Qwen2.5-7B-Instruct", "qwen2.5:7b"]);
  assert.deepEqual(shownFor("mini"), ["gpt-4o-mini"]);
  assert.deepEqual(shownFor("  gpt-4o "), ["gpt-4o-mini", "gpt-4o"]);
  assert.deepEqual(shownFor("клод"), []);
});

test("показываются первые 50 совпадений, остальные считаются", () => {
  const many = Array.from(
    { length: 120 },
    (_, index) => `model-${String(index).padStart(3, "0")}`
  );
  const all = visibleModels(many, "");
  assert.equal(all.shown.length, 50);
  assert.equal(all.shown[0], "model-000");
  assert.equal(all.shown[49], "model-049");
  assert.equal(all.hiddenCount, 70);
  // лимит применяется к совпадениям, а не к списку до поиска
  assert.deepEqual(visibleModels(many, "model-11"), {
    shown: [
      "model-110",
      "model-111",
      "model-112",
      "model-113",
      "model-114",
      "model-115",
      "model-116",
      "model-117",
      "model-118",
      "model-119",
    ],
    hiddenCount: 0,
  });
});

test("число согласуется со словом", () => {
  assert.equal(modelsCountLabel(0), "0 моделей");
  assert.equal(modelsCountLabel(1), "1 модель");
  assert.equal(modelsCountLabel(2), "2 модели");
  assert.equal(modelsCountLabel(4), "4 модели");
  assert.equal(modelsCountLabel(5), "5 моделей");
  assert.equal(modelsCountLabel(11), "11 моделей");
  assert.equal(modelsCountLabel(21), "21 модель");
  assert.equal(modelsCountLabel(111), "111 моделей");
});
