"""Разбор строки аккаунта (`modules/accounts._parse_account_line`).

Первые две части строки — логин и пароль ПО ПОЗИЦИИ: настоящий логин
бывает с заглавными и точкой (`Kate_2024`, `Anna.K`), и прежний разбор «по виду»
брал логином пароль. Разбор по виду остаётся запасным путём — когда первая часть
вовсе не похожа на логин (строка начинается с почты или с 2FA-секрета).

Тест постоянный, без сети и без файлов: только разбор.

Крайние случаи двухбуквенный логин при четырёх частях (не уезжает в
регион) и логин вне ASCII (не меняется местами с паролем).

    Run the corresponding check in tests/.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.accounts import _parse_account_line as parse  # noqa: E402

TOTP = "JBSWY3DPEHPK3PXP"                    # 16 символов = 80 бит
TOTP32 = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # 32 символа = 160 бит
TOTP26 = "ABCDEFGHIJKLMNOPQRSTUVWX23"        # 26 символов = 128 бит

# (что проверяем, строка, ожидаемая запись целиком; None — строка не разбирается)
CASES = [
    # --- правило владельца: первая часть — логин, вторая — пароль ---
    ("логин с заглавными, пароль строчный",
     f"Kate_2024:kate2024:{TOTP}",
     {"username": "Kate_2024", "password": "kate2024", "totp_secret": TOTP}),
    ("логин с точкой и заглавной, пароль из цифр",
     f"Anna.K:12345678:{TOTP}",
     {"username": "Anna.K", "password": "12345678", "totp_secret": TOTP}),
    ("обе части одинаковые — решает порядок",
     f"fixture.same:fixture.same:{TOTP}",
     {"username": "fixture.same", "password": "fixture.same", "totp_secret": TOTP}),
    ("ведущая собака у логина снимается",
     f"@Kate_2024:kate2024:{TOTP}",
     {"username": "Kate_2024", "password": "kate2024", "totp_secret": TOTP}),
    ("логин строчный, пароль со спецсимволами — как было",
     f"kate1993:Test!Password9:{TOTP}",
     {"username": "kate1993", "password": "Test!Password9", "totp_secret": TOTP}),

    # --- старые формы: не сломаны ---
    ("комбо email|логин|пароль|регион|2fa",
     f"mailbox@example.invalid|fixture.profile|Test!Password9|US|{TOTP32}",
     {"username": "fixture.profile", "password": "Test!Password9", "totp_secret": TOTP32,
      "email": "mailbox@example.invalid"}),
    ("логин:пароль:2fa",
     f"fixture.user:MyPass123:{TOTP}",
     {"username": "fixture.user", "password": "MyPass123", "totp_secret": TOTP}),
    ("разделитель пробел",
     f"fixture.second Qwerty45 {TOTP26}",
     {"username": "fixture.second", "password": "Qwerty45", "totp_secret": TOTP26}),
    ("комбо логин:пароль:почта:пароль почты",
     "kate1993:Test!Password9:mailbox@example.invalid:MailPass99",
     {"username": "kate1993", "password": "Test!Password9",
      "email": "mailbox@example.invalid", "email_password": "MailPass99"}),

    # --- запасной путь: первая часть не похожа на логин ---
    ("строка начинается с 2FA-секрета",
     f"{TOTP}:fixture.user:MyPass123",
     {"username": "fixture.user", "password": "MyPass123", "totp_secret": TOTP}),
    ("строка начинается с пароля со спецсимволами",
     f"Test!Password9:kate1993:{TOTP}",
     {"username": "kate1993", "password": "Test!Password9", "totp_secret": TOTP}),
    ("регион снимается, только когда остаются логин и пароль",
     f"ab:pass:{TOTP}",
     {"username": "ab", "password": "pass", "totp_secret": TOTP}),

    # --- логин/пароль, случайно похожие на 2FA-секрет по виду ---
    ("логин из букв+цифр 2-7 не принимается за 2FA-секрет",
     f"abcdefghijklmn237|Test!Password9|{TOTP32}",
     {"username": "abcdefghijklmn237", "password": "Test!Password9", "totp_secret": TOTP32}),
    ("тот же логин первым не отдаётся и при другом порядке",
     f"Test!Password9|abcdefghijklmn237|{TOTP32}",
     {"username": "abcdefghijklmn237", "password": "Test!Password9", "totp_secret": TOTP32}),
    ("длина не как у ключа (17) — это не 2FA-секрет",
     "kate1993:pass123:abcdefghijklmn237", None),
    ("секрет на 26 символов (128 бит)",
     f"kate1993:Test!Password9:{TOTP26}",
     {"username": "kate1993", "password": "Test!Password9", "totp_secret": TOTP26}),
    ("логин ровно 16 символов формы base32 — секрет тот, что длиннее",
     f"abcdefghijklmn23:mypass12:{TOTP32}",
     {"username": "abcdefghijklmn23", "password": "mypass12", "totp_secret": TOTP32}),
    ("оба по 16 символов — решает порядок, логин первый",
     f"abcdefghijklmn23:mypass12:{TOTP}",
     {"username": "abcdefghijklmn23", "password": "mypass12", "totp_secret": TOTP}),

    # --- правило TikTok: в юзернейме только буквы, цифры, '_' и '.' ---
    ("пароль со спецсимволом в логин не уезжает — строка не разбирается",
     f"gjf$nix054|qwe!rty#12|{TOTP32}", None),

    # --- крайние случаи ---
    ("двухбуквенный логин не уезжает в регион",
     f"ab:pass:US:{TOTP}",
     {"username": "ab", "password": "pass", "totp_secret": TOTP}),
    ("логин вне ASCII — по позиции, не по виду",
     f"Катя:kate2024:{TOTP}",
     {"username": "Катя", "password": "kate2024", "totp_secret": TOTP}),

    # --- не разбирается ---
    ("логин и пароль без источника кода", "user:pass", {"username": "user", "password": "pass"}),
    ("нет источника кода", "user:pass:notacode", None),
    ("пустая строка", "   ", None),
]

bad = 0
for name, line, want in CASES:
    got = parse(line)
    ok = got == want
    if not ok:
        bad += 1
    print(f"{'ok   ' if ok else 'ПРОВАЛ'} {name}")
    print(f"        строка: {line!r}")
    print(f"        ждали: {want}")
    print(f"        вышло: {got}")

print()
if bad:
    print(f"ПРОВАЛ: {bad} из {len(CASES)}")
else:
    print(f"ок: {len(CASES)} случаев разобраны как задумано")
sys.exit(1 if bad else 0)
