import { useState } from "react"
import { cn } from "@/lib/utils"

/* Флаг страны картинкой, а не эмодзи.

   Эмодзи-флаг (`🇺🇸`) в окне программы НЕ работает: pywebview на Windows рисует
   движком WebView2, тот берёт системный Segoe UI Emoji, а флагов стран в нём
   нет — вместо флага видны те же две буквы в рамке. Проверено в самом окне
   (`dev/_probe_webview_flags.py`). В Firefox флаги видны только потому, что он
   несёт собственный шрифт эмодзи, — на окно программы это не распространяется.

   Поэтому картинки: `web/public/flags/<код>.svg`, 271 страна, набор ISO из
   flag-icons. Лежат в public/ и отдаются сервером из ui/ по абсолютному пути —
   он не зависит от того, в каком разделе сейчас пользователь.

   Пропорции 4:3 — как у исходных файлов; тонкая рамка нужна белым флагам
   (Япония, Швейцария), иначе они сливаются с фоном строки. */

/** Код страны -> имя файла. Код приходит от TikTok заглавными («US»). */
function src(code: string): string {
  return `/flags/${code.toLowerCase()}.svg`
}

export function Flag({ code, className }: { code: string | null | undefined; className?: string }) {
  const [broken, setBroken] = useState(false)

  // страну ещё не знаем — прочерк, как у пустых значений в таблицах
  if (!code) return <span className={cn("text-muted-foreground", className)}>—</span>

  // файла на такой код нет: показываем сам код, чтобы строка не стала пустой
  if (broken) return <span className={cn("tabular-nums", className)}>{code}</span>

  return (
    <img
      src={src(code)}
      alt={code}
      width={24}
      height={18}
      loading="lazy"
      onError={() => setBroken(true)}
      className={cn("inline-block h-[18px] w-6 rounded-[2px] ring-1 ring-border/60", className)}
    />
  )
}
