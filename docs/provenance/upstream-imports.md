# Upstream Import Provenance — R3-CHAIN PoC workspace

Recorded: 2026-08-19 (T1.1A). All statements below are limited to what is verifiable
on this machine. No upstream commit hashes are stated for either project because none
were available; nothing here is inferred or invented.

## 1. PyDoublet

- **Source:** project-supplied source archive `pydoublet-main(1).zip` / folder
  `pydoublet-main`, supplied during project work in **July 2026**. The original upstream
  URL and commit hash are **not verified**. (Not attributed to any specific person;
  attribution to be added only if later confirmed.)
- **Local situation at import time:** the archive file itself was not present on this
  machine; the extracted folder `../pydoublet-main/` remained, but its visible content had
  previously been **moved** into `r3chain-poc/PyDoublet/` (the reference copy). Only
  dotfiles and a local `.venv/` remained in `../pydoublet-main/`.
- **Import recipe (2026-08-19):**
  `repos/PyDoublet/` = `r3chain-poc/PyDoublet/` (rsync, excluding `.DS_Store`,
  `__pycache__/`) **+** `../pydoublet-main/.gitignore` **+** `../pydoublet-main/.vscode/`.
  Excluded as machine-local artifacts: `.venv/` (local virtualenv), `__pycache__/`
  (3 compiled cpython-39 files), `.DS_Store` (macOS Finder metadata).
- **Reference-content manifest (119 files):**
  `docs/provenance/manifest-PyDoublet-reference.sha256`,
  manifest-file hash `1c1ac7684396b0b8c08c8e113ba74b6cd270ee0273a55bab4fe7ea07ed7a48a7`.
- **Reunited dotfile hashes:**
  - `.gitignore` `dbcc0b831758af6209d76567319be4ab8f6fcec330719126f73ae0cbadb7d985`
  - `.vscode/settings.json` `f2e66ca269eb2b0582913d99e0fa9f8dcca2e44549e8531a6a9a66fa51093796`
- **Known internal inconsistency carried in unmodified:** `LICENSE` is Apache-2.0 while
  `pyproject.toml`/`setup.py` declare MIT (tracked as Phase-0 question 10).
- **Note:** `figures/dc_example.PNG` and `figures/well_discretization.pdf` are present in
  the supplied content but matched by the upstream `.gitignore` (`figures/` pattern).
  **Checkpoint-1 decision (2026-08-19): force-added** so the baseline commit preserves the
  complete supplied source snapshot. They remain generated/reference figures, not source.
- **Verification (2026-08-19):** rsync checksum dry-run between reference copy and
  `repos/PyDoublet/` (modulo documented exclusions): **0 differing files**.

## 2. pandapipesAI

- **Source (repository URL, as supplied):**
  `https://github.com/Digital-Energy-Intelligence-Lab/pandapipesAI.git`
- **Source (archive):** `pandapipesAI-main.zip`, supplied **August 2026**. The archive
  file itself was not present on this machine at import time; the extracted folder
  `../pandapipesAI-main/` remained, its visible content previously **moved** into
  `r3chain-poc/pandapipesAI/` (the reference copy, file dates 2026-07-28). Only
  `.gitattributes`, `.github/`, `.gitignore` remained in `../pandapipesAI-main/`.
- **Clone attempt (2026-08-19):** `git clone` and `git ls-remote` against the supplied
  URL fail without credentials (HTTP 404 anonymously; `gh` unauthenticated on this
  machine). The repository is private or the URL differs. **The intended Git-managed
  baseline is a fresh clone of this repository**; until credentials are available, a
  fallback import (below) stands in, clearly labelled.
- **Fallback import recipe (2026-08-19):**
  `repos/pandapipesAI/` = `r3chain-poc/pandapipesAI/` (rsync, excluding `.DS_Store`)
  **+** `../pandapipesAI-main/.gitignore`, `.gitattributes`, `.github/`.
- **Reference-content manifest (152 files):**
  `docs/provenance/manifest-pandapipesAI-reference.sha256`,
  manifest-file hash `1b280477f96afc3331c8be1743d900d679ceeb0bf3cbedb4bf5f5643776724bf`.
- **Reunited dotfile hashes:**
  - `.gitignore` `4aeabc29c761072308aab54c5ede55b4df5e7dd7d90090d19437bfcfe8ec4225`
  - `.gitattributes` `7b83fb29de942f8310a55d2dafbd71f79a276275a0bb3a67c757233960c0a991`
  - `.github/workflows/tests.yml` `afbeb510c6a9606844fa66d8c4a0dce400ec06d929cf0f940560a6d621bdadfb`
- **Verification (2026-08-19):** rsync checksum dry-run between reference copy and
  `repos/pandapipesAI/` (modulo documented exclusions): **0 differing files**.
- **Migration policy (Checkpoint-2 decision, 2026-08-19):** official repository access is
  being requested in parallel. When access becomes available, this repository is **not**
  to be replaced or overwritten. Instead: create a separate clean upstream clone, compare
  it against this baseline (`diff -r`, recorded here), and propose a controlled migration
  or cherry-pick plan for the feature commits before any switch.

## 3. Proof that no existing work was lost (2026-08-19)

1. SHA-256 manifests of both reference folders were frozen **before** any copy/git action.
2. Re-hashing both reference folders after all T1.1A operations: **byte-identical** to the
   frozen manifests (`diff` clean for both).
3. Reference folders and `../*-main/` residue folders were used read-only throughout.
4. rsync checksum comparisons (see per-repo sections): 0 differing files.

## 4. Repository state produced by T1.1A (final, after approved checkpoints)

- `repos/PyDoublet/` — root commit `4fb328d` on `main` (118 files: 116 staged + 2
  force-added figures), tag `upstream-import-2026-08-19`, branch
  `feature/pydoublet-integration`. Working tree clean.
- `repos/pandapipesAI/` — root commit `a1fe3c6` on `main` (155 files), tag
  `upstream-import-2026-08-19`, branch `feature/r3chain-geothermal-poc`.
  Working tree clean. Described as a project-supplied source snapshot, **not** a
  verified clone with upstream history (see migration policy above).
