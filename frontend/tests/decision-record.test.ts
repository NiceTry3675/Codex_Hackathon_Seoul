import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_ROOM_CODE, mockApi } from "../src/mock.ts";

test("mock decision record becomes available after saving and can be fetched again", async () => {
  await mockApi.createRoom({
    question: "어떤 도구를 만들까요?",
    options: ["A", "B"],
    criteria: ["가치", "실행 가능성"],
  });

  await assert.rejects(mockApi.getDecisionRecord(DEFAULT_ROOM_CODE), /decision record not found/);

  const saved = await mockApi.createDecisionRecord(DEFAULT_ROOM_CODE, {
    final_choice: "A",
    final_reason: "팀이 합의한 이유",
  });
  const fetched = await mockApi.getDecisionRecord(DEFAULT_ROOM_CODE);

  assert.equal(fetched.final_choice, saved.final_choice);
  assert.equal(fetched.final_reason, saved.final_reason);
});