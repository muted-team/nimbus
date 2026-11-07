/* Заголовок шага формы: номер в кружке и название. Форма читается сверху
   вниз как порядок работы: что публикуем, как обработать, с какими
   параметрами. */

export function StepTitle({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-normal text-muted-foreground tabular">
        {n}
      </span>
      <span className="truncate">{children}</span>
    </span>
  )
}
