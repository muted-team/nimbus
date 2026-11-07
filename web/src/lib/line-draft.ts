/* Ответ относится только к отправленной части. Более новый ввод остаётся
   в поле; изменённую строку старый ответ не трогает. Номера ошибок считаются
   относительно оставшихся строк, а не уже удалённой принятой части. */
export function remainingLineDraft<T extends { line: number }>(
  sent: string,
  latest: string,
  errors: T[]
): { text: string; errors: T[]; retained: string } {
  if (!latest.startsWith(sent)) return { text: latest, errors: [], retained: "" }
  let tail = latest.slice(sent.length)
  if (tail && !sent.endsWith("\n")) {
    if (!/^\r?\n/.test(tail)) return { text: latest, errors: [], retained: "" }
    tail = tail.replace(/^\r?\n/, "")
  }

  const byLine = new Map(errors.map((error) => [error.line, error]))
  const lines: string[] = []
  const remainingErrors: T[] = []
  sent.split(/\r?\n/).forEach((line, i) => {
    const error = byLine.get(i + 1)
    if (!error || !line.trim()) return
    lines.push(line)
    remainingErrors.push({ ...error, line: lines.length })
  })

  const keep = lines.join("\n")
  const retained = keep && tail ? `${keep}\n` : keep
  return { text: retained + tail, errors: remainingErrors, retained }
}
