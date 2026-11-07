import { COLUMN_LABEL } from "./labels"
import type { SortKey } from "./filter"

/* Колонки таблицы прокси — настоящей `<table>`, а не сетки: ширину считает
   браузер (по самому длинному значению, а короче заголовка — по заголовку,
   обычная авто-раскладка `<table>`), и в коде не остаётся ни одного числа
   ширины, которое рассохнется при первом новом значении.

   У сетки колонок (как в списке аккаунтов) это не вышло бы: там КАЖДАЯ
   СТРОКА — своя сетка ради виртуализации, и `max-content` между разными
   сетками не выравнивается. Здесь виртуализации нет (строк десятки, не
   сотни) — значит и сетка не нужна, годится обычная таблица.

   Выравнивание и видимость каждой колонки — один класс на колонку здесь, а
   не отдельно в шапке и в строке: `<th>` и `<td>` одной колонки берут этот
   класс из одного места и не могут разойтись между собой. */

/* Ярусы видимости — как у аккаунтов: на 1280 таблица не должна вылезать
   за край и уводить меню строки под горизонтальную прокрутку. Отметки входа
   и публикации — работа, они видны с планшета; протокол, время ответа и
   занятость — справка, им место только на широком окне. Колонка действий
   прилеплена к правому краю: даже если таблица всё же шире окна, «…» под
   рукой. */
export const CELL = {
  index: "text-right tabular",
  proxy: "text-left",
  country: "hidden text-center sm:table-cell",
  scheme: "hidden text-left 2xl:table-cell",
  state: "text-left whitespace-nowrap",
  ping: "hidden text-right tabular whitespace-nowrap lg:table-cell",
  ms: "hidden text-right tabular whitespace-nowrap 2xl:table-cell",
  busy: "hidden text-right tabular xl:table-cell",
  checked: "hidden text-right whitespace-nowrap xl:table-cell",
  login: "hidden text-center sm:table-cell",
  publish: "hidden text-center sm:table-cell",
  actions: "sticky right-0 bg-background text-right",
} as const

/* Страна — не число, а флаг: своя колонка сразу за адресом, оформлена
   отдельно от чисел, по алфавиту кода, а не величине. */
export const COUNTRY_COLUMN = { key: "country" as const, label: COLUMN_LABEL.country, cell: CELL.country }

/* Числовые колонки прижаты вправо — тот же приём, что у списка аккаунтов. */
export const NUM_COLUMNS: { key: SortKey; label: string; cell: string }[] = [
  { key: "ping", label: COLUMN_LABEL.ping, cell: CELL.ping },
  { key: "ms", label: COLUMN_LABEL.ms, cell: CELL.ms },
  { key: "busy", label: COLUMN_LABEL.busy, cell: CELL.busy },
  { key: "checked_at", label: COLUMN_LABEL.checked_at, cell: CELL.checked },
]
