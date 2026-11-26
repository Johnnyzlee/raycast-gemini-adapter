# Installation, maintenance and migration

[English README](../README.md) · [中文说明](../README.zh-CN.md)

## Foreground or isolated operation

For a foreground service after preparing `settings.json`:

```sh
./.venv/bin/python adapter.py --settings settings.json
```

Press Control-C to stop. For isolation, use a separate settings file with a free port, separate `state_dir`, a dedicated `providers_file`, restricted `allowed_roots`, and a distinct `service_label`. Pass that file with `--settings` to every management command. The test harness automatically uses an ephemeral port and temporary state.

The advanced `launchagents_dir` setting can place a test service plist outside the normal login-item directory. Its default is `~/Library/LaunchAgents`; routine users can leave it unset.

## Login-service lifecycle

```sh
./.venv/bin/python manage.py install --dry-run
./.venv/bin/python manage.py install
./.venv/bin/python manage.py status
./.venv/bin/python manage.py stop
./.venv/bin/python manage.py start
./.venv/bin/python manage.py restart
```

Installation validates the selected provider and all configured model capabilities, checks the port and backs up the provider file. The service starts before the provider URL changes. Startup failure or a detected concurrent provider edit aborts installation and leaves that configuration intact.

LaunchAgent ownership is checked against this checkout's `adapter.py`. Run management commands in the installed checkout. This also protects an earlier installation when preparing a second source copy.

`stop` unloads the running job but retains its plist, so a later login can load it again. `start` bootstraps a stopped installation. `restart` replaces the running process. Launchd restarts a crashed loaded job. There are no API calls while idle; sleep, logout and shutdown interrupt availability.

## Update and code-version rollback

Record the current commit before updating:

```sh
git rev-parse HEAD
git status --short
# Proceed with a clean tree or preserve your local edits first.
git pull --ff-only
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m unittest -q
./.venv/bin/python manage.py restart
```

For code rollback, stop the service, preserve local changes, check out the previously recorded commit, reinstall its requirements and start it again. Replace `PREVIOUS_COMMIT` with that recorded hash:

```sh
./.venv/bin/python manage.py stop
git checkout --detach PREVIOUS_COMMIT
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python manage.py start
```

Local settings and state are ignored by Git and remain in place. Use a version known to understand the existing database. Before a major migration, stop the service and make a private copy of the configured state directory; it contains conversation data and provider backups.

## Remove the installation

```sh
# Optional: delete registered cloud uploads while the key is available
./.venv/bin/python manage.py cleanup-video-files

# Restore the selected provider's direct Google endpoint and remove startup
./.venv/bin/python manage.py rollback
# `uninstall` is an alias for the same operation.
```

Rollback edits only the installed provider endpoint. Later changes to other provider entries and display names are retained. If the target endpoint has changed, it stops for review. Local files, state and private backups remain. Direct Google routing provides ordinary compatible chat; adapter-managed file and tool workflows require the local service.

## Existing Gemini / DeepSeek setup

- Keep the existing DeepSeek provider. Its adapter conventionally listens on `18766`; Gemini uses `18767`.
- Existing Gemini provider IDs such as `gemini_li` work by setting `provider_id`. Model display names can remain unchanged.
- The source ledger uses additional SQLite tables; old history rows without source metadata remain readable. Sources absent from an old checkpoint are not reconstructed from answer prose.
- A checkpoint includes a model and credential scope. Model changes rebase recovered material without sending old model signatures. Changed or truncated client histories may require a fresh chat.
- To move directories, change port/state/service identity, or adopt this repository from an earlier local installation: use the **old installed checkout** to restore its endpoint and remove its login job first. Preserve your settings and private state backup. Then configure and install the new checkout. Do not run a second job against the same state directory.

## Diagnostic information to share

Share a sanitized `/health` response, Python/Raycast versions, configured model ID, tool type and the error message. Remove credentials, private paths, source-page tokens and user contents. Keep raw provider files, SQLite databases, backups and service logs local. The [contribution guide](../CONTRIBUTING.md) describes reproducible reports with generated fixtures.
