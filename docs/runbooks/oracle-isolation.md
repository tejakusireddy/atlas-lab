# Isolated runtime profile

The isolated Docker profile excludes datasets from its image build context. API, planner, and trainer services have no outcome volume, host-directory mount, or Docker socket. They run as non-root UIDs with dropped capabilities and a read-only root filesystem. Only release UID 10002 receives the private outcome volume, read-only. Volume contents are owned by that UID with directory mode 0700 and file mode 0600; accidental mounting under the other service UIDs still fails.

```sh
make runtime-image
make isolation
```

`make isolation` provisions a disposable sentinel volume, proves release access and denial for API/planner/trainer UIDs with both absent and accidental mounts, checks the rendered Compose configuration, and deletes its test volume. The real simulator remains separately sandboxed without an oracle mount.

Provision the private snapshot once, after importing and registering the verified local Doyle snapshot:

```sh
docker volume create atlas-lab_oracle-private
docker run --rm --network=none --user=0 \
  --mount type=bind,source="$PWD/data/snapshots/doyle2018-v1",target=/source,readonly \
  --mount type=bind,source="$PWD/infra/runtime/provision_oracle.py",target=/provision.py,readonly \
  --mount type=volume,source=atlas-lab_oracle-private,target=/target \
  atlas-runtime:local python /provision.py
docker compose -f infra/compose/compose.yaml -f infra/compose/isolated.yaml up -d api
```

The provisioner refuses nonempty volumes. It copies only the manifest and private oracle partition, not the candidate pool. Release an eligible run with:

```sh
docker compose -f infra/compose/compose.yaml -f infra/compose/isolated.yaml run --rm release \
  RUN_UUID --snapshot /private-snapshot
```

The API is exposed only on host loopback port 8001. Use the existing local demonstration identities. PostgreSQL migrations and candidate registration remain explicit operator operations.

## Trust boundary

This profile enforces access among application containers, not against the workstation owner, Docker daemon, or privileged provisioning/dispatch operator. The original host snapshot remains readable by its owner for offline evaluation. Running the host development API does not inherit container isolation. Never mount the repository, source snapshot, or Docker socket into the application services. Host dispatch remains a trusted operator function; a constrained remote execution broker and least-privilege database credentials remain production deployment work. This profile still uses local-only demo database credentials and is not a production authentication deployment.
