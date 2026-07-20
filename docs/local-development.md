# Local development

For a SaaS process on the Mac or Windows host and Connector inside Docker, configure the connector with:

```text
http://host.docker.internal:<saas-port>
```

The connector container's `localhost` points to itself, not the host. HTTP origins are accepted only with `PEKA_ENVIRONMENT=development`; production requires HTTPS.

Docker Desktop resolves `host.docker.internal` on macOS and Windows. Linux engines that do not provide it can add this service mapping:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Add that mapping only to a local development Compose override when needed. It is not required by the production Compose workflow.

Start SaaS before registration so its API and database are ready. Connector may start before SaaS after it has credentials: heartbeat recovery will run automatically using bounded backoff.
