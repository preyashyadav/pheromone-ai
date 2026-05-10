#!/bin/bash
# Stop and remove the local Postgres container used for dashboard development

set -euo pipefail

docker stop pheromone-pg && docker rm pheromone-pg

