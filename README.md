# social-approval-relay-edge

Public deploy shell for the social-approval relay. The account that hosts this service can only
deploy from public repositories, while the rendered designs are unreleased marketing material and
live in the private `lareesahu/social-approval-relay` repo.

- `relay/app.py` - the relay itself (WebSocket to the laptop connector + static `/media`).
- `fetch_media.py` - build step: clones the private repo with `GH_TOKEN` and copies its `media/`
  into this service's image, then deletes the clone. No design ever enters public git history.

Env: `RELAY_SECRET` (shared key, same as `relay_deploy.json`), `GH_TOKEN` (read access to the
private repo).
