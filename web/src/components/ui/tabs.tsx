import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"

import { cn } from "@/lib/utils"

/* Вкладки в виде линии: выбранная — цветом текста и чертой снизу, как виды
   в Linear и Attio. Черта — у самой вкладки, а не бегущий индикатор: список
   прокручивается вбок на телефоне, и индикатор отставал бы от прокрутки. */

function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return <TabsPrimitive.Root data-slot="tabs" className={cn("flex min-w-0 flex-col", className)} {...props} />
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn("flex min-w-0 items-center gap-4 overflow-x-auto no-scrollbar", className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-8 shrink-0 items-center gap-2 text-sm whitespace-nowrap text-muted-foreground transition-colors outline-none select-none",
        "hover:text-foreground focus-visible:rounded-sm focus-visible:ring-3 focus-visible:ring-ring/50",
        "after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:rounded-full after:bg-transparent",
        "data-active:text-accent-foreground data-active:after:bg-primary",
        "disabled:pointer-events-none disabled:opacity-50 pointer-coarse:h-10",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return <TabsPrimitive.Panel data-slot="tabs-content" className={cn("min-w-0 outline-none", className)} {...props} />
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
