import { localize } from "@/lib/i18n"
import { Component, type ReactNode } from "react"
import { RotateCcwIcon, TriangleAlertIcon } from "lucide-react"

import { StateView } from "@/components/state-view"
import { Button } from "@/components/ui/button"

/* Перехват падения отрисовки. Без него ошибка в одном месте (пункт меню,
   строка таблицы) гасит всё окно до чёрного экрана. С ним ломается только
   этот кусок: экран показывает «Что-то сломалось» и «Перезагрузить», а
   меню и остальные разделы работают. Ключ снаружи (адрес экрана) сбрасывает
   перехват при переходе в другой раздел. */

const TEXT = localize({
  title: "Что-то сломалось",
  reload: "Перезагрузить",
} as const)

export class ErrorBoundary extends Component<
  { children: ReactNode; /** что показать вместо упавшего; без него — экран с кнопкой */ fallback?: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error(error)
  }

  render() {
    if (!this.state.error) return this.props.children
    if (this.props.fallback !== undefined) return this.props.fallback
    return (
      <StateView
        icon={TriangleAlertIcon}
        tone="error"
        title={TEXT.title}
        text={this.state.error.message}
        className="py-16"
        action={
          <Button variant="outline" size="sm" onClick={() => location.reload()}>
            <RotateCcwIcon />
            {TEXT.reload}
          </Button>
        }
      />
    )
  }
}
