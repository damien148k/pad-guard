Rapports `rapport.md` produits par pad-checker à la fin de la Phase 3 (commit 5e66c58, le
23 octobre 2026) sur les fixtures de `tests/fixtures/make_fixtures.sh` : `ok_*` et `bad_*` avec
`tests/profiles/test_classic.yaml`, `arte_*` avec `profiles/arte_hd_sdr.yaml`.

Les lignes qui dépendent de la machine ou de la date (chemin, SHA-256 et taille du fichier,
date, commande, relances) ont été retirées. `tests/test_v3.py` vérifie que les rapports
actuels n'en diffèrent que par les lignes ajoutées en Phase 4a.
