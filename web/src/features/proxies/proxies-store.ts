import { create } from "zustand"

import { checkProxies, saveProxies } from "@/api/proxies"
import type { ProxiesResponse } from "@/api/types"
import { notify } from "@/lib/notify"

import { PROXIES_TOAST } from "./labels"

/* Список живёт таблицей — правки строк (правка, удаление, добавление) уходят
   на сервер сразу, явным действием человека, а не черновиком поля, который
   надо было бы держать синхронным с сервером между кликами. Это само по себе
   убирает почву под старым багом T-201 (`dev/_probe_proxy_wipe.py`): там
   пустой текст улетал сам, потому что автосохранение слало значение своего
   последнего рендера, а рендер и сервер были не синхронны. Здесь сервер и
   экран рассинхронизироваться не успевают — каждое действие берёт актуальный
   список и сразу шлёт его целиком.

   Осознанно перенесённая часть защиты — ниже, в proxiesTextToSave: пустой
   список всё равно не должен улетать сам по себе, только по явному «удалить
   последнюю строку». */

interface ProxiesStore {
  /** идёт общая проверка списка («Проверить сейчас») */
  checking: boolean
  /** когда раздел сам звал проверку, мс эпохи; null — ещё не звал */
  autoCheckedAt: number | null
}

export const useProxiesStore = create<ProxiesStore>(() => ({
  checking: false,
  autoCheckedAt: null,
}))

/** Текст, который уйдёт на сервер, или null — сохранять не нужно вовсе.
    Пустой список превращается в текст только когда его прислало явное
    действие человека «удалить последнюю строку» (allowEmpty): случайно
    посчитанная где-то по пути пустота до сервера просто не доходит (T-201). */
export function proxiesTextToSave(lines: string[], allowEmpty: boolean): string | null {
  if (!lines.length && !allowEmpty) return null
  return lines.join("\n")
}

/** После удаления строки отметки правее неё сдвигаются на один индекс, сама
    удалённая отметка исчезает. Нужен для обеих групп и «выключена». */
export function indexesAfterRemoval(indexes: number[], removed: number): number[] {
  return indexes.filter((i) => i !== removed).map((i) => (i > removed ? i - 1 : i))
}

/** Сохранить список строк целиком. allowEmpty — только у «удалить последнюю
    строку»: без него пустой результат тихо не уходит (см. proxiesTextToSave).
    null — сохранять не пришлось (список и так пуст, действие не явное). */
export async function saveProxiesLines(
  lines: string[],
  {
    allowEmpty = false,
    login,
    publish,
    off,
  }: { allowEmpty?: boolean; login?: number[]; publish?: number[]; off?: number[] } = {}
): Promise<ProxiesResponse | null> {
  const text = proxiesTextToSave(lines, allowEmpty)
  if (text === null) return null
  return saveProxies({ text, login, publish, off })
}

/** «Проверить сейчас» и авто-проверка при открытии раздела: список к этому
    моменту уже лежит на сервере (каждая правка строки сохраняется сама, ждать
    здесь нечего) — достаточно самой проверки. silent — так проверяет раздел
    сам при открытии: человек её не просил, и сбой сети не должен встречать
    его тостом ошибки. */
export async function checkProxiesNow({ silent = false }: { silent?: boolean } = {}) {
  if (useProxiesStore.getState().checking) return
  useProxiesStore.setState({ checking: true })
  try {
    await checkProxies()
  } catch (error) {
    if (!silent) notify.error(error, PROXIES_TOAST.notChecked)
  } finally {
    useProxiesStore.setState({ checking: false })
  }
}
