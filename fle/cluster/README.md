# Local Factorio Cluster

This directory contains the compose generator and configuration for running
multiple headless Factorio servers locally in Docker.

## Overview

- Create and manage N Factorio server instances with Docker Compose
- Configure server settings, ports, and resources per instance
- Choose between scenarios (`open_world` or `default_lab_scenario`)
- Start from a Factorio save file instead of a scenario

Cluster management lives in `run_envs.py` (`ComposeGenerator` +
`ClusterManager`) and is exposed through the `fle cluster` CLI. The generated
`docker-compose.yml` is written to the platform state directory
(`platformdirs.user_state_dir("fle")`, overridable with `FLE_STATE_DIR`), not
into the package.

## Usage

```bash
# Start a single instance with the default lab scenario
fle cluster start

# Start 5 instances
fle cluster start -n 5

# Start 3 instances with the open_world scenario
fle cluster start -n 3 -s open_world

# Start from a save file
fle cluster start --save path/to/save.zip

# Stop / restart the cluster
fle cluster stop
fle cluster restart

# Show running containers / tail a server's logs
fle cluster show
fle cluster logs factorio_0
```

### Options

- `-n NUMBER` — number of Factorio instances (default: 1)
- `-s SCENARIO` — `open_world` or `default_lab_scenario` (default)
- `--save FILE` — start the server from a save zip (must contain `level.dat`)

## Server configuration

Each instance runs `factoriotools/factorio:<FACTORIO_VERSION>` (the version
constant lives in `fle/commons/constants.py`) with:

- Resource limits: 1 CPU core and 1024MB memory
- Game port (UDP): `34197 + instance_number`
- RCON port (TCP): `27000 + instance_number`
- RCON password: `factorio` (override with `FLE_RCON_PASSWORD`)

## Volume mounts

- Scenarios and config: bundled package resources (read-only binds)
- Mod list: bundled `mods/mod-list.json` (disables Space Age DLC mods)
- Screenshots: `<work_dir>/.fle/data/_screenshots` → `/opt/factorio/script-output`
- Saves (only with `--save`): `<state_dir>/saves`

## Troubleshooting

1. Ensure Docker is running and has enough resources (1 core per instance)
2. `fle cluster logs factorio_<n>` to inspect a server
3. Port conflicts are reported at start; stop the previous cluster with
   `fle cluster stop`
