/** Deterministic integer-percentage allocation shared by input and simulation UI. */
export function allocatePercentages(
  values: Record<string, number>,
  keys: string[],
  total = 100,
  minimum = 1,
): Record<string, number> {
  if (keys.length === 0) return {};
  if (keys.length * minimum > total) throw new Error("minimum allocation exceeds total");

  const budget = total - keys.length * minimum;
  const safe = keys.map((key) => Math.max(0, Number.isFinite(values[key]) ? values[key] : 0));
  const valueTotal = safe.reduce((sum, value) => sum + value, 0);
  const shares = valueTotal > 0
    ? safe.map((value) => (value / valueTotal) * budget)
    : safe.map(() => budget / keys.length);
  const floors = shares.map((value) => Math.floor(value));
  let remainder = budget - floors.reduce((sum, value) => sum + value, 0);
  const order = shares
    .map((value, index) => ({ index, fraction: value - floors[index] }))
    .sort((left, right) => right.fraction - left.fraction || left.index - right.index);
  for (let index = 0; index < remainder; index += 1) floors[order[index].index] += 1;

  return Object.fromEntries(keys.map((key, index) => [key, floors[index] + minimum]));
}

export function equalPercentages(keys: string[]): Record<string, number> {
  return allocatePercentages(Object.fromEntries(keys.map((key) => [key, 1])), keys);
}

export function rebalancePercentages(
  current: Record<string, number>,
  keys: string[],
  changedKey: string,
  requestedValue: number,
): Record<string, number> {
  if (!keys.includes(changedKey)) throw new Error("changed key is not present");
  if (keys.length === 1) return { [changedKey]: 100 };

  const minimum = 1;
  const maximum = 100 - minimum * (keys.length - 1);
  const changedValue = Math.max(minimum, Math.min(maximum, Math.round(requestedValue)));
  const otherKeys = keys.filter((key) => key !== changedKey);
  const others = allocatePercentages(current, otherKeys, 100 - changedValue, minimum);
  return Object.fromEntries(keys.map((key) => [key, key === changedKey ? changedValue : others[key]]));
}

export function calculateRanking(
  options: string[],
  criteria: string[],
  meanScores: Record<string, Record<string, number>>,
  percentages: Record<string, number>,
) {
  return options
    .map((option, optionIndex) => ({
      option,
      optionIndex,
      score: criteria.reduce(
        (sum, criterion) => sum + (meanScores[option]?.[criterion] ?? 0) * (percentages[criterion] ?? 0) / 100,
        0,
      ),
    }))
    .sort((left, right) => right.score - left.score || left.optionIndex - right.optionIndex);
}
