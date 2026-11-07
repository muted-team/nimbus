import { t, useLanguage } from "@/lib/i18n"
import { useRef } from "react"
import { create } from "zustand"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"

/* Подтверждение действия — свой диалог, одна разметка на приложение:
   const ok = await confirm({ title, confirmText, destructive }). Короткий
   заголовок-вопрос и, если есть что сказать, сводка «ключ — значение».
   Для необратимого фокус стоит на «Отмена»: двойной Enter ничего не удалит. */

export interface ConfirmOptions {
  title: string
  description?: React.ReactNode
  /** сводка: [подпись, значение] */
  details?: [string, React.ReactNode][]
  confirmText: string
  cancelText?: string
  destructive?: boolean
  /** куда поставить фокус; по умолчанию у необратимого — «Отмена» */
  focus?: "confirm" | "cancel"
}

interface ConfirmState {
  current: (ConfirmOptions & { resolve: (ok: boolean) => void }) | null
  open: boolean
}

const useConfirmStore = create<ConfirmState>(() => ({ current: null, open: false }))

export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    useConfirmStore.getState().current?.resolve(false)
    useConfirmStore.setState({ current: { ...options, resolve }, open: true })
  })
}

/** Необратимое (удалить, очистить, остановить): красная кнопка, фокус на «Отмена».
    То же, что confirm({ …, destructive: true }), только без повтора флага. */
export const confirmDestructive = (options: Omit<ConfirmOptions, "destructive">) =>
  confirm({ ...options, destructive: true })

function close(ok: boolean) {
  const { current } = useConfirmStore.getState()
  current?.resolve(ok)
  useConfirmStore.setState({ open: false })
}

export function ConfirmHost() {
  useLanguage()
  const { current, open } = useConfirmStore()
  const cancelRef = useRef<HTMLButtonElement>(null)
  const confirmRef = useRef<HTMLButtonElement>(null)
  if (!current) return null

  const focusCancel = (current.focus ?? (current.destructive ? "cancel" : "confirm")) === "cancel"

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close(false)
      }}
      onOpenChangeComplete={(next) => {
        if (!next) useConfirmStore.setState({ current: null })
      }}
    >
      <AlertDialogContent initialFocus={focusCancel ? cancelRef : confirmRef} className="sm:max-w-md">
        <AlertDialogHeader>
          <AlertDialogTitle>{current.title}</AlertDialogTitle>
          {current.description ? (
            <AlertDialogDescription>{current.description}</AlertDialogDescription>
          ) : null}
        </AlertDialogHeader>
        {current.details?.length ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            {current.details.map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="tabular text-right">{value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel ref={cancelRef}>{current.cancelText ?? t("Отмена")}</AlertDialogCancel>
          <AlertDialogAction
            ref={confirmRef}
            variant={current.destructive ? "destructive" : "default"}
            onClick={() => close(true)}
          >
            {current.confirmText}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
