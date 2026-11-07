# Nimbus

Nimbus is an open desktop client for managing TikTok accounts, preparing
media and running publication campaigns through the Nimbus API service.
Its interface is available in English, Russian and Ukrainian, with system,
light and dark themes. A phone on the same network can open the interface
using a QR code.

The client is MIT licensed. The remote Nimbus service is operated separately
and requires an API key. TikTok authentication, request signing and native
publication run on that service; its source and credentials are not needed
to develop this client. Media processing and uniquification run locally.

## Run from source

Use Python 3.14 and Node.js 24. Install the platform's desktop webview first:
Edge WebView2 on Windows, WebKit on macOS, or GTK 3 + WebKitGTK 4.1 on Linux.
On Debian/Ubuntu Linux these packages are `python3-gi`, `gir1.2-gtk-3.0`
and `gir1.2-webkit2-4.1`. On Arch Linux install `python-gobject`, `gtk3`
and `webkit2gtk-4.1`.

```sh
python -m venv .venv
# Linux with distro-installed PyGObject: python -m venv --system-site-packages .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -r requirements.txt
cd web
npm ci
npm run build:app
cd ..
python app.py
```

For browser development run `python main.py 8740 127.0.0.1`, then open
`http://127.0.0.1:8740`. The desktop window adds native file dialogs;
the browser and phone interfaces use uploads instead.

The client creates its settings, accounts, sessions and SQLite database
locally. Keep those files private. A clean clone contains no accounts or API
keys. Existing `TikTok Web API v…` folders can be imported on first launch
when placed alongside the new `Nimbus v…` folder; the old files are preserved.

## Develop

```sh
python -m unittest discover -s tests -p "test_*.py"
python tests/check_account_parse.py
python tests/check_accounts_bulk.py
python tests/check_config_cache.py
python tools/check_public_tree.py
cd web
npm run typecheck
npm run lint
npx vitest run
npm run build
```

To work without a live API key or TikTok account, run
`python dev/_ui_mock.py --scenario idle` and set `API_TARGET=http://127.0.0.1:8799`
when starting Vite. The mock contains synthetic data only.

## Build

Build on the target operating system:

```sh
python -m pip install -r requirements-dev.txt
python build.py --dry-run
python build.py
```

The builder produces a standalone application and a ZIP in `dist/`.
GitHub Actions checks Python and frontend code on Windows, Linux and macOS
and provides Windows/Linux build artifacts. macOS packaging is planned later.
Successful compilation is followed by a native
application check before a platform is declared supported in a release.
Version 1.0.0 is being prepared; no public release is published yet.

## Releases

Collect small reviewed commits, run the checks, write short user-facing
notes, and tag the tested commit as `v1.0.0`, `v1.0.1`, and so on.
Publishing a release is a separate, explicit step after platform validation.
The old private releases are summarized as `0.0.1` through `0.0.9`.

## Contribute

Improvements to media processing, uniquification, usability, accessibility
and platform support are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md). The code is licensed under [MIT](LICENSE).
