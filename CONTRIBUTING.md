# Contributing

Thank you for improving Swarm Agent Coordinator.

## Before opening a change

1. Keep changes focused and explain their operational/security impact.
2. Do not include credentials, `.env` files, database files, logs, backups, attachments, private IP ranges, or customer data.
3. Preserve the default boundary: the control panel stays loopback-only and agent access remains authenticated and scoped to projects/rooms.
4. Run the local checks:

```bash
python -m compileall app adapters master
docker compose config
```

## Pull requests

Describe the problem, the design decision, how you tested it, and any deployment or migration steps. For security-sensitive changes, follow [SECURITY.md](SECURITY.md) instead of creating a public issue.

## Code of conduct

Be respectful, do not publish private information, and do not use the project to coordinate unauthorized access to systems or data.
