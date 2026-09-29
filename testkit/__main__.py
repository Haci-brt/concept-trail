"""The test environment: Concept Trail with sample notes and a stand-in
model, entirely apart from your own notes and settings.

    python -m testkit                  opens in the browser
    python -m testkit --pencere        in the desktop window
    python -m testkit --gercek-model   with your own model settings (notes still apart)
    python -m testkit --ilk-acilis     as if no model were connected: try the setup wizard
    python -m testkit --sifirla        start over with fresh sample notes and settings
    python -m testkit --sunucu         no window at all; open the address yourself

Everything lives in .sandbox/ next to the code (ignored by git): the vault in
.sandbox/kasa, the settings in .sandbox/ayar. Walk through docs/TEST.md.
"""
import argparse
import os
import shutil
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANDBOX = ROOT / ".sandbox"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def free_port(preferred: int = 0) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
        except OSError:
            s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="python -m testkit",
                                     description="Concept Trail test ortamı: örnek notlar ve sahte bir modelle, "
                                                 "gerçek notlarından ve ayarlarından ayrı.")
    parser.add_argument("--pencere", action="store_true", help="masaüstü penceresinde aç (varsayılan: tarayıcı)")
    parser.add_argument("--sunucu", action="store_true", help="hiçbir pencere açma; yalnız sunucu (adresi kendin aç)")
    parser.add_argument("--gercek-model", action="store_true",
                        help="sahte model yerine kendi model ayarlarını kullan (notlar yine test kasasında)")
    parser.add_argument("--ilk-acilis", action="store_true",
                        help="hiç model bağlı değilmiş gibi aç: kurulum sihirbazını dene")
    parser.add_argument("--sifirla", action="store_true", help="örnek notları ve test ayarlarını baştan kur")
    parser.add_argument("--gecikme", type=float, default=0.3, help="sahte modelin cevap gecikmesi, saniye (0.3)")
    parser.add_argument("--port", type=int, default=0, help="uygulamanın portu (verilmezse boş bir port)")
    args = parser.parse_args()

    if args.sifirla and SANDBOX.exists():
        shutil.rmtree(SANDBOX)
        print("Test ortamı sıfırlandı.")
    from testkit.seed import bind_fake_model, seed_vault
    vault = SANDBOX / "kasa"
    written = seed_vault(vault)

    model = None
    if not args.gercek_model:
        from testkit.fake_model import FakeModel
        config = SANDBOX / "ayar"
        os.environ["FIKIR_CONFIG_DIR"] = str(config)
        providers = config / "ConceptTrail" / "providers.json"
        # first start: on llama.cpp's usual port, so the wizard finds it by itself
        model = FakeModel(delay=args.gecikme, port=free_port(8080) if args.ilk_acilis else 0).start()
        if args.ilk_acilis:
            providers.unlink(missing_ok=True)
            prefs = config / "ConceptTrail" / "preferences.json"
            if prefs.exists():
                import json
                data = json.loads(prefs.read_text(encoding="utf-8"))
                data["setup_dismissed"] = False
                prefs.write_text(json.dumps(data), encoding="utf-8")
        else:
            bind_fake_model(config, model.base_url)

    port = args.port or free_port(8790)
    print()
    print("  Concept Trail — test ortamı")
    print(f"  Adres:  http://127.0.0.1:{port}/")
    print(f"  Notlar: {vault}" + (f"  (yeni: {len(written)} örnek not)" if written else ""))
    if model is None:
        print("  Model:  senin model ayarların (harcama sınırın geçerli)")
    elif args.ilk_acilis:
        print(f"  Model:  bağlı değil — sihirbazda 'Bu bilgisayarda çalışan bir model'i seç ({model.base_url})")
    else:
        print(f"  Model:  sahte model, {model.base_url} (anahtarsız, ücretsiz)")
    print("  Kontrol listesi: docs/TEST.md · durdurmak için Ctrl+C")
    print()

    import main as app_main
    mode = [] if args.pencere else ["--server"] if args.sunucu else ["--browser"]
    sys.argv = ["main.py", "--vault", str(vault), "--port", str(port)] + mode
    try:
        app_main.main()
    finally:
        if model is not None:
            model.stop()


if __name__ == "__main__":
    main()
