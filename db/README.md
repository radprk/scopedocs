# Database Schema

Apply the schema in `db/schema.sql` with one of the following options:

## Supabase SQL Editor
1. Open the Supabase SQL editor for your project.
2. Paste the contents of `db/schema.sql`.
3. Run the SQL to create tables and indexes.

## psql
```bash
psql "$DATABASE_URL" -f db/schema.sql
```

## Notes
- `db/schema.sql` includes `pgcrypto` for UUID generation and an optional `pgvector` extension.
- If `pgvector` is not enabled, replace `embedding vector(1536)` with `embedding DOUBLE PRECISION[]` in the `embeddings` table.
