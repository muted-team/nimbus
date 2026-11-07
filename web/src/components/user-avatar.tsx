import { CircleUserRoundIcon } from "lucide-react"

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"

export function UserAvatar({
  url,
  name,
  size = "default",
}: {
  url?: string | null
  name: string
  size?: "default" | "sm" | "lg"
}) {
  return (
    <Avatar size={size}>
      {url ? (
        <AvatarImage src={url} alt={name} referrerPolicy="no-referrer" />
      ) : null}
      <AvatarFallback>
        <CircleUserRoundIcon className="size-5" />
      </AvatarFallback>
    </Avatar>
  )
}
