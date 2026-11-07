import { t, useLanguage } from "@/lib/i18n"
import { useEffect, useRef, useState } from "react"
import {
  ChevronRightIcon,
  EllipsisIcon,
  EraserIcon,
  FilmIcon,
  FolderIcon,
  FolderPlusIcon,
  Trash2Icon,
  UploadIcon,
  XIcon,
} from "lucide-react"
import { useLocation, useParams } from "wouter"
import { useCampaignForm } from "@/api/campaign"
import { ContentPanel } from "@/features/campaign/content-panel"
import { hydrateForm, updateForm, useFormAutosave, useFormStore } from "@/features/campaign/form-store"
import { ProcessingPanel } from "@/features/campaign/processing-panel"
import { Panel } from "@/components/panel"

import {
  clearMediaFolder,
  createMediaFolder,
  deleteMediaFolder,
  mediaThumbUrl,
  removeMediaFile,
  useMediaFiles,
  useMediaLibrary,
} from "@/api/misc"
import type { MediaFile, MediaFolder } from "@/api/types"
import { sectionPath, sectionTitle } from "@/app/sections"
import { confirmDestructive } from "@/components/confirm"
import { IconButton } from "@/components/hint"
import { Page, PageBody, PageHeader } from "@/components/page"
import { ErrorView, LoadingRows, QueryView } from "@/components/state-view"
import { UploadStatus } from "@/components/upload-status"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { UniqView } from "@/features/uniq/uniq-view"
import { UNIQ_TITLE } from "@/features/uniq/labels"
import { useFolderUpload } from "@/hooks/use-folder-upload"
import { useHotkey } from "@/hooks/use-hotkey"
import { notify } from "@/lib/notify"
import { cn } from "@/lib/utils"

import { LIB_LABEL, LIB_TOAST } from "./labels"
import { NewFolderDialog } from "./new-folder-dialog"

/* Креативы — единое место для папок, выбора контента и обработки.
   Библиотека и форма публикации используют один стор с автосохранением;
   второй вкладкой — параметры уникализации и превью.

   Открытая папка и вкладка живут в адресе (/media/f/<папка>, /media/uniq):
   «Назад» браузера и Esc ведут обратно к списку. «Загрузить» кладёт файлы
   туда, где стоишь: в открытую папку или в новую с датой. Файлы можно и
   перетащить в окно — туда же. */

/** Что принимает загрузка: фото и видео, в том числе форматы айфона. */
const ACCEPT = "image/*,video/*,.heic,.heif,.avif,.mp4,.mov,.m4v,.webm,.mkv,.avi"

const BASE = sectionPath("media")
const folderPath = (name: string) => `${BASE}/f/${encodeURIComponent(name)}`
const UNIQ_PATH = `${BASE}/uniq`

type Tab = "folders" | "uniq"

