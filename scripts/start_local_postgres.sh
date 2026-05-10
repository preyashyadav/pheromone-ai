#!/bin/bash
# Start a local Postgres for dashboard development

set -euo pipefail

docker run --name pheromone-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_DB=pheromone \
  -p 5432:5432 \
  -d postgres:16

echo "Postgres running at localhost:5432"
echo "DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pheromone"

