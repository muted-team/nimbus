import { useLanguage } from "@/lib/i18n"
import { RotateCcwIcon, UserRoundIcon } from "lucide-react"

import type { BannedAccount } from "@/api/types"
import { SelectionBarSpacer } from "@/components/selection-bar"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Button } from "@/components/ui/button"
import { fmtAgo } from "@/lib/format"

import { BANNED_LABEL } from "./labels"
import { atUsername } from "./username"

/* Отключённые аккаунты: кампания уносит их сюда сама, когда TikTok отвечает
   баном. Это отдельный срез списка — в общем списке их нет, чтобы они не
   мешались среди рабочих. «Вернуть» — на случай ошибочного бана. */

export function BannedBlock({
  banned,
  avatars,
  disabled,
  onRestore,
  padBottom,
}: {
  banned: BannedAccount[]
  /** аватарки остаются от прошлых обновлений профиля */
  avatars?: Record<string, string>
  /** идёт публикация: менять аккаунты нельзя */
  disabled: boolean
  onRestore: (username: string) => void
  /** внизу висит панель выделения — освобождаем место под неё */
  padBottom?: boolean
}) {
  useLanguage()
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      {banned.map((b) => (
        <div
          key={b.username}
          className="flex h-12 items-center gap-3 border-b px-4 text-row md:px-6"
        >
          <Avatar className="size-8 shrink-0 opacity-60">
            {avatars?.[b.username] ? (
              <AvatarImage src={avatars[b.username]} alt="" />
            ) : (
              <AvatarFallback>
                <UserRoundIcon className="size-4 text-muted-foreground" />
              </AvatarFallback>
            )}
          </Avatar>
          <div className="min-w-0 flex-1 select-text">
            <div className="truncate font-medium">{atUsername(b.username)}</div>
            {b.ban_reason ? (
              <div className="truncate text-xs text-muted-foreground">{b.ban_reason}</div>
            ) : null}
          </div>
          <div className="shrink-0 text-right text-xs text-muted-foreground tabular">
            {BANNED_LABEL.at} {fmtAgo(b.banned_at)}
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={disabled}
            onClick={() => onRestore(b.username)}
          >
            <RotateCcwIcon />
            {BANNED_LABEL.restore}
          </Button>
        </div>
      ))}
      {padBottom ? <SelectionBarSpacer /> : null}
    </div>
  )
}