export default function MediaPage() {
  useLanguage()
  const form = useCampaignForm()
  const values = useFormStore((s) => s.values)
  useEffect(() => { if (form.data) hydrateForm(form.data) }, [form.data])
  useFormAutosave()
  const [, navigate] = useLocation()
  const rest = useParams<{ "*"?: string }>()["*"] ?? ""
  const tab: Tab = rest === "uniq" ? "uniq" : "folders"
  // Wouter уже декодировал обычные символы, включая %25. Повторный decode
  // ломал «50%» и превращал буквальное «%20» в пробел.
  const openName = rest.startsWith("f/") ? rest.slice(2) : null

  const query = useMediaLibrary()
  const [newOpen, setNewOpen] = useState(false)
  const { state: upload, upload: uploadFiles } = useFolderUpload()
  const input = useRef<HTMLInputElement>(null)

  const folders = query.data?.folders ?? []
  // decodeURI роутера оставляет зарезервированные символы (#, ?, /) в escape-виде.
  const open = openName ? (folders.find((f) => decodeURI(encodeURIComponent(f.name)) === openName) ?? null) : null
  const busy = upload !== null

  /* Папку удалили или переименовали снаружи — адрес ведёт в никуда, к списку.
     Пока список обновляется, не решаем: только что заведённой папки в
     старом списке ещё нет, и без этой проверки загрузка в новую папку
     выкидывала к списку папок. */
  useEffect(() => {
    if (openName && query.data && !query.isFetching && !open) navigate(BASE, { replace: true })
  }, [openName, open, query.data, query.isFetching, navigate])

  useHotkey("Escape", () => navigate(BASE), { enabled: !!openName, inInputs: false })

  /** Файлы — в открытую папку, а без неё — в новую с датой. */
  async function put(files: File[]) {
    let path = open?.path ?? null
    if (!path) {
      try {
        const folder = await createMediaFolder("", LIB_LABEL.gallery(new Date()))
        path = folder.path
        navigate(folderPath(folder.name))
      } catch (error) {
        notify.error(error, LIB_TOAST.notCreated)
        return
      }
    }
    await uploadFiles(path, files)
  }

  const dragging = useFileDrop(tab === "folders" && !busy, (files) => void put(files))

  return (
    <Page>
      <PageHeader
        title={sectionTitle("media")}
        toolbar={
          <Tabs value={tab} onValueChange={(v) => navigate(v === "uniq" ? UNIQ_PATH : BASE)} className="-mb-3">
            <TabsList>
              <TabsTrigger value="folders">{t("Контент")}</TabsTrigger>
              <TabsTrigger value="uniq">{t(UNIQ_TITLE)}</TabsTrigger>
            </TabsList>
          </Tabs>
        }
        actions={
          tab === "folders" ? (
            <>
              <Button variant="outline" aria-label={LIB_LABEL.newFolder} onClick={() => setNewOpen(true)} disabled={busy}>
                <FolderPlusIcon />
                <span className="hidden sm:inline">{LIB_LABEL.newFolder}</span>
              </Button>
              <Button onClick={() => input.current?.click()} disabled={busy}>
                <UploadIcon />
                {LIB_LABEL.upload}
              </Button>
            </>
          ) : null
        }
      />
      <PageBody width="full" className="max-w-[1440px]">
        {tab === "uniq" ? (
          <UniqView />
        ) : (
          <div className={cn("grid items-start gap-5", !open && "xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]")}>
            {!open ? <div className="flex min-w-0 flex-col gap-4">
              {values ? <><ContentPanel /><ProcessingPanel /></> :
                <Panel title={t("Для публикации")}>{form.isError ? <ErrorView error={form.error} onRetry={() => void form.refetch()} /> : <LoadingRows />}</Panel>}
            </div> : null}
            <Panel title={open ? open.name : t("Библиотека")}>
            {upload ? <UploadStatus done={upload.done} total={upload.total} /> : null}
            <QueryView query={query}>
              {() =>
                open ? (
                  <FolderView folder={open} busy={busy} />
                ) : folders.length ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {folders.map((f) => (
                      <FolderCard key={f.path} folder={f} busy={busy} onOpen={() => navigate(folderPath(f.name))} />
                    ))}
                  </div>
                ) : (
                  <Empty>
                    <EmptyHeader>
                      <EmptyMedia variant="icon">
                        <FolderIcon />
                      </EmptyMedia>
                      <EmptyTitle>{LIB_LABEL.empty}</EmptyTitle>
                    </EmptyHeader>
                    <Button variant="outline" onClick={() => input.current?.click()}>
                      <UploadIcon />
                      {LIB_LABEL.upload}
                    </Button>
                  </Empty>
                )
              }
            </QueryView>
            </Panel>
          </div>
        )}
      </PageBody>

      {dragging ? (
        <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-6 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3 rounded-xl border-2 border-dashed border-primary/60 px-12 py-10 text-center">
            <UploadIcon className="size-6 text-primary" />
            <span className="text-sm">{open ? LIB_LABEL.dropInto(open.name) : LIB_LABEL.dropNew}</span>
          </div>
        </div>
      ) : null}

      <NewFolderDialog open={newOpen} onOpenChange={setNewOpen} onCreated={(f) => navigate(folderPath(f.name))} />
      <input
        ref={input}
        type="file"
        multiple
        hidden
        accept={ACCEPT}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ""
          if (files.length) void put(files)
        }}
      />
    </Page>
  )
}

/* Файлы, перетащенные в окно. Счётчик входов нужен из-за дочерних
   элементов: dragleave приходит при переходе с родителя на ребёнка, и без
   счёта подложка мигала бы на каждом. */
