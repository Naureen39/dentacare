#!/bin/sh
# Runs before the container's main command.
#
#   RUN_MIGRATIONS=1   bring the database schema up to date
#   SEED_DEMO=1        load the demo dataset, index the knowledge base and train the no show
#                      model, each only when it has not been done yet
#
# Both are off by default, so the worker and the development containers just start. In the
# production overlay the API container sets them; the worker waits for the API to be healthy.
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    echo "entrypoint: applying database migrations"
    alembic upgrade head
fi

if [ "${SEED_DEMO:-0}" = "1" ]; then
    # The seed script records a marker row, so a restart never duplicates the data.
    echo "entrypoint: seeding the demo dataset (skipped when already loaded)"
    python -m scripts.seed
    echo "entrypoint: indexing the knowledge base (unchanged documents are skipped)"
    python -m scripts.embed_kb
    if [ ! -d "${MODEL_DIR:-models/analytics}" ] || [ -z "$(ls -A "${MODEL_DIR:-models/analytics}" 2>/dev/null)" ]; then
        echo "entrypoint: training the no show model"
        python -m scripts.train_no_show
    fi
fi

exec "$@"
