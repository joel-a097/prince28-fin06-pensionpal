# Engineering notes: PensionPal

## D03 · PostgreSQL

### Migrations (upgrade, downgrade, upgrade)

```text
INFO  [alembic.runtime.migration] Running downgrade 5f1275c9ff24 -> dc4f9b756223, add gin index on metadata

dc4f9b756223

INFO  [alembic.runtime.migration] Running upgrade dc4f9b756223 -> 5f1275c9ff24, add gin index on metadata

dc4f9b756223 -> 5f1275c9ff24 (head), add gin index on metadata
<base> -> dc4f9b756223, create documents and pages
```

### The loader is idempotent

```text
run 1: records=20 inserted=20 updated=0 unchanged=0
run 2: records=20 inserted=0 updated=0 unchanged=20
run 3 (after editing one record): records=20 inserted=0 updated=1 unchanged=19
```

### EXPLAIN for ?doc_type=FAQ

```text
-- 1) What the planner chooses on its own:
Seq Scan on documents  (cost=0.00..11.00 rows=1 width=36) (actual time=0.022..0.022 rows=0.00 loops=1)
  Filter: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
  Rows Removed by Filter: 20
  Buffers: shared hit=2
Planning:
  Buffers: shared hit=149
Planning Time: 0.413 ms
Execution Time: 0.045 ms

-- 2) Seq scan switched off, to prove the index can be used:
Bitmap Heap Scan on documents  (cost=12.81..16.82 rows=1 width=36) (actual time=0.108..0.109 rows=0.00 loops=1)
  Recheck Cond: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
  Buffers: shared hit=3
  ->  Bitmap Index Scan on ix_documents_metadata_gin  (cost=0.00..12.81 rows=1 width=0) (actual time=0.027..0.028 rows=0.00 loops=1)
        Index Cond: (metadata @> '{"doc_type": "FAQ"}'::jsonb)
        Index Searches: 1
        Buffers: shared hit=3
Planning:
  Buffers: shared hit=1
Planning Time: 0.089 ms
Execution Time: 0.146 ms
```

Why did the planner choose a Seq Scan on my table? (2 lines, your own words)

With only 20 rows the entire table fits in 2 shared buffer pages, so reading
everything in one pass costs less than the overhead of an index lookup.

When would it switch to the GIN index? (1 line)

The planner uses the Bitmap Index Scan on ix_documents_metadata_gin once the
table is large enough that filtering first is cheaper than a full scan.
