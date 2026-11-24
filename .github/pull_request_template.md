## What and why

<!-- One or two sentences. Link the Jira issue if there is one. -->

## Type (Conventional Commits)

- [ ] feat
- [ ] fix
- [ ] perf
- [ ] docs
- [ ] refactor / chore

## Checklist

- [ ] `pre-commit run --all-files` passes (ruff, ruff-format, bandit, gitleaks, mypy, prompt validator)
- [ ] No AWS access keys, secrets, real PII or local-machine URLs in the change
- [ ] Prompt changes are in `backend/src/ai/prompts/` with an updated `version`
- [ ] New config values are in `.env.example` (placeholders only)
- [ ] Frontend: `npm run lint` and `npm run build` pass
