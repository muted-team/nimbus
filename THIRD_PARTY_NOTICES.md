# Сторонние компоненты

Nimbus использует Python- и npm-пакеты на условиях их собственных лицензий.
Точные версии записаны в requirements и npm lockfile.

- SVG-флаги: flag-icons, автор lipis, MIT; см. `web/public/flags/LICENSE`.
- Шрифт Inter Variable: SIL Open Font License 1.1 (`@fontsource-variable/inter`).
- Компоненты Base UI и shadcn: MIT; лицензии компонентов сохраняются.
- React, Tailwind CSS, Lucide, TanStack, Zustand, Wouter, Sonner и QRCode:
  лицензии входят в соответствующие пакеты.
- pywebview, Pillow, pillow-heif и curl_cffi: лицензии соответствующих пакетов.
- Системные WebView2, WebKit и GTK распространяются на своих условиях.

Готовые сборки включают зависимости выбранной платформы. При упаковке
релиза сохраняйте поставляемые с ними файлы лицензий.
