# Database migrations

I am sorry if this is review.
This is my first time building a web application with a database.
I wanted to write down everything I learned for when I need to revisit this.

## Creating a new migration

Create a new migration when adding, removing, or changing a column or table in
`homeshare/models.py`.

### 1. Make model changes

Edit the relevant model in `server/homeshare/models.py`.

### 2. Generate the migration script

From `server/`:

```sh
cd server
FLASK_APP=homeshare.wsgi HOMESHARE_CONFIG_FILE=/path/to/config.json \
  flask db migrate -m "add expiry to share"
```

Alembic compares the model against the current database schema and generates
a new file in `migrations/versions/`.

### 3. Review the generated script

Read the generated script before committing it.
Alembic is good at detecting added/removed tables and columns,
but it cannot detect:

- Column renames (it generates a drop + add instead of an ALTER RENAME)
- Changes to `server_default`
- Certain index changes

Open the generated file and verify both `upgrade()` and `downgrade()`.
Edit as required, and season to taste.

### 4. Apply and test locally

```sh
flask db upgrade        # apply the new migration
flask db downgrade -1   # roll it back
flask db upgrade        # re-apply
```

### 5. Write a test

Add a test function to `server/tests/test_migrations.py`.

There are three things to test for each migration:

- Upgrade
  - Does the schema come out correct?
  - Are the right tables and columns present?
- Downgrade
  - Does `downgrade()` correctly undo the change?
- Idempotency
  - Re-applying a migration after a rollback should produce the same result as the first apply.

## The `sessions` table

Flask-Session creates a `sessions` table in the same database to store
server-side sessions.
This table is note defined in the `Base` metadata and is therefore
invisible to Alembic.
Flask-Session creates and manages this table independently of the migration
scripts.
