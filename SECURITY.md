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

The interface contains inline JavaScript/CSS. A strict script CSP needs additional
work; do not assume that a default-src/script-src self policy will work unchanged.
Server-side protection is not installed automatically by cloning this repository.

No audit or dependency scan guarantees that the application is vulnerability-free.
