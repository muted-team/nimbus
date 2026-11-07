import { localize, t } from "@/lib/i18n"
import type { BrowserProfile, ProxyOnDeath } from "@/api/types"

/* Тексты экрана «Настройки»: общая форма, пароль и сервер. */

export const SETTINGS_LABEL = localize({
  publishing: "Публикация",
  browser: "Профиль браузера",
  browserGroup: "Браузер",
  browserPending: "Применится после перезапуска приложения",
  threads: "Потоков",
  proxyOnDeath: "Прокси умер",
  serverWait: "Ждать сервер, мин",
  address: "Адрес",
  port: "Порт",
  phone: "С телефона",
  phoneTitle: "Подключить телефон",
  phoneHint: "Телефон и компьютер должны быть в одной Wi-Fi-сети.",
  phoneNeedPassword: "Сначала задайте пароль для доступа к Nimbus ниже.",
  phoneScan: "Отсканируйте QR-код камерой телефона и введите пароль Nimbus.",
  phoneUnavailable: "Адрес локальной сети не найден.",
  phoneQrError: "Не удалось создать QR-код.",
  phonePortOpen: (port: string) => t("Порт {0} открыт на этом компьютере.", [port]),
  phoneConnected: "Подключение с устройства получено.",
  phoneWaiting: "Ждём подключения с устройства.",
  now: "сейчас",
  restart: "после перезапуска",
  copy: "Скопировать",
} as const)

export const BROWSER_LABEL: Record<BrowserProfile, string> = {
  chrome152: "Chrome 152",
  firefox155: "Firefox 155",
}

export const ON_DEATH_LABEL: Record<ProxyOnDeath, string> = localize({
  swap: "Сменить прокси",
  stop: "Остановить поток",
})

export const SETTINGS_TOAST = localize({
  restart: "Сработает после перезапуска программы.",
  copied: "Ссылка скопирована.",
} as const)

export const PASSWORD_LABEL = localize({
  title: "Доступ к Nimbus",
  hint: "Этот пароль нужен для входа с телефона и других устройств.",
  localHint: "На этом компьютере пароль не требуется.",
  field: "Новый пароль",
  set: "Задать",
  remove: "Снять",
  exit: "Выйти на этом устройстве",
} as const)

export const PASSWORD_TOAST = localize({
  set: "Пароль задан.",
  removed: "Пароль снят.",
  confirmRemove: "Снять пароль?",
} as const)

export const SERVER_LABEL = localize({
  title: "Сервер",
  address: "Адрес",
  checking: "Проверяю соединение",
  ok: "Доступен",
  ms: "мс",
  fail: "Нет связи",
} as const)