function useFileDrop(enabled: boolean, onFiles: (files: File[]) => void) {
  const [dragging, setDragging] = useState(false)
  const handler = useRef(onFiles)
  useEffect(() => {
    handler.current = onFiles
  })
  useEffect(() => {
    if (!enabled) return
    let depth = 0
    const hasFiles = (e: DragEvent) => !!e.dataTransfer?.types.includes("Files")
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return
      depth += 1
      setDragging(true)
    }
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return
      depth = Math.max(0, depth - 1)
      if (!depth) setDragging(false)
    }
    const over = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault()
    }
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth = 0
      setDragging(false)
      const files = Array.from(e.dataTransfer?.files ?? [])
      if (files.length) handler.current(files)
    }
    window.addEventListener("dragenter", enter)
    window.addEventListener("dragleave", leave)
    window.addEventListener("dragover", over)
    window.addEventListener("drop", drop)
    return () => {
      window.removeEventListener("dragenter", enter)
      window.removeEventListener("dragleave", leave)
      window.removeEventListener("dragover", over)
      window.removeEventListener("drop", drop)
      setDragging(false)
    }
  }, [enabled])
  return dragging
}

/* ── папка: очистить, удалить ────────────────────────────────────────── */

async function clearFolder(name: string) {
  const ok = await confirmDestructive({
    title: LIB_LABEL.clearAsk(name),
    description: LIB_LABEL.clearDesc,
    confirmText: LIB_LABEL.clearYes,
  })
  if (!ok) return
  try {
    notify.ok(LIB_TOAST.cleared((await clearMediaFolder(name)).removed))
  } catch (error) {
    notify.error(error, LIB_TOAST.notCleared)
  }
}

async function deleteFolder(name: string) {
  const ok = await confirmDestructive({
    title: LIB_LABEL.removeAsk(name),
    description: LIB_LABEL.removeDesc,
    confirmText: LIB_LABEL.removeYes,
  })
  if (!ok) return
  try {
    await deleteMediaFolder(name)
    notify.ok(LIB_TOAST.removed)
  } catch (error) {
    notify.error(error, LIB_TOAST.notRemoved)
  }
}

function FolderMenu({ folder, busy }: { folder: MediaFolder; busy: boolean }) {
  useLanguage()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger render={<Button variant="ghost" size="icon-sm" aria-label={LIB_LABEL.more} />} disabled={busy}>
        <EllipsisIcon />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-44">
        <DropdownMenuGroup>
        <DropdownMenuItem onClick={() => void clearFolder(folder.name)}>
          <EraserIcon />
          {LIB_LABEL.clear}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onClick={() => void deleteFolder(folder.name)}>
          <Trash2Icon />
          {LIB_LABEL.remove}
        </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* ── карточка папки ──────────────────────────────────────────────────── */

function FolderCard({ folder, busy, onOpen }: { folder: MediaFolder; busy: boolean; onOpen: () => void }) {
  useLanguage()
  const values = useFormStore((s) => s.values)
  const slots = values ? (values.media === "video" ? values.videoSlots : values.photoSlots) : []
  const selected = slots.includes(folder.path)
  const toggle = () => {
    if (!values) return
    const next = selected ? slots.filter((p) => p !== folder.path) : values.media === "video" ? [folder.path] : [...slots.filter(Boolean), folder.path]
    updateForm(values.media === "video" ? { videoSlots: next } : { photoSlots: next })
  }
  return (
    <div className={cn("flex min-w-0 flex-col overflow-hidden rounded-xl border bg-card transition-colors", selected && "border-primary/50 bg-primary/5")}>
      {/* четыре плитки 3:4 — как фото для TikTok; фото нет — значок того, что есть */}
      <button
        type="button"
        onClick={onOpen}
        className="aspect-[3/1] bg-border outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {folder.preview.length ? (
          <div className="grid size-full grid-cols-4 gap-px">
            {Array.from({ length: 4 }, (_, i) => {
              const file = folder.preview[i]
              return (
                <div key={i} className="overflow-hidden bg-muted">
                  {file ? (
                    <img src={mediaThumbUrl(folder.name, file)} alt="" loading="lazy" className="size-full object-cover" />
                  ) : null}
                </div>
              )
            })}
          </div>
        ) : (
          <div className="flex size-full items-center justify-center bg-muted text-muted-foreground">
            {folder.videos ? <FilmIcon className="size-6" /> : <FolderIcon className="size-6" />}
          </div>
        )}
      </button>
      <div className="flex items-center gap-2 px-4 py-2">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left outline-none">
          <div className="truncate text-sm font-medium">{folder.name}</div>
          <div className="text-xs text-muted-foreground tabular">{LIB_LABEL.counts(folder.photos, folder.videos)}</div>
        </button>
        <FolderMenu folder={folder} busy={busy} />
      </div>
      <div className="px-4 pb-3">
        <Button className="w-full" size="sm" variant={selected ? "secondary" : "outline"} aria-pressed={selected} disabled={!values} onClick={toggle}>
          {selected ? t("Выбрана для публикации") : t("В публикацию")}
        </Button>
      </div>
    </div>
  )
}

