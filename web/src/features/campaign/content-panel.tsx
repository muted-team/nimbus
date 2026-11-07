import { useEffect, useRef, useState } from "react"
import { FolderIcon, FolderOpenIcon, FolderPlusIcon, ImagesIcon, PlusIcon, Trash2Icon, UploadIcon } from "lucide-react"

import { useAccounts } from "@/api/accounts"
import { createMediaFolder, useMediaLibrary } from "@/api/misc"
import type { Creatives, MediaKind, SlotInfo } from "@/api/types"
import { Panel } from "@/components/panel"
import { SimpleSelect } from "@/components/simple-select"
import { UploadStatus } from "@/components/upload-status"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Field, FieldError, FieldGroup, FieldLabel as Label } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { t, useLanguage } from "@/lib/i18n"

import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { useFolderUpload, type FolderUpload } from "@/hooks/use-folder-upload"
import { cn } from "@/lib/utils"
import { hasNativeWindow, onNativeReady, pickFolder } from "@/lib/native"
import { notify } from "@/lib/notify"
import { LIB_LABEL, LIB_TOAST } from "@/features/media/labels"
import { NewFolderDialog } from "@/features/media/new-folder-dialog"

import { checkForm, shownCreatives } from "./form-model"
import { updateForm, useFormStore } from "./form-store"
import {
  CAPTION_MAX,
  CREATIVES_LABEL,
  FOLDER_LABEL,
  FORM_LABEL,
  MEDIA_LABEL,
  SHORTAGE_LABEL,
  SLOT_LABEL,
  TITLE_MAX,
  TOAST,
  UPLOAD_ACCEPT,
} from "./labels"
import { findShortage, slotFileCount, type SlotShortage } from "./shortage"
import { useSlotFiles } from "./slot-files"


/* Контент публикации: фото или видео, папки-источники, текст поста.

   Папка бывает двух видов. Своя — любой путь на компьютере с программой: в
   окне его выбирают системным «Обзором», по ссылке вписывают. Папка программы
   — из «Креативов» (media/ рядом с программой): её выбирают по имени, и это
   путь для телефона, где ни «Обзора», ни чужого диска нет. «Добавить из
   галереи» — в одно касание: папка с датой, файлы в неё, папка — сразу в
   публикацию; «Загрузить» в «Креативах» только заводит папку в библиотеку, без
   публикации, — поэтому подписи у кнопок разные. Чистят и удаляют папки
   программы в «Креативах», здесь их выбирают. */

interface SlotRowProps {
  index: number
  path: string
  /** имя папки программы; null — своя папка */
  library: string | null
  media: MediaKind
  info?: SlotInfo
  /** файлов в этой папке не хватит на проход (см. shortage.ts) */
  short?: SlotShortage
  /** идёт загрузка в эту папку */
  upload: FolderUpload | null
  /** системный «Обзор» есть только в окне программы */
  native: boolean
  /** любая загрузка уже идёт */
  locked: boolean
  focusFolder?: boolean
  errorId?: string
  onChange: (path: string) => void
  onRemove: () => void
  onBrowse: () => void
  onUpload: () => void
}

function slotCountText(
  info: SlotInfo | undefined,
  media: MediaKind,
  upload: FolderUpload | null
): { text: string; bad: boolean } | null {
  if (upload) return { text: SLOT_LABEL.uploading(upload.done, upload.total), bad: false }
  if (!info) return null
  if (!info.exists) return { text: SLOT_LABEL.missing, bad: true }
  const n = slotFileCount(info, media)
  return { text: media === "video" ? SLOT_LABEL.videos(n) : SLOT_LABEL.photos(n), bad: false }
}

