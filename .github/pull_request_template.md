## Summary

<!-- One-paragraph description of what this PR does and why. -->

## Changes

<!-- Bullet list of the specific changes. -->

-
-

## Testing

- [ ] `black --check agents/ llm/` passes
- [ ] `ruff check agents/ llm/` passes
- [ ] `pytest tests/` passes
- [ ] `shellcheck scripts/**/*.sh` passes (if shell scripts changed)
- [ ] Docker builds succeed (`docker build agents/ llm/ ui/`) (if Dockerfiles changed)
- [ ] `docker compose -f infra/docker-compose.yml config` is valid (if compose files changed)
- [ ] Manually tested on the GPU server (if runtime behaviour changed)

## Related issues

<!-- Closes #... -->
