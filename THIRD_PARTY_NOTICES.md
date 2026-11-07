# Third-party notices

Nimbus uses Python and npm packages under their respective licenses.
The npm lockfile and Python requirement pins record the exact dependencies.

- Inter Variable font: SIL Open Font License 1.1 (`@fontsource-variable/inter`).
- Base UI and shadcn component sources: MIT; retained dependency licenses
  apply to their components.
- React, Tailwind CSS, Lucide, TanStack, Zustand, Wouter, Sonner and QRCode:
  see the licenses distributed with each package.
- pywebview, Pillow, pillow-heif and curl_cffi: see their package licenses.
- Native WebView2, WebKit and GTK runtimes retain their own licenses.

Build artifacts include the dependencies selected by the target platform.
Do not remove their bundled license files when packaging a release.
