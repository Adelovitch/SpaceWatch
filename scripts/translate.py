#!/usr/bin/env python3
"""Optional offline English-to-French translation; original fields are preserved."""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "articles.json"

def main():
    import argostranslate.package
    import argostranslate.translate
    argostranslate.package.update_package_index()
    packages = argostranslate.package.get_available_packages()
    model = next((p for p in packages if p.from_code == "en" and p.to_code == "fr"), None)
    if model is None:
        raise RuntimeError("Modèle anglais → français indisponible")
    argostranslate.package.install_from_path(model.download())
    data = json.loads(DATA.read_text(encoding="utf-8"))
    # Reuse previously translated articles when a new collection leaves the same text.
    cache = {}
    cache_path = DATA.parent / "translation_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    # Editorial corrections take precedence over the persisted machine-translation cache.
    reviewed_titles = {
        "APOD: 2026 October 25 – Dark Matter in a Simulated Universe":
            "Image astronomique du jour : la matière noire dans un univers simulé",
        "APOD: 2026 October 24 – Rosetta’s Selfie":
            "Image astronomique du jour : l’autoportrait de Rosetta",
        "NASA, Partners Accelerate Lander Development for 2028 Moon Missions":
            "La NASA et ses partenaires accélèrent le développement des atterrisseurs lunaires pour 2028",
        "NASA’s James Webb Space Telescope Captures Eerie Cat’s Head":
            "Le télescope James-Webb révèle une mystérieuse nébuleuse en forme de tête de chat",
        "APOD: 2026 October 31 – Night on a Spooky Planet":
            "Image astronomique du jour : nuit sur une planète inquiétante",
        "NASA Releases MAX POWER Key Events for Media, Participants":
            "La NASA dévoile les temps forts de MAX POWER pour les médias et les participants",
    }
    reviewed_summaries = {
        "NASA Astronomy Picture of the Day — Night on a Spooky Planet. Read the original NASA page for the scientific explanation.":
            "Image astronomique du jour de la NASA : nuit sur une planète inquiétante. Consultez la page originale pour l’explication scientifique.",
    }

    updated = 0
    for a in data.get("articles", []):
        for key in ("title", "summary"):
            original = re.sub(r"\\s+", " ", a.get(key, "")).strip()
            if not original:
                continue
            translated = (reviewed_titles if key == "title" else reviewed_summaries).get(original)
            if translated is None:
                translated = cache.get(original)
            if translated is None:
                translated = re.sub(r"\\s+", " ", argostranslate.translate.translate(original, "en", "fr")).strip()
                if translated:
                    cache[original] = translated
            if translated and translated != original:
                a[key + "_fr"] = translated
                updated += 1
    data["translation"] = {"engine": "Argos Translate", "type": "automatique", "source": "en", "target": "fr"}
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Traductions produites : {updated} champs")

if __name__ == "__main__":
    main()
