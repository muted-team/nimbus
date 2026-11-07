import { useQuery } from "@tanstack/react-query"

import { api } from "./client"
import { keys, queryClient } from "./query-client"
import type {
  AuthState,
  Changelog,
  MediaFile,
  MediaFolder,
  MediaLibrary,
  ServerCheck,
  Settings,
  SettingsPatch,
  SlotInfo,
  UniqPreviewResponse,
  UniqSettings,
} from "./types"

/* ── настройки ───────────────────────────────────────────────────────── */

export function useSettings() {
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api.get<Settings>("api/settings"),
    // их может поменять другой браузер или правка config.json
    staleTime: 0,
    refetchOnMount: "always",
    refetchInterval: (query) => query.state.data?.phone.active ? 3000 : false,
  })
}

export async function saveSettings(patch: SettingsPatch) {
  const res = await api.put<Settings>("api/settings", patch)
  queryClient.setQueryData(keys.settings, res)
  return res
}

/** Доступен ли наш сервер по текущему адресу — при каждом заходе в раздел. */
export function useServerCheck() {
  return useQuery({
    queryKey: keys.serverCheck,
    queryFn: () => api.get<ServerCheck>("api/server/check"),
    staleTime: 0,
    refetchOnMount: "always",
    retry: false,
  })
}

/** Адрес поменялся — проверить заново. */
export const recheckServer = () => queryClient.invalidateQueries({ queryKey: keys.serverCheck })

/* ── вход по паролю (сервер, открытый по ссылке) ─────────────────────── */

export const getAuth = () => api.get<AuthState>("api/auth")
export const signIn = (password: string) => api.post<{ ok: boolean }>("api/auth", { password })
export const signOut = () => api.post<{ ok: boolean }>("api/auth/logout", {})

/* ── история изменений ───────────────────────────────────────────────── */

export function useChangelog() {
  return useQuery({
    queryKey: keys.changelog,
    queryFn: () => api.get<Changelog>("api/changelog"),
    staleTime: Infinity,
  })
}

/* ── уникализатор ────────────────────────────────────────────────────── */

export function useUniq() {
  return useQuery({
    queryKey: keys.uniq,
    queryFn: () => api.get<UniqSettings>("api/uniq"),
    staleTime: Infinity,
  })
}

/** Ответ кладём в кэш: экран читает настройки оттуда и при следующем открытии
    должен увидеть записанное, а не то, что пришло при первой загрузке. */
export async function saveUniq(patch: Partial<UniqSettings>) {
  const res = await api.put<UniqSettings>("api/uniq", patch)
  queryClient.setQueryData(keys.uniq, res)
  return res
}

export const previewUniq = (folders: string[], settings?: UniqSettings) =>
  api.post<UniqPreviewResponse>("api/uniq/preview", { folders, settings }, { timeout: 60_000 })

/* ── папки с фото и видео ────────────────────────────────────────────── */

/* Запрос чисел по папкам один на всех: и реактивный хук строк формы, и разовый
   счёт перед запуском берут его отсюда — ключ и форма данных в кэше совпадают. */
const slotInfoQuery = (folders: string[]) => ({
  queryKey: keys.slots(folders),
  queryFn: async () => {
    const res = await api.post<{ items: SlotInfo[] }>("api/slots", { folders })
    return new Map(res.items.map((it) => [it.path, it]))
  },
  staleTime: 10_000,
})

export function useSlotInfo(folders: string[]) {
  return useQuery({
    ...slotInfoQuery(folders),
    enabled: folders.length > 0,
    // правят путь — счётчик фото не мигает прочерком, пока идёт запрос
    placeholderData: (prev: Map<string, SlotInfo> | undefined) => prev,
  })
}

/** Числа по папкам сейчас, без ожидания рендера; свежий кэш сети не трогает. */
export const fetchSlotInfo = (folders: string[]) => queryClient.fetchQuery(slotInfoQuery(folders))

/* После загрузки помечаем «устарели» только показанные сейчас наборы папок:
   invalidateQueries перепрашивает одни активные запросы (а активный набор в
   дереве один — `useSlotInfo` зовётся из одного места), но полный префикс
   `keys.slotsRoot` заодно пометил бы устаревшими и наборы из кэша без экрана,
   которым это ни к чему. Ни один не показан — обновляем все. */
export const refreshSlotInfo = () => {
  const shown = queryClient.getQueryCache().findAll({ queryKey: keys.slotsRoot, type: "active" })
  if (!shown.length) return queryClient.invalidateQueries({ queryKey: keys.slotsRoot })
  return Promise.all(
    shown.map((query) => queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true }))
  )
}

/* ── папки программы ─────────────────────────────────────────────────── */

export function useMediaLibrary() {
  return useQuery({
    queryKey: keys.media,
    queryFn: () => api.get<MediaLibrary>("api/media"),
    staleTime: 10_000,
  })
}

export const refreshMedia = () => {
  // и список папок, и файлы любой из них: ключи файлов начинаются с keys.media
  void queryClient.invalidateQueries({ queryKey: keys.media })
  void refreshSlotInfo()
}

/** Новая папка программы; пустое имя — `fallback` (например, «Галерея 25.09 14-32»). */
export async function createMediaFolder(name: string, fallback = "") {
  const folder = await api.post<MediaFolder>("api/media", { name, default: fallback })
  refreshMedia()
  return folder
}

export async function clearMediaFolder(name: string) {
  const res = await api.post<{ ok: boolean; removed: number }>("api/media/clear", { name })
  refreshMedia()
  return res
}

export async function deleteMediaFolder(name: string) {
  await api.post<{ ok: boolean }>("api/media/delete", { name })
  refreshMedia()
}

/** Фото и видео папки программы, свежие сверху. */
export function useMediaFiles(name: string | null) {
  return useQuery({
    queryKey: keys.mediaFiles(name ?? ""),
    queryFn: async () => (await api.get<{ files: MediaFile[] }>(`api/media/files?name=${encodeURIComponent(name!)}`)).files,
    enabled: !!name,
  })
}

/** Превью фото; время правки в адресе — чтобы браузерный кэш не отдал старое. */
export const mediaThumbUrl = (name: string, file: Pick<MediaFile, "file" | "mtime">) =>
  `api/media/thumb?name=${encodeURIComponent(name)}&file=${encodeURIComponent(file.file)}&v=${file.mtime}`

export async function removeMediaFile(name: string, file: string) {
  await api.post<{ ok: boolean }>("api/media/remove-file", { name, file })
  refreshMedia()
}

/* Срок на один файл — по его весу: минута на запрос плюс время на передачу
   при 64 КБ/с (медленный Wi-Fi телефона). Прежние 30 минут на любой файл
   превращали один зависший ответ в вечный прогресс — следующие файлы стояли
   за ним и не уходили. */
const uploadTimeout = (bytes: number) => 60_000 + Math.ceil(bytes / 64)

/** Один файл — один запрос: сервер не держит в памяти всю пачку. */
export const uploadToFolder = (folder: string, file: File) =>
  api.upload<{ ok: boolean; photos: number; videos: number }>(
    `api/slots/upload?folder=${encodeURIComponent(folder)}&name=${encodeURIComponent(file.name)}`,
    file,
    { timeout: uploadTimeout(file.size) }
  )
