# Database Layer

MongoDB connection management for the Fivos harvester.

## Modules

| File | Role | Key Functions |
|------|------|---------------|
| `db_connection.py` | Singleton MongoClient, collection accessors | `get_db()`, `test_connection()` |

## Collections

| Collection | Contents | Written by |
|------------|----------|------------|
| `devices` | Harvested GUDID-format records | `runner.py --db` or `orchestrator.run_pipeline_batch()` |
| `validationResults` | GUDID comparison results | `orchestrator.run_validation()` |

## Connection

- URI from `FIVOS_MONGO_URI` env var (fallback: `mongodb://localhost:27017/fivos`)
- Default database: `fivos-shared`
- Module-level accessors: `db_connection.client`, `db_connection.db`, `db_connection.devices_collection`, `db_connection.validation_collection`
