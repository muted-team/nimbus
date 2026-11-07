import { copyWithToast } from "@/lib/native"

import { COPY_LABEL } from "./labels"

/* Юзернейм на экране и в буфере — всегда с собакой: так он выглядит в TikTok,
   и так его принимает поиск. Без собаки скопированный столбик никуда не
   вставишь.

   В буфер уходят только юзернеймы: пароли, коды 2FA и почты рядом с ними не
   попадают. */

export const atUsername = (username: string) => `@${username}`

/* Выделенные в порядке строк списка: сперва видимые, следом скрытые срезом
   или поиском. Скрытые тоже идут в буфер: счётчик панели и соседние действия
   берут всё выделение, и буфер обязан говорить про то же множество — иначе
   после смены среза копируется меньше обещанного, а выделенный единственный
   скрытый не копируется вовсе. В конец — потому что видимые строки человек
   видит на экране, и порядок им есть откуда взять. */
export function selectedUsernames(
  selected: Iterable<string>,
  visible: string[],
  all: string[]
): string[] {
  const picked = new Set(selected)
  const shown = new Set(visible)
  return [
    ...visible.filter((u) => picked.has(u)),
    ...all.filter((u) => picked.has(u) && !shown.has(u)),
  ]
}

/** Столбик юзернеймов — по одному в строке, в переданном порядке. */
export const usernamesText = (usernames: string[]) => usernames.map(atUsername).join("\n")

/** Копирует юзернеймы и подтверждает тостом: буфера человек не видит, а
    молчание после нажатия читается как сбой. */
export async function copyUsernames(usernames: string[]): Promise<void> {
  await copyWithToast(
    usernamesText(usernames),
    usernames.length === 1 ? COPY_LABEL.toastOne : COPY_LABEL.toastMany(usernames.length)
  )
}
