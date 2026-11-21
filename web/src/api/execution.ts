import { useQuery } from "@tanstack/react-query"
import { api } from "./client"

export type Operation = "login" | "publish" | "logout"
export type ExecutorMode = 0 | 3 | 4
export type ExecutionModes = Record<Operation, ExecutorMode>
export interface ExecutionCapability {
  mode: 1 | 2 | 3 | 4
  supported: boolean
  available: boolean
  live_proven: boolean
  reason: string
}
export interface ExecutionCapabilities {
  operations: Record<Operation, ExecutionCapability[]>
}
export function useExecutionCapabilities() {
  return useQuery({
    queryKey: ["execution", "capabilities"],
    queryFn: () => api.get<ExecutionCapabilities>("api/execution/capabilities"),
    staleTime: 0,
    retry: false,
  })
}
export function useExecutionStates() {
  return useQuery({
    queryKey: ["execution", "states"],
    queryFn: () => api.get<Record<string, Record<"3" | "4", { saved: boolean }>>>("api/execution/states"),
    refetchInterval: 15000,
  })
}