function SlotRow(props: SlotRowProps) {
  const { index, path, library, media, info, short, upload, native, focusFolder } = props
  const count = slotCountText(info, media, upload)
  const placeholder = native
    ? media === "video"
      ? "C:\\video"
      : "C:\\slots\\1"
    : media === "video"
      ? "assets/video"
      : "assets/1"
  // в папку программы грузят всегда, в свою — только там, где нет «Обзора»
  const canUpload = library !== null || !native

  const name = library ?? path.trim().replace(/[\\/]+$/, "").split(/[\\/]/).pop()

  return (
    <FieldGroup className="min-w-0 gap-2 grid grid-cols-[minmax(0,1fr)_auto] items-center" data-slot-row={index}>
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex min-w-0 items-center gap-2">
          <FolderIcon className="size-4 shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-sm" title={path}>
            {media === "photo" ? `${index + 1}. ` : ""}{name || FORM_LABEL.folderPath}
          </span>
        </div>
        <span className={cn("text-xs", count?.bad ? "text-destructive" : "text-muted-foreground")}>
          {count?.text ?? "—"}
        </span>
      </div>
      {library === null ? (
        <Input
          className="col-span-2 row-start-2"
          value={path}
          onChange={(e) => props.onChange(e.target.value)}
          placeholder={placeholder}
          aria-label={media === "photo" ? SHORTAGE_LABEL.folder(media, index) : FORM_LABEL.folders.video}
          aria-invalid={props.errorId ? true : undefined}
          aria-describedby={props.errorId}
          title={path}
          spellCheck={false}
          autoComplete="off"
          data-field={focusFolder ? "folders" : undefined}
        />
      ) : null}
      <div className="flex min-w-0 items-center justify-between gap-3 col-start-2 row-start-1">
        <div className="flex shrink-0 items-center gap-1">
          {native && library === null ? (
            <Button variant="outline" size="icon" aria-label={FORM_LABEL.browse} title={FORM_LABEL.browse} onClick={props.onBrowse}>
              <FolderOpenIcon />
            </Button>
          ) : null}
          {canUpload ? (
            <Button variant="outline" size="icon" aria-label={FORM_LABEL.upload} title={FORM_LABEL.upload} onClick={props.onUpload} disabled={props.locked}>
              <UploadIcon />
            </Button>
          ) : null}
          <Button variant="ghost" size="icon" aria-label={FORM_LABEL.removeFolder} title={FORM_LABEL.removeFolder} onClick={props.onRemove}>
            <Trash2Icon />
          </Button>
        </div>
      </div>
      {short ? <p className="text-xs text-destructive col-span-2">{SHORTAGE_LABEL.row(media, short.need, short.have)}</p> : null}
    </FieldGroup>
  )
}

