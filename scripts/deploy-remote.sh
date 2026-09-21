#!/usr/bin/env bash
# Receives a clean, committed release from deploy.ps1.example. No private defaults.
set -Eeuo pipefail
repo=${1:?Repository path required}
service=${2:?Service name required}
release=${3:?Release commit required}
[[ "$repo" =~ ^/[a-zA-Z0-9_./-]+$ && "$service" =~ ^[a-zA-Z0-9_.@-]+$ && "$release" =~ ^[0-9a-f]{40}$ ]] || exit 2
cd "$repo"
exec 9>"$(git rev-parse --git-path hsbg-deploy.lock)"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
[[ -z "$(git status --porcelain)" ]] || { echo 'Remote checkout is not clean; refusing to overwrite local work.' >&2; exit 1; }
previous=$(git rev-parse HEAD)
changed=0
health() {
    local attempt response code body
    for attempt in {1..6}; do
        if response=$(curl --silent --show-error --connect-timeout 3 --max-time 8 --write-out $'\n%{http_code}' http://127.0.0.1:8000/health); then
            code=${response##*$'\n'}
            body=${response%$'\n'*}
            if [[ "$code" == 200 ]] && python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d,dict) and d.get("status")=="ok" else 1)' <<< "$body"; then
                return 0
            fi
        fi
        sleep 2
    done
    return 1
}
rollback() {
    trap - ERR HUP INT TERM
    if [[ "$changed" == 1 ]]; then
        echo "Deployment failed; restoring $previous" >&2
        if timeout 30 git reset --hard "$previous" && timeout 60 sudo -n systemctl restart "$service" && health; then
            echo 'Previous release restored and health verified.' >&2
        else
            echo 'CRITICAL: recovery failed; manual intervention required.' >&2
        fi
    fi
    exit 1
}
trap rollback ERR HUP INT TERM
# Verify the current release is healthy before changing it.
health
timeout 60 git fetch origin main
git cat-file -e "$release^{commit}"
git merge-base --is-ancestor "$release" origin/main
git merge-base --is-ancestor "$previous" "$release"
changed=1
timeout 30 git merge --ff-only "$release"
timeout 60 sudo -n systemctl restart "$service"
health
trap - ERR HUP INT TERM
echo "Deployment verified: $release"