/* ── открытая папка ──────────────────────────────────────────────────── */

/* Загрузка в открытую папку — кнопкой «Загрузить» в шапке раздела: она кладёт
   файлы туда, где стоишь, и второй такой же кнопки здесь не нужно. */
function FolderView({ folder, busy }: { folder: MediaFolder; busy: boolean }) {
  useLanguage()
  const [, navigate] = useLocation()
  const files = useMediaFiles(folder.name)
  /* Крестик удаляет файл с диска сразу, плитка прячется, не дожидаясь нового
     списка. Отложенное удаление с «Отменить» теряло файл при перезагрузке
     страницы: удаление не успевало уйти, и фото возвращалось. */
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const shown = (files.data ?? []).filter((f) => !hidden.has(f.file))

  async function remove(file: MediaFile) {
    const toggle = (on: boolean) =>
      setHidden((prev) => {
        const next = new Set(prev)
        if (on) next.add(file.file)
        else next.delete(file.file)
        return next
      })
    toggle(true)
    try {
      await removeMediaFile(folder.name, file.file)
    } catch (error) {
      toggle(false)
      notify.error(error, LIB_TOAST.notFileRemoved)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <nav aria-label={LIB_LABEL.path} className="flex min-w-0 flex-1 items-center gap-1 text-sm">
          <button
            type="button"
            onClick={() => navigate(BASE)}
            className="shrink-0 rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {LIB_LABEL.folders}
          </button>
          <ChevronRightIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium" aria-current="page">
            {folder.name}
          </span>
          <span className="ml-2 shrink-0 text-xs text-muted-foreground tabular">
            {LIB_LABEL.counts(folder.photos, folder.videos)}
          </span>
        </nav>
        <FolderMenu folder={folder} busy={busy} />
      </div>
      {files.isPending ? (
        <TileGrid>
          {Array.from({ length: 12 }, (_, i) => (
            <Skeleton key={i} className="aspect-[3/4] rounded-lg" />
          ))}
        </TileGrid>
      ) : files.isError ? (
        <ErrorView error={files.error} onRetry={() => void files.refetch()} />
      ) : !shown.length ? (
        <p className="text-sm text-muted-foreground">{LIB_LABEL.folderEmpty}</p>
      ) : (
        <TileGrid>
          {shown.map((file) => (
            <FileTile key={file.file} folder={folder.name} file={file} onRemove={() => void remove(file)} />
          ))}
        </TileGrid>
      )}
    </div>
  )
}

function TileGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-6">{children}</div>
}

function FileTile({ folder, file, onRemove }: { folder: string; file: MediaFile; onRemove: () => void }) {
  useLanguage()
  return (
    <div className="group relative aspect-[3/4] overflow-hidden rounded-lg bg-muted">
      {file.kind === "photo" ? (
        <img src={mediaThumbUrl(folder, file)} alt="" loading="lazy" className="size-full object-cover" />
      ) : (
        <div className="flex size-full flex-col items-center justify-center gap-1 p-2 text-muted-foreground">
          <FilmIcon className="size-6" />
          <span className="w-full truncate text-center text-xs">{file.file}</span>
        </div>
      )}
      <IconButton
        label={LIB_LABEL.removeFile}
        icon={XIcon}
        variant="secondary"
        size="icon-xs"
        className={cn("absolute top-1 right-1 opacity-90")}
        onClick={onRemove}
      />
    </div>
  )
}