export function ContentPanel() {
  useLanguage()
  const values = useFormStore((s) => s.values)!
  const showErrors = useFormStore((s) => s.showErrors)
  const pendingFocus = useFormStore((s) => s.pendingFocus)
  useEffect(() => {
    if (!pendingFocus || !checkForm(values).errors.folders) return
    document.querySelector<HTMLElement>('input[data-field="folders"],button[data-field="folders"]')?.focus()
    useFormStore.setState({ pendingFocus: false })
  }, [pendingFocus, values])
  const folderError = showErrors ? checkForm(values).errors.folders : undefined
  const video = values.media === "video"
  const slots = video ? values.videoSlots : values.photoSlots

  const [native, setNative] = useState(hasNativeWindow)
  useEffect(() => onNativeReady(() => setNative(true)), [])

  // файлов в папках может не хватить на проход: считаем по форме и по числу
  // аккаунтов, которые пойдут с запуска «по всем»
  const info = useSlotFiles()
  const accounts = useAccounts().data?.accounts.length
  const shortOf = new Map(findShortage(values, info, accounts).map((s) => [s.index, s]))

  const library = useMediaLibrary().data
  const [newOpen, setNewOpen] = useState(false)

  const { state: upload, upload: uploadFiles } = useFolderUpload()
  const fileInput = useRef<HTMLInputElement>(null)
  const galleryInput = useRef<HTMLInputElement>(null)
  const uploadIdx = useRef(-1)
  const listRef = useRef<HTMLDivElement>(null)

  /** Имя папки программы по пути в форме; null — своя папка. */
  function libraryName(path: string): string | null {
    const root = library?.root
    const p = path.trim()
    if (!root || p.length <= root.length + 1) return null
    const sep = p.charAt(root.length)
    return p.startsWith(root) && (sep === "\\" || sep === "/") ? p.slice(root.length + 1) : null
  }

  /** Текущие папки формы — из стора, а не из замыкания рендера: между
      созданием папки и её добавлением форма могла поменяться. */
  function currentSlots(): string[] {
    const v = useFormStore.getState().values!
    return v.media === "video" ? v.videoSlots : v.photoSlots
  }

  function setSlots(next: string[]) {
    updateForm(video ? { videoSlots: next } : { photoSlots: next })
  }

  function setSlot(index: number, path: string) {
    const next = [...slots]
    next[index] = path
    setSlots(next)
  }

  /** Папку — в публикацию: у фото в конец, у видео папка одна — вместо прежней. */
  function addSlot(path: string) {
    setSlots(video ? [path] : [...currentSlots(), path])
  }

  async function browse(index: number) {
    const path = await pickFolder()
    if (path) setSlot(index, path)
  }

  async function addOwnFolder() {
    if (native) {
      const path = await pickFolder()
      if (path) addSlot(path)
      return
    }
    addSlot("")
    requestAnimationFrame(() => {
      const inputs = listRef.current?.querySelectorAll<HTMLInputElement>("input")
      inputs?.[inputs.length - 1]?.focus()
    })
  }

  function uploadInto(index: number, files: File[]) {
    const folder = slots[index]?.trim()
    if (!folder) {
      notify.warn(TOAST.noFolder)
      return
    }
    void uploadFiles(folder, files)
  }

  /** «Из галереи»: папка программы с датой, файлы в неё, папка — в публикацию. */
  async function fromGallery(files: File[]) {
    let folder
    try {
      folder = await createMediaFolder("", LIB_LABEL.gallery(new Date()))
    } catch (error) {
      notify.error(error, LIB_TOAST.notCreated)
      return
    }
    addSlot(folder.path)
    await uploadFiles(folder.path, files)
  }

  // в списке «Добавить папку» — папки программы, которых в публикации ещё нет
  const inForm = new Set(slots.map((s) => s.trim()))
  const offered = (library?.folders ?? []).filter((f) => !inForm.has(f.path))
  const canAdd = !video || slots.length === 0
  const creativesItems = (Object.entries(CREATIVES_LABEL[values.media]) as [Creatives, string][]).map(
    ([value, label]) => ({ value, label })
  )

  return (
    <Panel title={t("Для публикации")}>
      <FieldGroup className="gap-4">
      {upload ? <UploadStatus done={upload.done} total={upload.total} /> : null}

      <ToggleGroup
        value={[values.media]}
        onValueChange={(group) => {
          const next = group[0]
          if (next && next !== values.media) updateForm({ media: next as MediaKind })
        }}
        aria-label={FORM_LABEL.content}
      >
        {(["photo", "video"] as MediaKind[]).map((kind) => (
          <ToggleGroupItem key={kind} value={kind}>
            {MEDIA_LABEL[kind]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <Field data-invalid={!!folderError}>
        <Label>{FORM_LABEL.folders[values.media]}</Label>
        <FieldGroup ref={listRef} className="min-w-0 gap-4">
          {slots.map((path, index) => (
            <SlotRow
              key={`${values.media}-${index}`}
              index={index}
              path={path}
              library={libraryName(path)}
              media={values.media}
              info={info?.get(path.trim())}
              short={shortOf.get(index)}
              upload={upload && upload.target === path.trim() ? upload : null}
              native={native}
              locked={upload !== null}
              focusFolder={index === 0}
              errorId={folderError ? "camp-folders-error" : undefined}
              onChange={(next) => setSlot(index, next)}
              onRemove={() => setSlots(slots.filter((_, i) => i !== index))}
              onBrowse={() => void browse(index)}
              onUpload={() => {
                uploadIdx.current = index
                fileInput.current?.click()
              }}
            />
          ))}
        </FieldGroup>
        <div className="flex flex-wrap items-center gap-2">
          {canAdd ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={<Button variant="outline" />}
                disabled={upload !== null}
                data-field="folders"
                aria-invalid={folderError ? true : undefined}
                aria-describedby={folderError ? "camp-folders-error" : undefined}
              >
                <PlusIcon data-icon="inline-start" />
                {FORM_LABEL.addFolder}
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="max-h-80 min-w-56 max-w-[calc(100vw-2rem)]">
                <DropdownMenuGroup>
                  <DropdownMenuLabel>{FOLDER_LABEL.library}</DropdownMenuLabel>
                  {offered.length ? (
                    offered.map((f) => (
                      <DropdownMenuItem key={f.path} onClick={() => addSlot(f.path)}>
                        <FolderIcon />
                        <span className="min-w-0 flex-1 truncate">{f.name}</span>
                        <span className="text-xs text-muted-foreground tabular">
                          {FOLDER_LABEL.count(f.photos, f.videos, values.media)}
                        </span>
                      </DropdownMenuItem>
                    ))
                  ) : (
                    <DropdownMenuItem disabled>{LIB_LABEL.empty}</DropdownMenuItem>
                  )}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                <DropdownMenuItem onClick={() => setNewOpen(true)}>
                  <FolderPlusIcon />
                  {LIB_LABEL.newFolder}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => void addOwnFolder()}>
                  <FolderOpenIcon />
                  {FOLDER_LABEL.own}
                </DropdownMenuItem>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : null}
          <Button variant="outline" onClick={() => galleryInput.current?.click()} disabled={upload !== null}>
            <ImagesIcon data-icon="inline-start" />
            {FOLDER_LABEL.fromGallery}
          </Button>
        </div>
        {folderError ? <FieldError id="camp-folders-error" className="text-xs">{folderError}</FieldError> : null}
      </Field>

      <Field className="min-w-0 max-w-sm">
        <Label>{FORM_LABEL.creatives}</Label>
        <SimpleSelect
          aria-label={FORM_LABEL.creatives}
          value={shownCreatives(values.media, values.creatives)}
          items={creativesItems}
          onValueChange={(creatives) => updateForm({ creatives })}
        />
      </Field>

      {!video ? (
        <Field>
          <div className="flex items-baseline justify-between">
            <Label htmlFor="camp-title">{FORM_LABEL.title}</Label>
            <span className="text-xs tabular text-muted-foreground">
              {values.title.length}/{TITLE_MAX}
            </span>
          </div>
          <Input
            id="camp-title"
            value={values.title}
            onChange={(e) => updateForm({ title: e.target.value })}
            maxLength={TITLE_MAX}
          />
        </Field>
      ) : null}

      <Field>
        <div className="flex items-baseline justify-between">
          <Label htmlFor="camp-caption">{FORM_LABEL.caption}</Label>
          <span className="text-xs tabular text-muted-foreground">
            {values.caption.length}/{CAPTION_MAX}
          </span>
        </div>
        <Textarea
          id="camp-caption"
          rows={4}
          value={values.caption}
          onChange={(e) => updateForm({ caption: e.target.value })}
          maxLength={CAPTION_MAX}
          className="max-h-40 overflow-y-auto"
        />
      </Field>

      </FieldGroup>
      <NewFolderDialog open={newOpen} onOpenChange={setNewOpen} onCreated={(f) => addSlot(f.path)} />

      <input
        ref={fileInput}
        type="file"
        multiple
        hidden
        accept={UPLOAD_ACCEPT[values.media]}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ""
          if (files.length && uploadIdx.current >= 0) uploadInto(uploadIdx.current, files)
        }}
      />
      <input
        ref={galleryInput}
        type="file"
        multiple
        hidden
        accept={UPLOAD_ACCEPT[values.media]}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          e.target.value = ""
          if (files.length) void fromGallery(files)
        }}
      />
    </Panel>
  )
}
