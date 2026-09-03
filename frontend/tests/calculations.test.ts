import assert from "node:assert/strict";
import test from "node:test";
import { allocatePercentages, calculateRanking, equalPercentages, rebalancePercentages } from "../src/calculations.ts";

test("equal and rounded allocations always total exactly 100", () => {
  assert.deepEqual(equalPercentages(["a", "b", "c"]), { a: 34, b: 33, c: 33 });
  assert.deepEqual(allocatePercentages({ a: 1, b: 1, c: 1 }, ["a", "b", "c"]), { a: 34, b: 33, c: 33 });
});

test("changed weight is fixed and the remainder is proportionally redistributed", () => {
  const next = rebalancePercentages({ a: 50, b: 30, c: 20 }, ["a", "b", "c"], "a", 70);
  assert.deepEqual(next, { a: 70, b: 18, c: 12 });
  assert.equal(Object.values(next).reduce((sum, value) => sum + value, 0), 100);
});

test("zero remainder weights use deterministic key order", () => {
  assert.deepEqual(rebalancePercentages({ a: 100, b: 0, c: 0 }, ["a", "b", "c"], "a", 50), { a: 50, b: 25, c: 25 });
  assert.deepEqual(rebalancePercentages({ only: 1 }, ["only"], "only", 1), { only: 100 });
});

test("ranking uses the same weighted average and option-order tie break as backend", () => {
  const scores = { A: { quality: 5, cost: 1 }, B: { quality: 1, cost: 5 } };
  assert.equal(calculateRanking(["A", "B"], ["quality", "cost"], scores, { quality: 50, cost: 50 })[0].option, "A");
  assert.equal(calculateRanking(["A", "B"], ["quality", "cost"], scores, { quality: 40, cost: 60 })[0].option, "B");
});
