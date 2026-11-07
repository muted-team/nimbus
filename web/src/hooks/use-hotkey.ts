import { useEffect, useRef } from "react"

/* Горячие клавиши по физической клавише (event.code): Ctrl+A работает и на
   русской раскладке. Сочетание — строка вида "Mod+Enter", "Alt+1", "Delete",
   "Shift+ArrowDown"; Mod — Ctrl, на macOS — Cmd. */

export interface HotkeyOptions {
  enabled?: boolean
  /** срабатывать и в поле ввода (по умолчанию — нет, кроме сочетаний с Mod) */
  inInputs?: boolean
  preventDefault?: boolean
  /** слушать на элементе, а не на всём окне */
  target?: React.RefObject<HTMLElement | null>
}

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)

const KEY_CODES: Record<string, string> = {
  enter: "Enter",
  escape: "Escape",
  esc: "Escape",
  delete: "Delete",
  backspace: "Backspace",
  space: "Space",
  tab: "Tab",
  up: "ArrowUp",
  down: "ArrowDown",
  left: "ArrowLeft",
  right: "ArrowRight",
  arrowup: "ArrowUp",
  arrowdown: "ArrowDown",
  arrowleft: "ArrowLeft",
  arrowright: "ArrowRight",
  home: "Home",
  end: "End",
  pageup: "PageUp",
  pagedown: "PageDown",
  slash: "Slash",
  "/": "Slash",
}

interface Combo {
  mod: boolean
  alt: boolean
  shift: boolean
  code: string
}

function parse(spec: string): Combo {
  const parts = spec.split("+").map((p) => p.trim().toLowerCase())
  const key = parts.pop() ?? ""
  let code = KEY_CODES[key]
  if (!code) {
    if (/^[a-z]$/.test(key)) code = `Key${key.toUpperCase()}`
    else if (/^[0-9]$/.test(key)) code = `Digit${key}`
    else if (/^f\d{1,2}$/.test(key)) code = key.toUpperCase()
    else code = key
  }
  return {
    mod: parts.includes("mod") || parts.includes("ctrl"),
    alt: parts.includes("alt"),
    shift: parts.includes("shift"),
    code,
  }
}

const KEY_LABELS: Record<string, string> = {
  mod: isMac ? "⌘" : "Ctrl",
  ctrl: "Ctrl",
  alt: isMac ? "⌥" : "Alt",
  shift: "Shift",
  enter: "⏎",
  escape: "Esc",
  esc: "Esc",
  delete: "Del",
  slash: "/",
}

/** Клавиши сочетания для подсказки: "Mod+Enter" → ["Ctrl", "⏎"]. */
export function hotkeyKeys(spec: string): string[] {
  return spec.split("+").map((p) => {
    const k = p.trim().toLowerCase()
    return KEY_LABELS[k] ?? (k.length === 1 ? k.toUpperCase() : p.trim())
  })
}

function matchesHotkey(e: KeyboardEvent, spec: string): boolean {
  const c = parse(spec)
  const mod = isMac ? e.metaKey : e.ctrlKey
  const code = e.code.startsWith("Numpad") && /\d$/.test(e.code) ? `Digit${e.code.slice(-1)}` : e.code
  return code === c.code && mod === c.mod && e.altKey === c.alt && e.shiftKey === c.shift
}

function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable
}

/** Подписка на сочетание; обработчик — всегда свежий, без переподписки. */
export function useHotkey(
  spec: string | string[],
  handler: (e: KeyboardEvent) => void,
  { enabled = true, inInputs, preventDefault = true, target }: HotkeyOptions = {}
) {
  const handlerRef = useRef(handler)
  useEffect(() => {
    handlerRef.current = handler
  })
  const specs = Array.isArray(spec) ? spec : [spec]
  const key = specs.join("|")

  useEffect(() => {
    if (!enabled) return
    const node: HTMLElement | Window = target?.current ?? window
    const list = key.split("|")
    const onKey = (event: Event) => {
      const e = event as KeyboardEvent
      if (e.defaultPrevented || e.isComposing) return
      const hit = list.find((s) => matchesHotkey(e, s))
      if (!hit) return
      const withMod = /mod|ctrl|alt/i.test(hit)
      if (isTypingTarget(e.target) && !(inInputs ?? withMod)) return
      if (preventDefault) e.preventDefault()
      handlerRef.current(e)
    }
    node.addEventListener("keydown", onKey)
    return () => node.removeEventListener("keydown", onKey)
  }, [key, enabled, inInputs, preventDefault, target])
}
