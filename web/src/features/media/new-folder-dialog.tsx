import { useLanguage } from "@/lib/i18n"
import { useState } from "react"

import { createMediaFolder } from "@/api/misc"
import type { MediaFolder } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Field } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { notify } from "@/lib/notify"

import { LIB_LABEL, LIB_TOAST } from "./labels"

/* Новая папка программы: имя и «Создать». Имя не ввели — «Папка 25.09 14-32»;
   занято — сервер добавит номер. */
export function NewFolderDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated: (folder: MediaFolder) => void
}) {
  useLanguage()
  const [name, setName] = useState("")
  const [busy, setBusy] = useState(false)
  // Имя по умолчанию должно отражать время открытия диалога.
  // oxlint-disable-next-line react/purity
  const fallback = LIB_LABEL.dated(new Date())

  async function create() {
    setBusy(true)
    try {
      const folder = await createMediaFolder(name.trim(), fallback)
      setName("")
      onOpenChange(false)
      onCreated(folder)
    } catch (error) {
      notify.error(error, LIB_TOAST.notCreated)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{LIB_LABEL.newFolder}</DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            void create()
          }}
        >
          <Field>
            <Label htmlFor="new-folder-name">{LIB_LABEL.name}</Label>
            <Input
              id="new-folder-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={fallback}
              maxLength={60}
              autoComplete="off"
              autoFocus
            />
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              {busy ? <Spinner /> : null}
              {LIB_LABEL.create}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
