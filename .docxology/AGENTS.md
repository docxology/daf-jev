# AGENTS.md — `.docxology/`

This folder is managed by the `docxology-sidecar` tool
(github.com/docxology/daf-sidecar); `init` scaffolded it and
`seal`/`open`/`status`/`doctor`/`recipients` maintain it. Read
`docs/format-spec.md` in that repo before writing against any field.

## Layout

- `manifest.toml` — plaintext identity/provenance fields (`validate`
  checks field presence).
- `.sidecar-lock.toml` — plaintext recipients plus a sha256 tamper
  hash per sealed file.
- `public/` — always plaintext (`citation.toml`, `links.toml`).
- `sealed/` — always ciphertext (age / sops / tar+age). Classification
  is by directory only; never place plaintext in `sealed/` or
  ciphertext in `public/`.

## Rules

- `status`/`doctor` verify every sealed file's ciphertext hash against
  `.sidecar-lock.toml` — commit updated ciphertext and lock together.
- Your age identity lives at `~/.config/docxology-sidecar/identity.txt`
  (mode 0600, machine-wide, never in git). `seal` refuses until your
  public key is a recipient of THIS repo:
  `docxology-sidecar recipients add . <pubkey>`.

---

In the sidecar tool's own repo, this file doubles as the canonical copy
of its own scaffold template: the templates are embedded as string
literals in `src/cli.ts`'s `TEMPLATES` map (not fs reads), so editing
the file under `templates/` without the matching map string changes
nothing at runtime — `tests/templates-sync.test.ts` fails on drift.
