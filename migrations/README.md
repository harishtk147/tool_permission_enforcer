# Database migrations

Alembic owns all production schema changes. Do not use `Base.metadata.create_all()` in
application startup or deployment scripts.

Apply the latest migration:

```powershell
uv run alembic upgrade head
```

Show the current revision:

```powershell
uv run alembic current
```

Production deployments run migrations as a one-shot task before new service tasks start.

