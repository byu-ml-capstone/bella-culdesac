# Deployment

The class platform deploys `docker-compose.yaml` through Coolify. GitHub Actions runs tests, then triggers the staging webhook from `staging` and the production webhook from `main`.

## Services

`hello` is the only public service and listens internally on port 8000. It references `${SERVICE_FQDN_HELLO}` so Coolify/Traefik can route the domain. `db` is internal and must not receive a service FQDN reference.

Production Compose uses `expose`, not host `ports`. The local-only override supplies the host binding for development.

## Coolify settings

Configure the domain manually for the `hello` service in both staging and production, then redeploy after changing it. Required deployment variables include:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB`
- `SESSION_SECRET`
- `APP_TIMEZONE`
- `APP_VERSION`
- `AI_PROVIDER`, `LITELLM_BASE_URL`, `LITELLM_API_KEY`, and `LITELLM_MODEL` when report generation is enabled

Use separate values and volumes for staging and production. Keep `ALLOW_ADMIN_RESET=false` in deployed environments.

After deployment, check `/health`, `/version`, and run the smoke test against the deployed URL:

```bash
SMOKE_USERNAME=lead SMOKE_PASSWORD='temporary-value' ./smoke-test.sh http://your-coolify-domain
```

The domain must be reachable from the class network/VPN as required by the platform.
