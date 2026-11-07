import { useMediaQuery } from "./use-media-query"

const MOBILE_BREAKPOINT = 768

/** Телефонная ширина окна (меньше 768px). */
export function useIsMobile() {
  return useMediaQuery(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
}
