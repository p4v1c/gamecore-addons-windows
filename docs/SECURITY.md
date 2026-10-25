# gamecore-addons — security rules

The full plan lives in
[GamecoreWindows/docs/SECURITY.md](https://github.com/p4v1c/GamecoreWindows/blob/main/docs/SECURITY.md).
Summary: a single LAN-facing port (Caddy `:8443`, HTTPS + shared login via
`forward_auth`), everything else on loopback. Addons are served behind path
prefixes (`/roms/`, `/saves/`, `/rpcs3/`, `/bios/`) on a single origin. On
Windows the firewall opens `:8443` alone (Private profile): an addon port needs
no rule because nothing outside the PC may reach it.

## Rules for every addon

1. **Loopback only**: `uvicorn.run(app, host="127.0.0.1", port=PORT)`.
   Never `0.0.0.0` — Caddy is what exposes to the LAN.
2. **No CORS**: behind Caddy everything is same-origin. No
   `CORSMiddleware`, ever.
3. **Not one line of auth** in the addons: Caddy enforces the login upstream
   (`forward_auth` to the core). The addon receives the identity in the
   `X-GC-User` header, and that is all.
4. **No hardcoded port or host on the client side** (phase 4): relative URLs
   in HTML/JS, shared nav based on `location.origin` + `/gc/addons`. The
   FastAPI app takes `root_path=os.environ.get("ADDON_BASE", "")`, and
   `install.ps1` writes `ADDON_BASE` into `addon.env` from the `path` field of
   `addon.json`.
5. When the browser needs a core resource, it goes through the proxied
   statics (`/assets/*`) or a passthrough endpoint of the addon — the core's
   `/api/*` is never exposed to the LAN.
6. **A passthrough relays; it does not reimplement.** rom-manager's covers are
   the example: the core finds, scrapes and caches a cover under its own
   names, and the addon asks it over loopback instead of reading the cache.
   On Linux, the bezel upload was the write-side example (the core decided the
   filename, the destination and the validation); the Windows edition has no
   overlays. Anything the core owns is written by the core: `api: 1` says an
   addon writes inside its own data directory and nowhere else.
7. **The tasks run elevated** (owner's decision: the backend does too). That
   makes rules 1 and 3 matter more, not less: a loopback-only server behind
   Caddy's login is the boundary, and the path-containment checks
   ([06](architecture/06-security-and-traps.md)) are what stop an upload from
   reaching outside its folder.

## Phases on the addon side

- **Phase 1**: bind `127.0.0.1` + removal of wildcard CORS in rom-manager,
  rpcs3-manager, save-manager and `_template`.
- **Phase 4**: `root_path`/`ADDON_BASE`, `path` field in `addon.json`, shared
  path-based nav, full audit of absolute URLs in HTML/JS.
