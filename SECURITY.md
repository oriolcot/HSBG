# Security

## Reporting

Do not post credentials, personal data or exploit details in a public issue.
If GitHub offers **Security → Report a vulnerability**, use that private channel.
Otherwise, open a minimal issue asking for a private reporting channel without
including sensitive details. Do not perform disruptive tests on the public site.

## Deployment guidance

- Run the web process as an unprivileged dedicated user, not an administrator.
- Keep code and leaderboard data read-only to the web process. Give the collector
  write access only to its snapshot directory.
- Keep secrets, private infrastructure configuration, logs and data dumps outside Git.
  `.gitignore` does not remove files already tracked or erase Git history.
- Expose the application through an HTTPS reverse proxy. Keep Uvicorn on loopback.
- The API trusts forwarded client-IP headers from its proxy. The proxy must replace
  client-supplied headers and trust CDN headers only from verified CDN source ranges.
- Preserve search limits and bound requests/resources at the proxy and service levels.
- Patch dependencies and the host OS, use MFA for hosting accounts, and maintain
  off-server backups with tested recovery procedures.

The application JavaScript is served from `assets/app.js`, with no inline script
or HTML event handlers. The public deployment restricts scripts to its own origin
and the Cloudflare Analytics script host, and blocks inline handlers and eval.
Inline CSS remains; this is an allowlist-based CSP, not a nonce-based strict CSP.
For your deployment, test policies against the fonts, images and analytics you use.
Server-side protection is not installed automatically by cloning this repository.

No audit or dependency scan guarantees that the application is vulnerability-free.
