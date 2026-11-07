/// <reference types="vitest/config" />
import * as path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

// Сервер программы отдаёт собранный интерфейс из ui/ и API под /api на том же
// адресе. В разработке Vite проксирует /api на живой сервер (main.py, 8740)
// или на стенд с выдуманными данными (dev/_ui_mock.py): API_TARGET=...
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const target = env.API_TARGET || "http://127.0.0.1:8740"

  return {
    // относительные пути: интерфейс открывают и из окна программы, и по
    // ссылке с сервера, где он может жить не в корне домена
    base: "./",
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": path.resolve(import.meta.dirname, "./src") },
    },
    server: {
      port: Number(env.PORT) || 5173,
      strictPort: true,
      // Origin — как у окна программы: сервер отклоняет /api с чужой
      // страницы (main.py: _foreign), а dev-сервер Vite для него чужой
      proxy: { "/api": { target, changeOrigin: true, headers: { origin: target } } },
    },
    build: {
      // в ui/ (откуда отдаёт сервер) собирает npm run build:app — он передаёт
      // --outDir сам; здесь обычный dist для просмотра сборки
      outDir: "dist",
      emptyOutDir: true,
      target: "es2022",
      chunkSizeWarningLimit: 900,
    },
    test: {
      include: ["src/**/*.test.ts"],
    },
  }
})
