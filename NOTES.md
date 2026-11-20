# Engineering notes: PensionPal

## D03 · PostgreSQL

### Migrations (upgrade, downgrade, upgrade)

```text
paste the output of:
uv run alembic downgrade -1
uv run alembic current
uv run alembic upgrade head
uv run alembic history
```

### The loader is idempotent

```text
run 1: paste here
run 2: paste here
run 3 (after editing one record): paste here
```

### EXPLAIN for ?doc_type=FAQ

```text
paste the output of: uv run python scripts/explain.py doc_type FAQ
```

Why did the planner choose a Seq Scan on my table? (2 lines, your own words)

With only 20 rows, Postgres decides it is cheaper to scan the whole table than
to use an index, because the overhead of an index lookup exceeds the cost of
reading a tiny table in one pass.

When would it switch to the GIN index? (1 line)

The planner switches to a Bitmap Index Scan on the GIN index when the table
is large enough that filtering first is faster than a full scan.
