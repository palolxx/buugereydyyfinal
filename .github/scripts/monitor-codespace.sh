#!/usr/bin/env bash
# Starts/refreshes the repository Codespace and runs the idempotent service launcher.
set -euo pipefail

if [ -z "${GH_CODESPACES_TOKEN:-}" ]; then
  echo "GH_CODESPACES_TOKEN is required. Create a PAT with Codespaces access and add it as a repository secret." >&2
  exit 1
fi

export GH_TOKEN="$GH_CODESPACES_TOKEN"
REPOSITORY="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
REPO_NAME="${REPOSITORY##*/}"
TARGET_CODESPACE="${CODESPACE_NAME:-}"
START_TIMEOUT_SECONDS="${START_TIMEOUT_SECONDS:-360}"

select_codespace() {
  if [ -n "$TARGET_CODESPACE" ]; then
    echo "$TARGET_CODESPACE"
    return
  fi

  gh api --paginate /user/codespaces \
    --jq ".codespaces[] | select(.repository.full_name == \"$REPOSITORY\") | .name" \
    | head -n 1
}

codespace_state() {
  gh api "/user/codespaces/$1" --jq '.state'
}

codespace_name="$(select_codespace)"
if [ -z "$codespace_name" ]; then
  echo "No Codespace found for $REPOSITORY. Set the CODESPACE_NAME repository variable to the Codespace name if needed." >&2
  exit 1
fi

echo "[monitor] Selected Codespace: $codespace_name"
state="$(codespace_state "$codespace_name")"
echo "[monitor] Current state: $state"

if [ "$state" != "Available" ]; then
  echo "[monitor] Starting Codespace..."
  gh api -X POST "/user/codespaces/$codespace_name/start" >/dev/null

  deadline=$((SECONDS + START_TIMEOUT_SECONDS))
  while [ "$SECONDS" -lt "$deadline" ]; do
    state="$(codespace_state "$codespace_name")"
    echo "[monitor] Waiting for Codespace; state=$state"
    if [ "$state" = "Available" ]; then
      break
    fi
    sleep 15
  done

  if [ "$state" != "Available" ]; then
    echo "Codespace did not become Available within ${START_TIMEOUT_SECONDS}s." >&2
    exit 1
  fi
fi

echo "[monitor] Refreshing Codespace services..."
gh codespace ports visibility 443:public -c "$codespace_name" || true
gh codespace ssh -c "$codespace_name" -- \
  bash -lc "if [ -x /workspaces/$REPO_NAME/.devcontainer/monitor-start.sh ]; then /workspaces/$REPO_NAME/.devcontainer/monitor-start.sh; elif [ -x /usr/local/bin/start.sh ]; then /usr/local/bin/start.sh; else bash /workspaces/$REPO_NAME/.devcontainer/start.sh; fi"

echo "[monitor] Codespace refresh completed."
