import { Panel } from "@/components/panel"
import { Label } from "@/components/ui/label"

/* Настройки одной колонкой групп: подпись слева, поле справа, строки группы
   разделены чертой — как FieldSet в shadcn. Три карточки на два-три поля
   каждая читались как три разных экрана. */

export function SettingsGroup({
  title,
  meta,
  children,
}: {
  title: string
  meta?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Panel title={title} meta={meta} flush>
      <div className="divide-y">{children}</div>
    </Panel>
  )
}

export function SettingRow({
  label,
  htmlFor,
  children,
}: {
  label: React.ReactNode
  htmlFor?: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-2 px-4 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:items-center sm:gap-4">
      {htmlFor ? (
        <Label htmlFor={htmlFor} className="text-muted-foreground">
          {label}
        </Label>
      ) : (
        <span className="text-sm text-muted-foreground">{label}</span>
      )}
      <div className="flex min-w-0 flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}
